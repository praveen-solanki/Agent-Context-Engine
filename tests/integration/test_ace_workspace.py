"""Workspace API and SDK integration over real Mongo; no paid model calls.

Worker availability is advanced explicitly here. Existing ingestion/extraction
is reused, not exercised as a full pipeline by these focused interaction tests.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
from pydantic import BaseModel

from agent_context.api import create_app
from agent_context.assembly import ContextAssembler
from agent_context.client import AgentContextClient
from agent_context.continuity import (
    PROJECT_TASK_ID,
    ReferencedChange,
    TaskIntent,
    WorkspaceAssistant,
)
from agent_context.contracts import (
    EventStatus,
    Permission,
    Principal,
    RevocationInput,
)
from agent_context.demo import WorkspaceAnswer, WorkspaceDecision
from agent_context.event_store import MongoEventStore
from agent_context.handoff import HandoffService, ReportedProgress
from agent_context.navigation import SessionTitle
from agent_context.task_state import TaskCandidateSource, TaskStateService
from tests.fakes import FakeLLMProvider
from tests.integration.test_ace_handoff import handoffs as handoffs
from tests.unit.test_assembly import Source
from tests.unit.test_event_contracts import event, principal
from ui.workspace import restore


@dataclass
class Workspace:
    events: MongoEventStore
    tasks: TaskStateService
    user: AgentContextClient
    host: AgentContextClient
    actor: Principal


@pytest.fixture
async def workspace(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Workspace]:
    snapshots, events, _ = handoffs
    tasks = TaskStateService(snapshots, events)
    user = principal(projects=["p1", "p2"], permissions=frozenset(Permission))
    host = principal(
        projects=["p1", "p2"],
        actor_kind="agent",
        actor_id="research-agent",
        permissions=frozenset(Permission),
    )

    async def ready() -> bool:
        return True

    app = create_app(
        events=events,
        handoffs=snapshots,
        tasks=tasks,
        assembler=ContextAssembler(
            Source(), required_sources=(TaskCandidateSource(tasks),)
        ),
        ready=ready,
        auth_bindings={
            hashlib.sha256(token.encode()).hexdigest(): actor
            for token, actor in [("u" * 40, user), ("h" * 40, host)]
        },
    )
    first = AgentContextClient(
        base_url="http://test",
        bearer_token="u" * 40,
        transport=httpx.ASGITransport(app=app),
    )
    second = AgentContextClient(
        base_url="http://test",
        bearer_token="h" * 40,
        transport=httpx.ASGITransport(app=app),
    )
    original = AgentContextClient.wait_available

    async def advance(
        self: AgentContextClient, event_id: str, *, timeout_seconds: float = 2
    ) -> EventStatus:
        while claim := await events.claim("t1"):
            assert await events.finish(*claim, success=True)
        return await original(self, event_id, timeout_seconds=timeout_seconds)

    monkeypatch.setattr(AgentContextClient, "wait_available", advance)
    try:
        yield Workspace(events, tasks, first, second, user)
    finally:
        await first.aclose()
        await second.aclose()


async def test_navigation_pagination_rename_and_ownership(workspace: Workspace) -> None:
    env = workspace
    assert [entry.project_id for entry in (await env.user.projects()).projects] == [
        "p1",
        "p2",
    ]
    for identifier, project, actor in [
        ("alpha", "p1", env.actor),
        ("beta", "p1", env.actor),
        ("other-project", "p2", env.actor),
        (
            "other-user",
            "p1",
            env.actor.model_copy(update={"user_id": "u2", "actor_id": "u2"}),
        ),
        ("other-tenant", "p1", env.actor.model_copy(update={"tenant_id": "t2"})),
    ]:
        await env.events.record(
            actor,
            event(
                session_id=identifier,
                event_id=identifier,
                project_id=project,
                text="Conversation " + identifier,
            ),
        )
    first = await env.user.sessions("p1", limit=1)
    assert (
        len(first.sessions) == 1
        and first.sessions[0].session_id == "beta"
        and first.next_cursor
    )
    second = await env.user.sessions("p1", limit=1, cursor=first.next_cursor)
    assert [entry.session_id for entry in second.sessions] == [
        "alpha"
    ] and second.next_cursor is None
    with pytest.raises(httpx.HTTPStatusError) as invalid:
        await env.user.sessions("p2", cursor=first.next_cursor)
    assert invalid.value.response.status_code == 422
    with pytest.raises(httpx.HTTPStatusError) as denied:
        await env.user.sessions("ungranted")
    assert denied.value.response.status_code == 403
    with pytest.raises(httpx.HTTPStatusError):
        await env.user.rename_session("other-user", "Forbidden title")
    before = await env.user.session("alpha")
    old = await env.events.collection.find_one(
        {"session_id": "alpha", "tenant_id": "t1"}
    )
    renamed = await env.user.rename_session("alpha", "Archive research")
    assert renamed.title == "Archive research"
    assert await env.user.session("alpha") == before
    assert old
    await env.events.record(env.actor, before.events[0].event)
    after = await env.events.collection.find_one(
        {"session_id": "alpha", "tenant_id": "t1"}
    )
    assert (
        after
        and after["updated_at"] == old["updated_at"]
        and after["console_title"] == "Archive research"
    )
    with pytest.raises(PermissionError):
        await env.events.rename(
            env.actor.model_copy(update={"actor_kind": "agent"}),
            "alpha",
            SessionTitle(title="No"),
        )
    with pytest.raises(ValueError):
        await env.events.rename(env.actor, "alpha", SessionTitle(title=" "))
    # Sessions created before navigation metadata was introduced remain reachable.
    await env.events.collection.update_one(
        {"session_id": "alpha", "tenant_id": "t1"},
        {"$unset": {"updated_at": "", "console_title": ""}},
    )
    legacy = await env.user.sessions("p1")
    assert (
        legacy.sessions[-1].session_id == "alpha"
        and legacy.sessions[-1].updated_at is None
    )
    assert legacy.sessions[-1].title == "Conversation"


async def test_navigation_respects_readonly_grants_and_erasure_fence(
    workspace: Workspace,
) -> None:
    env = workspace
    await env.events.record(env.actor, event(project_id="p1"))
    readonly = env.actor.model_copy(
        update={"permissions": frozenset({Permission.VIEW})}
    )
    assert (await env.events.sessions(readonly, "p1")).sessions
    with pytest.raises(PermissionError):
        await env.events.rename(readonly, "s1", SessionTitle(title="No"))
    await env.events.privacy.quarantine(env.actor)
    with pytest.raises(httpx.HTTPStatusError) as blocked:
        await env.user.sessions("p1")
    assert blocked.value.response.status_code == 403


async def test_chat_updates_current_task_reopens_and_retries_without_reexecution(
    workspace: Workspace,
) -> None:
    env = workspace
    intents = [
        TaskIntent(
            goal_quote="Build the archive",
            add_requirements=("Keep citations",),
            add_steps=("Read the paper", "Write the report"),
        ),
        TaskIntent(
            report_completed=(
                ReferencedChange(
                    target="Read the paper", quote="I finished reading the paper"
                ),
            )
        ),
        TaskIntent(),
    ]

    def respond(payload: str, schema: type[BaseModel]) -> BaseModel:
        if schema is TaskIntent:
            return intents.pop(0)
        data = json.loads(payload.split("\n")[0])
        citations = tuple(
            row["id"] for row in data["current_context"] if row["evidence"]
        )
        return schema.model_validate(
            {
                "answer": "Continue from the current project plan.",
                "citations": citations,
                "suggested_next_steps": ["Check the source list"],
            }
        )

    llm = FakeLLMProvider(responder=respond)
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    first = await assistant.turn(
        session_id="s1",
        turn_id="t1",
        message="Build the archive. Keep citations. Read the paper. Write the report.",
    )
    assert first.task and first.task.version == 1 and first.task.source_available
    assert first.result.task_context and first.result.task_context.version == 1
    second = await assistant.turn(
        session_id="s1",
        turn_id="t2",
        sequence=first.result.next_sequence,
        message="I finished reading the paper",
    )
    assert second.task and second.task.version == 2
    assert second.task.content.pending == ("Write the report",)
    assert (
        len(second.task.content.reported_completed) == 1
        and not second.task.content.completed
    )
    assert second.task.content.requirements == ("Keep citations",)
    resumed = await assistant.turn(
        session_id="new-session", turn_id="t3", message="Where were we?"
    )
    assert (
        resumed.task
        and resumed.task.version == 2
        and resumed.result.task_context
        and resumed.result.task_context.version == 2
    )
    final_payload = json.loads(llm.calls[-1][1])
    assert "Write the report" in str(final_payload["current_context"])
    assert "reported_completed" in str(final_payload["current_context"])
    calls = len(llm.calls)
    replay = await assistant.turn(
        session_id="s1",
        turn_id="t1",
        message="Build the archive. Keep citations. Read the paper. Write the report.",
    )
    assert replay.result.cached and len(llm.calls) == calls
    assert replay.result.task_context and replay.result.task_context.version == 1
    assert (await env.user.current_task("p1", PROJECT_TASK_ID)).version == 2
    history, pending = restore(await env.user.session("s1"))
    assert (
        len(history) == 2 and pending is None and all(turn.recorded for turn in history)
    )
    assert history[0].result.suggested_next_steps == ("Check the source list",)
    assert [row.session_id for row in (await env.user.sessions("p1")).sessions] == [
        "new-session",
        "s1",
    ]


async def test_actual_receipts_are_verified_without_turning_suggestions_into_plan(
    workspace: Workspace,
) -> None:
    env = workspace
    llm = FakeLLMProvider(
        [
            TaskIntent(
                goal_quote="Read the document", add_steps=("Read the document",)
            ),
            WorkspaceDecision(read_document_id="paper"),
            WorkspaceAnswer(
                answer="The document has been read.",
                citations=("paper",),
                suggested_next_steps=("Write a summary",),
            ),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user,
        host=env.host,
        llm=llm,
        project_id="p1",
        documents={"paper": "A real registered source snapshot."},
    )
    outcome = await assistant.turn(
        session_id="s1", turn_id="read", message="Read the document"
    )
    assert outcome.task and outcome.task.version == 2
    assert (
        len(outcome.task.content.completed) == 1
        and not outcome.task.content.reported_completed
    )
    assert "Write a summary" not in outcome.task.content.pending
    assert (
        outcome.task.content.completed[0].description
        == "Read registered document paper"
    )
    assert not outcome.task.warnings
    replay = await assistant.turn(
        session_id="s1", turn_id="read", message="Read the document"
    )
    assert replay.result.cached and len(llm.calls) == 3
    assert (
        len(
            [
                record
                for record in (await env.user.session("s1")).events
                if record.event.tool_succeeded
            ]
        )
        == 1
    )


async def test_ambiguous_plan_change_is_saved_as_clarification_not_work(
    workspace: Workspace,
) -> None:
    env = workspace
    llm = FakeLLMProvider(
        [
            TaskIntent(clarification="Which step should I add?"),
            WorkspaceAnswer(answer="Which step should I add?", citations=()),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    outcome = await assistant.turn(
        session_id="s1", turn_id="yes", message="Yes, do that."
    )
    assert outcome.clarification and outcome.task is None
    assert len((await env.user.session("s1")).events) == 2
    replay = await assistant.turn(
        session_id="s1", turn_id="yes", message="Yes, do that."
    )
    assert replay.result.cached and len(llm.calls) == 2


async def test_interrupted_correction_recovers_exact_target_before_answering(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = workspace
    target = RevocationInput(
        item_id="memory-old", expected_fingerprint="old-fingerprint"
    )
    failures: list[RevocationInput] = []

    async def unavailable(self: AgentContextClient, request: RevocationInput) -> None:
        failures.append(request)
        raise ConnectionError("interrupted")

    monkeypatch.setattr(AgentContextClient, "revoke", unavailable)
    llm = FakeLLMProvider(
        [
            TaskIntent(),
            WorkspaceAnswer(answer="Updated context recorded.", citations=()),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    with pytest.raises(ConnectionError):
        await assistant.turn(
            session_id="s1",
            turn_id="fix",
            message="The updated instruction is to use citations.",
            correction=True,
            correction_target=target,
        )
    stream = await env.user.session("s1")
    history, pending = restore(stream)
    assert (
        not history
        and pending
        and pending.correction_target == target
        and not llm.calls
    )

    async def revoke(self: AgentContextClient, request: RevocationInput) -> None:
        failures.append(request)
        await env.events.privacy.block(env.actor, request.item_id)

    monkeypatch.setattr(AgentContextClient, "revoke", revoke)
    outcome = await assistant.turn(
        session_id="s1",
        turn_id=pending.turn_id,
        message=pending.message,
        sequence=pending.sequence,
        correction=pending.correction,
        correction_target=pending.correction_target,
    )
    assert outcome.result.answer and failures == [target, target]
    assert (
        target.item_id
        in (await env.events.privacy.require_active("t1", "u1")).blocked_item_ids
    )
    assert len((await env.user.session("s1")).events) == 2


async def test_task_reports_must_reference_the_authenticated_users_exact_statement(
    workspace: Workspace,
) -> None:
    from agent_context.task_state import TaskUpdate

    env = workspace
    await env.events.record(
        env.actor, event(project_id="p1", text="I finished reading")
    )
    data = {
        "project_id": "p1",
        "task_id": "project-work",
        "goal": "Build archive",
        "source_session_id": "s1",
        "source_event_id": "e1",
        "expected_version": 0,
        "idempotency_key": "initial",
    }
    for report in [
        ReportedProgress(
            description="Read",
            quote="Invented",
            source_session_id="s1",
            source_event_id="e1",
        ),
        ReportedProgress(
            description="Read",
            quote="I finished reading",
            source_session_id="foreign",
            source_event_id="e1",
        ),
    ]:
        with pytest.raises(PermissionError, match="exact source quote"):
            await env.tasks.update(
                env.actor,
                TaskUpdate.model_validate({**data, "reported_completed": [report]}),
            )
    report = ReportedProgress(
        description="Read",
        quote="I finished reading",
        source_session_id="s1",
        source_event_id="e1",
    )
    state = await env.tasks.update(
        env.actor, TaskUpdate.model_validate({**data, "reported_completed": [report]})
    )
    assert state.content.reported_completed == (report,) and not state.content.completed


async def test_retry_after_a_tool_result_recovers_receipt_without_rerunning_it(
    workspace: Workspace,
) -> None:
    env = workspace
    failed = False

    def respond(payload: str, schema: type[BaseModel]) -> BaseModel:
        nonlocal failed
        if schema is TaskIntent:
            return TaskIntent(goal_quote="Review the source")
        if schema is WorkspaceDecision:
            return WorkspaceDecision(read_document_id="paper")
        if not failed:
            failed = True
            raise RuntimeError("answer provider interrupted after tool recording")
        return WorkspaceAnswer(answer="The source was read.", citations=("paper",))

    llm = FakeLLMProvider(responder=respond)
    assistant = WorkspaceAssistant(
        user=env.user,
        host=env.host,
        llm=llm,
        project_id="p1",
        documents={"paper": "A registered source."},
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        await assistant.turn(
            session_id="s1", turn_id="interrupted", message="Review the source"
        )
    before = await env.user.session("s1")
    assert len(before.events) == 2 and before.events[-1].event.tool_succeeded
    _, pending = restore(before)
    assert pending and pending.turn_id == "interrupted"
    recovered = await assistant.turn(
        session_id="s1",
        turn_id=pending.turn_id,
        message=pending.message,
        sequence=pending.sequence,
    )
    assert recovered.task and len(recovered.task.content.completed) == 1
    assert len((await env.user.session("s1")).events) == 3
    assert (
        sum("Identify explicit task changes" in system for system, _ in llm.calls) == 1
    )


async def test_concurrent_plan_change_is_surfaced_instead_of_claiming_a_current_answer(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.task_state import TaskUpdate

    env = workspace
    llm = FakeLLMProvider(
        [
            TaskIntent(goal_quote="Plan the report"),
            WorkspaceAnswer(
                answer="Here is the plan.",
                citations=(
                    "memory:"
                    + env.tasks.identifier(env.actor, "p1", PROJECT_TASK_ID)
                    + ":1",
                ),
            ),
        ]
    )
    original = llm.structured

    async def structured[M: BaseModel](
        *, system: str, user: str, schema: type[M], max_output_tokens: int
    ) -> M:
        if schema is WorkspaceAnswer:
            state = await env.user.current_task("p1", PROJECT_TASK_ID)
            await env.user.update_task(
                TaskUpdate.model_validate(
                    {
                        **state.content.model_dump(),
                        "expected_version": state.version,
                        "idempotency_key": "concurrent",
                        "pending": ["Review the revised plan"],
                    }
                )
            )
        return await original(
            system=system, user=user, schema=schema, max_output_tokens=max_output_tokens
        )

    monkeypatch.setattr(llm, "structured", structured)
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    outcome = await assistant.turn(
        session_id="s1", turn_id="drift", message="Plan the report"
    )
    assert outcome.warning and "changed while answering" in outcome.warning
    assert (
        outcome.task
        and outcome.task.version == 2
        and outcome.task.content.pending == ("Review the revised plan",)
    )
    assert outcome.result.task_context and outcome.result.task_context.version == 1


async def test_old_unfinished_request_cannot_overwrite_a_newer_conversation_plan(
    workspace: Workspace,
) -> None:
    from agent_context.events import EventConflict

    env = workspace
    failed = False

    def respond(payload: str, schema: type[BaseModel]) -> BaseModel:
        nonlocal failed
        if schema is TaskIntent:
            return TaskIntent(goal_quote="Build the archive")
        failed = True
        raise RuntimeError("answer interrupted")

    llm = FakeLLMProvider(responder=respond)
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    with pytest.raises(RuntimeError):
        await assistant.turn(
            session_id="old-session", turn_id="old", message="Build the archive"
        )
    assert failed
    fresh = WorkspaceAssistant(
        user=env.user,
        host=env.host,
        llm=FakeLLMProvider(
            [
                TaskIntent(goal_quote="Prepare a budget"),
                WorkspaceAnswer(
                    answer="Budget objective saved.",
                    citations=(
                        "memory:"
                        + env.tasks.identifier(env.actor, "p1", PROJECT_TASK_ID)
                        + ":2",
                    ),
                ),
            ]
        ),
        project_id="p1",
        documents={},
    )
    newer = await fresh.turn(
        session_id="new-session", turn_id="new", message="Prepare a budget"
    )
    assert newer.task and newer.task.version == 2
    calls = len(llm.calls)
    with pytest.raises(EventConflict, match="project plan changed"):
        await assistant.turn(
            session_id="old-session", turn_id="old", message="Build the archive"
        )
    assert len(llm.calls) == calls
    current = await env.user.current_task("p1", PROJECT_TASK_ID)
    assert current.version == 2 and current.content.goal == "Prepare a budget"


async def seed_active_plan(env: Workspace) -> None:
    from agent_context.contracts import utcnow
    from agent_context.task_state import TaskUpdate

    await env.user.record_events(
        event(
            event_id="seed",
            session_id="seed-session",
            project_id="p1",
            event_time=utcnow(),
            text="Prepare the project. Retain the budget constraint.",
        )
    )
    await env.user.wait_available("seed")
    await env.user.update_task(
        TaskUpdate(
            project_id="p1",
            task_id=PROJECT_TASK_ID,
            source_session_id="seed-session",
            source_event_id="seed",
            goal="Prepare the project",
            requirements=("Retain the budget constraint",),
            expected_version=0,
            idempotency_key="seed",
        )
    )


@pytest.mark.parametrize(
    ("message", "paraphrase"),
    [
        (
            "The supplier can deliver on Tuesdays only.",
            "Delivery is restricted to Tuesday",
        ),
        ("La livraison est possible uniquement le jeudi.", "Livraison le jeudi"),
    ],
)
async def test_invalid_constraint_quote_is_repaired_without_discarding_the_update(
    workspace: Workspace, message: str, paraphrase: str
) -> None:
    env = workspace
    await seed_active_plan(env)
    citation = "memory:" + env.tasks.identifier(env.actor, "p1", PROJECT_TASK_ID) + ":2"
    llm = FakeLLMProvider(
        [
            TaskIntent(add_requirements=(paraphrase,)),
            TaskIntent(add_requirements=(message,)),
            WorkspaceAnswer(
                answer="The constraint is now part of the current plan.",
                citations=(citation,),
            ),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    outcome = await assistant.turn(
        session_id="update", turn_id="update", message=message
    )
    assert outcome.task and outcome.task.version == 2
    assert outcome.task.content.requirements == (
        "Retain the budget constraint",
        message,
    )
    assert outcome.result.citations == (citation,) and outcome.result.model_calls == 3
    assert "validation_feedback" in llm.calls[1][1]


async def test_planner_commentary_cannot_bypass_grounded_recall(
    workspace: Workspace,
) -> None:
    env = workspace
    await seed_active_plan(env)
    citation = "memory:" + env.tasks.identifier(env.actor, "p1", PROJECT_TASK_ID) + ":1"
    unsafe = "The project is complete and no work remains."
    llm = FakeLLMProvider(
        [
            TaskIntent(clarification=unsafe),
            WorkspaceAnswer(answer="Uncited summary", citations=()),
            WorkspaceAnswer(
                answer="The project is active. No next step has been agreed yet.",
                citations=(citation,),
            ),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    outcome = await assistant.turn(
        session_id="recall",
        turn_id="recall",
        message="What do you remember and what remains?",
    )
    assert unsafe not in outcome.result.answer
    assert outcome.result.citations == (citation,)
    assert outcome.result.task_context and outcome.result.task_context.version == 1
    assert (
        len(llm.calls) == 3 and outcome.task and outcome.task.content.status == "active"
    )
    payload = json.loads(llm.calls[1][1])
    assert payload["task_update_feedback"] == "needs_clarification"
    assert all(unsafe not in payload for _, payload in llm.calls[1:])
    assert "empty pending" in llm.calls[-1][0]
    history, _ = restore(await env.user.session("recall"))
    assert history[0].result.citations == (citation,)


async def test_unrepairable_plan_proposal_preserves_state_and_still_grounds_the_answer(
    workspace: Workspace,
) -> None:
    env = workspace
    await seed_active_plan(env)
    citation = "memory:" + env.tasks.identifier(env.actor, "p1", PROJECT_TASK_ID) + ":1"
    invalid = TaskIntent(add_requirements=("A quote absent from the actual message",))
    llm = FakeLLMProvider(
        [
            invalid,
            invalid,
            invalid,
            WorkspaceAnswer(
                answer="The requested change was not applied. The current goal remains active.",
                citations=(citation,),
            ),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    outcome = await assistant.turn(
        session_id="invalid", turn_id="invalid", message="Adjust the constraints"
    )
    assert outcome.clarification and outcome.task and outcome.task.version == 1
    assert outcome.task.content.requirements == ("Retain the budget constraint",)
    assert outcome.result.citations == (citation,) and outcome.result.model_calls == 4
    assert len(llm.calls) == 4


async def test_stale_requirement_reference_is_repaired_before_replacing_a_constraint(
    workspace: Workspace,
) -> None:
    env = workspace
    await seed_active_plan(env)
    quote = "The spending cap is now 500 units"
    llm = FakeLLMProvider(
        [
            TaskIntent(
                remove_requirements=(
                    ReferencedChange(target="Old budget", quote=quote),
                ),
                add_requirements=(quote,),
            ),
            TaskIntent(
                remove_requirements=(
                    ReferencedChange(
                        target="Retain the budget constraint", quote=quote
                    ),
                ),
                add_requirements=(quote,),
            ),
            WorkspaceAnswer(
                answer="The spending requirement was updated.",
                citations=(
                    "memory:"
                    + env.tasks.identifier(env.actor, "p1", PROJECT_TASK_ID)
                    + ":2",
                ),
            ),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    outcome = await assistant.turn(
        session_id="replacement", turn_id="replacement", message=quote
    )
    assert (
        outcome.task
        and outcome.task.version == 2
        and outcome.task.content.requirements == (quote,)
    )
    assert outcome.task.content.goal == "Prepare the project"
    assert "missing current entry" in llm.calls[1][1]


async def test_oversized_repair_proposal_never_reaches_the_provider_or_mutates_state(
    workspace: Workspace,
) -> None:
    env = workspace
    await seed_active_plan(env)
    llm = FakeLLMProvider(
        [TaskIntent(add_requirements=tuple("x" * 4000 for _ in range(16)))]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    with pytest.raises(ValueError, match="repair exceeds the context budget"):
        await assistant.turn(
            session_id="bounded", turn_id="bounded", message="Change the budget"
        )
    assert len(llm.calls) == 1
    assert (await env.user.current_task("p1", PROJECT_TASK_ID)).version == 1


async def test_approved_goal_echo_does_not_discard_a_natural_constraint_update(
    workspace: Workspace,
) -> None:
    env = workspace
    await seed_active_plan(env)
    message = "The venue only permits deliveries before noon."
    citation = "memory:" + env.tasks.identifier(env.actor, "p1", PROJECT_TASK_ID) + ":2"
    llm = FakeLLMProvider(
        [
            TaskIntent(goal_quote="Prepare the project", add_requirements=(message,)),
            WorkspaceAnswer(
                answer="The new constraint is saved in the plan.", citations=(citation,)
            ),
        ]
    )
    assistant = WorkspaceAssistant(
        user=env.user, host=env.host, llm=llm, project_id="p1", documents={}
    )
    result = await assistant.turn(
        session_id="natural-update", turn_id="update", message=message
    )
    assert (
        result.task
        and result.task.version == 2
        and result.task.content.goal == "Prepare the project"
    )
    assert message in result.task.content.requirements
    assert len(llm.calls) == 2 and result.result.citations == (citation,)
