"""SDK host recovery with real durable events and deterministic model decisions."""

from __future__ import annotations

import asyncio
from hashlib import sha256

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from agent_context.api import create_app
from agent_context.assembly import ContextAssembler
from agent_context.client import AgentContextClient
from agent_context.contracts import Principal
from agent_context.demo import (
    DemoSettings,
    ResearchAnswer,
    ResearchAssistant,
    ResearchDecision,
    ResearchRead,
)
from agent_context.event_store import MongoEventStore
from agent_context.handoff import ArtifactRef, CompletedAction, HandoffService
from agent_context.search import BraveSearch, SearchSettings
from tests.fakes import FakeLLMProvider
from tests.integration.test_ace_events import event_store as event_store
from tests.unit.test_assembly import Source, item
from tests.unit.test_event_contracts import principal


class InterruptedProvider(FakeLLMProvider):
    interrupted = False

    async def structured[M: BaseModel](
        self, *, system: str, user: str, schema: type[M], max_output_tokens: int
    ) -> M:
        if schema is ResearchAnswer and not self.interrupted:
            self.interrupted = True
            raise TimeoutError("simulated provider interruption after the read")
        return await super().structured(
            system=system, user=user, schema=schema, max_output_tokens=max_output_tokens
        )


@pytest.mark.parametrize("interrupt", [False, True])
@pytest.mark.parametrize("repair_citations", [False, True])
@pytest.mark.parametrize("web_source", [False, True])
async def test_host_read_recovery_citations_and_cached_replay(
    event_store: MongoEventStore,
    interrupt: bool,
    repair_citations: bool,
    web_source: bool,
) -> None:
    async def deny_action(_: Principal, __: CompletedAction) -> bool:
        return False

    async def deny_artifact(_: Principal, __: ArtifactRef) -> bool:
        return False

    async def ready() -> bool:
        return True

    user_token, host_token = "u" * 40, "h" * 40
    bindings = {
        sha256(user_token.encode()).hexdigest(): principal(projects=["p1"]),
        sha256(host_token.encode()).hexdigest(): principal(
            actor_kind="agent", projects=["p1"]
        ),
    }
    handoffs = HandoffService(
        event_store.collection.database.client,
        event_store.collection.database.name,
        verify_action=deny_action,
        verify_artifact=deny_artifact,
    )
    source = Source(
        item(canonical_key="personalization:report_language", value="Spanish")
    )
    app = create_app(
        events=event_store,
        assembler=ContextAssembler(source),
        handoffs=handoffs,
        auth_bindings=bindings,
        ready=ready,
    )
    transport = httpx.ASGITransport(app=app)
    user = AgentContextClient(
        base_url="http://test", bearer_token=user_token, transport=transport
    )
    host = AgentContextClient(
        base_url="http://test", bearer_token=host_token, transport=transport
    )
    documents = {"doc": "Option A works offline."}
    document_id = "doc"
    if web_source:
        provider_settings = SearchSettings.model_validate(
            {"api_key": SecretStr("unit-search-key"), "_env_file": None}
        )
        response_data = {
            "web": {
                "results": [
                    {
                        "title": "Public research evidence",
                        "url": "https://example.org/research",
                        "description": "Option A works offline.",
                    }
                ]
            }
        }
        async with BraveSearch(
            provider_settings,
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(200, json=response_data)
                )
            ),
        ) as provider:
            result = await provider.search("offline research options")
        source = result.results[0]
        document_id = source.document_id
        documents = {document_id: source.as_document()}
    replies: list[BaseModel] = [
        ResearchRead(read_document_id=document_id)
        if web_source
        else ResearchDecision(read_document_id=document_id)
    ]
    if repair_citations:
        replies.append(
            ResearchAnswer(
                answer="La opción A es adecuada.", citations=("invented-id",)
            )
        )
    replies.append(
        ResearchAnswer(answer="La opción A es adecuada.", citations=(document_id,))
    )
    llm = InterruptedProvider(replies) if interrupt else FakeLLMProvider(replies)
    assistant = ResearchAssistant(
        user_client=user,
        host_client=host,
        llm=llm,
        documents=documents,
        settings=DemoSettings(
            agent_id="a1",
            project_id="p1",
            event_timeout_seconds=5,
            require_sources=web_source,
        ),
    )

    async def process() -> None:
        while True:
            claim = await event_store.claim("t1")
            if claim:
                assert await event_store.finish(*claim, success=True)
            await asyncio.sleep(0.01)

    task = asyncio.create_task(process())
    try:
        if interrupt:
            with pytest.raises(TimeoutError):
                await assistant.turn(
                    session_id="s1",
                    turn_id="t1",
                    message="Compare the provided options.",
                )
        result = await assistant.turn(
            session_id="s1", turn_id="t1", message="Compare the provided options."
        )
        assert f"[{document_id}]" in result.answer and len(result.completed) == 1
        assert result.citations == (document_id,)
        assert "Write the final answer in Spanish" in llm.calls[-1][0]
        before = await user.session("s1")
        replay = await assistant.turn(
            session_id="s1", turn_id="t1", message="Compare the provided options."
        )
        assert replay.cached and replay.model_calls == 0
        assert replay.citations == result.citations
        assert (await user.session("s1")).events == before.events
        if web_source:
            tool = next(
                record
                for record in before.events
                if record.event.kind.value == "tool_result"
            )
            assert "https://example.org/research" in tool.event.text
            assert tool.event.correlation_id == document_id
        with pytest.raises(ValueError, match="different input"):
            await assistant.turn(session_id="s1", turn_id="t1", message="Changed input")
        changed = ResearchAssistant(
            user_client=user,
            host_client=host,
            llm=llm,
            documents={document_id: "changed source"},
            settings=assistant.settings,
        )
        with pytest.raises(ValueError, match="source snapshot changed"):
            await changed.turn(
                session_id="s1", turn_id="t1", message="Compare the provided options."
            )
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await user.aclose()
        await host.aclose()
