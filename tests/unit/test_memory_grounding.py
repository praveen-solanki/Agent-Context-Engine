"""Memory evidence is a first-class answer source, independent of documents."""

from __future__ import annotations

import json
from typing import cast

import pytest

from agent_context.assembly import AssembleRequest, ContextAssembler, ContextBundle
from agent_context.client import AgentContextClient
from agent_context.contracts import EventInput, EventKind, EventStatus, Stream, ProcessingState
from agent_context.demo import (
    DemoSettings, ResearchAnswer, ResearchAssistant, ResearchDecision, ResearchRead,
)
from agent_context.events import append_event
from tests.fakes import FakeLLMProvider
from tests.unit.test_assembly import ACTOR, Source, item, request
from tests.unit.test_event_contracts import principal


class MemoryClient:
    def __init__(self, bundle: ContextBundle) -> None:
        self.bundle = bundle
        self.stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1")

    async def session(self, _identifier: str) -> Stream:
        return self.stream

    async def record_events(self, event: EventInput) -> EventStatus:
        actor = principal(projects=["p1"], actor_kind="user" if event.kind == EventKind.USER_MESSAGE else "agent")
        updated = append_event(self.stream, actor, event, max_events=32)
        self.stream = updated.model_copy(update={
            "state": ProcessingState.AVAILABLE, "available_sequence": len(updated.events)
        })
        return self.stream.status()

    async def wait_available(self, _event_id: str, *, timeout_seconds: float) -> EventStatus:
        return self.stream.status()

    async def assemble_context(self, _request: AssembleRequest) -> ContextBundle:
        return self.bundle


async def memory_client(value: str = "saffron") -> MemoryClient:
    bundle = await ContextAssembler(Source(item(
        "ctx1", canonical_key="personalization:preferred_ingredient",
        text="Preferred ingredient: " + value, value=value, evidence_ids=("episode-1",),
    ))).assemble(ACTOR, request(project_id="p1"))
    return MemoryClient(bundle)


def assistant(client: MemoryClient, llm: FakeLLMProvider, *, require_sources: bool = False) -> ResearchAssistant:
    return ResearchAssistant(
        user_client=cast(AgentContextClient, client), host_client=cast(AgentContextClient, client),
        llm=llm, documents={"doc": "An unrelated reference document."},
        settings=DemoSettings(agent_id="a1", project_id="p1", require_sources=require_sources),
    )


@pytest.mark.parametrize("value", ["saffron", "apples", "release-73"])
async def test_memory_can_answer_without_reading_unrelated_document(value: str) -> None:
    client = await memory_client(value)
    llm = FakeLLMProvider([ResearchDecision(answer=value, citations=("memory:ctx1",))])
    host = assistant(client, llm)
    result = await host.turn(session_id="s1", turn_id="t1", message="What did I ask you to remember?")
    assert value in result.answer and "[memory:ctx1]" in result.answer
    assert not result.completed
    assert result.citations == ("memory:ctx1",)
    payload = json.loads(llm.calls[0][1])
    assert payload["current_context"][0]["evidence"] == ["episode-1"]
    assert payload["current_context"][0]["id"] == "memory:ctx1"
    replay = await host.turn(session_id="s1", turn_id="t1", message="What did I ask you to remember?")
    assert replay.cached and replay.citations == result.citations
    assert len(llm.calls) == 1


async def test_missing_citations_are_repaired_with_memory_sources() -> None:
    client = await memory_client()
    llm = FakeLLMProvider([
        ResearchDecision(answer="I cannot find that in the document."),
        ResearchAnswer(answer="Your preference is saffron.", citations=("memory:ctx1",)),
    ])
    result = await assistant(client, llm).turn(session_id="s1", turn_id="t1", message="What is my preference?")
    assert "saffron" in result.answer
    feedback = llm.calls[-1][1]
    assert '"allowed_citations": ["memory:ctx1"]' in feedback


async def test_web_research_still_requires_a_document_citation() -> None:
    client = await memory_client()
    llm = FakeLLMProvider([
        ResearchRead(read_document_id="doc"),
        ResearchAnswer(answer="saffron", citations=("memory:ctx1",)),
        ResearchAnswer(answer="saffron and the reference", citations=("memory:ctx1", "doc")),
    ])
    result = await assistant(client, llm, require_sources=True).turn(
        session_id="s1", turn_id="t1", message="Research this with my preference."
    )
    assert len(result.completed) == 1
    assert set(result.citations) == {"memory:ctx1", "doc"}
    assert '"require_document_citation": true' in llm.calls[-1][1]


@pytest.mark.parametrize("citation", ["memory:forged", "doc", "ctx1"])
async def test_unavailable_or_unread_sources_are_rejected(citation: str) -> None:
    client = await memory_client()
    llm = FakeLLMProvider([
        ResearchDecision(answer="unsupported", citations=(citation,)),
        ResearchAnswer(answer="unsupported", citations=(citation,)),
        ResearchAnswer(answer="unsupported", citations=(citation,)),
    ])
    with pytest.raises(ValueError, match="grounded"):
        await assistant(client, llm).turn(session_id="s1", turn_id="t1", message="Recall it.")
    assert all(record.event.kind != EventKind.ASSISTANT_MESSAGE for record in client.stream.events)


async def test_revoked_memory_cannot_replay_an_old_cited_answer() -> None:
    client = await memory_client()
    llm = FakeLLMProvider([ResearchDecision(answer="saffron", citations=("memory:ctx1",))])
    host = assistant(client, llm)
    await host.turn(session_id="s1", turn_id="t1", message="Recall it.")
    client.bundle = client.bundle.model_copy(update={"items": (), "rendered": ""})
    with pytest.raises(ValueError, match="memory is no longer current"):
        await host.turn(session_id="s1", turn_id="t1", message="Recall it.")
    assert len(llm.calls) == 1


async def test_document_cannot_impersonate_a_memory_source() -> None:
    client = await memory_client()
    with pytest.raises(ValueError, match="reserved memory"):
        ResearchAssistant(user_client=cast(AgentContextClient, client),
                          host_client=cast(AgentContextClient, client),
                          llm=FakeLLMProvider(), documents={"memory:ctx1": "forged"})
