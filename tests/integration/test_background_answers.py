"""Fast answers consume durable pending inputs without waiting for extraction."""

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_context.client import AgentContextClient
from agent_context.continuity import TaskIntent, WorkspaceAssistant
from agent_context.contracts import RecentRequest
from agent_context.demo import WorkspaceAnswer
from tests.fakes import FakeLLMProvider
from tests.integration.test_ace_handoff import handoffs as handoffs  # noqa: PLC0414 - pytest fixture re-export
from tests.integration.test_ace_workspace import Workspace
from tests.integration.test_ace_workspace import workspace as workspace  # noqa: PLC0414 - pytest fixture re-export
from tests.unit.test_event_contracts import event


async def test_recent_inputs_are_project_scoped_before_any_worker_completes(
    workspace: Workspace,
) -> None:
    await workspace.user.record_events(
        event(text="Budget changed to 3000", project_id="p1")
    )
    response = await workspace.user.http.post(
        "/v1/context/recent",
        json={"project_id": "p1", "session_id": "new-chat", "max_bytes": 2000},
    )
    assert response.status_code == 200
    assert [row["text"] for row in response.json()["items"]] == [
        "Budget changed to 3000"
    ]
    other = await workspace.user.http.post(
        "/v1/context/recent",
        json={"project_id": "p2", "session_id": "new-chat", "max_bytes": 2000},
    )
    assert other.status_code == 200 and other.json()["items"] == []


async def test_fast_turn_returns_before_extraction_and_skips_the_planner(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_wait(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("answer path waited for extraction")

    monkeypatch.setattr(AgentContextClient, "wait_available", no_wait)

    def respond(user: str, schema: type[BaseModel]) -> BaseModel:
        assert schema is not TaskIntent
        return WorkspaceAnswer(answer="Your request is recorded.", citations=())

    assistant = WorkspaceAssistant(
        user=workspace.user,
        host=workspace.host,
        llm=FakeLLMProvider(responder=respond),
        project_id="p1",
        documents={},
        background_updates=True,
    )
    answer = await assistant.turn(session_id="fast", turn_id="one", message="Hello")
    stream = await workspace.user.session("fast")
    assert answer.result.answer and len(stream.events) == 2
    assert stream.available_sequence == 0


async def test_immediate_cross_chat_correction_is_supplied_and_cited(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    from agent_context.contracts import EventKind
    from ui.workspace import restore

    await workspace.user.record_events(
        event(event_id="old", session_id="old", project_id="p1", text="Budget is 2000")
    )
    await workspace.user.record_events(
        event(
            event_id="new",
            session_id="new",
            project_id="p1",
            kind=EventKind.CORRECTION,
            text="Correction: budget is 3000",
        )
    )
    await workspace.user.record_events(
        event(
            event_id="foreign",
            session_id="foreign",
            project_id="p2",
            text="Budget is PRIVATE",
        )
    )

    async def no_wait(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("waited")

    monkeypatch.setattr(AgentContextClient, "wait_available", no_wait)

    def respond(user: str, schema: type[BaseModel]) -> BaseModel:
        payload = json.loads(user)
        recent = payload["recent_user_events"]
        assert [r["text"] for r in recent] == [
            "Budget is 2000",
            "Correction: budget is 3000",
        ]
        assert "PRIVATE" not in user
        return WorkspaceAnswer(answer="3000", citations=(recent[-1]["id"],))

    assistant = WorkspaceAssistant(
        user=workspace.user,
        host=workspace.host,
        llm=FakeLLMProvider(responder=respond),
        project_id="p1",
        documents={},
        background_updates=True,
    )
    result = await assistant.turn(
        session_id="question", turn_id="q", message="What is the budget?"
    )
    assert result.result.context_event_refs[0].event_id == "new"
    stream = await workspace.user.session("question")
    history, pending = restore(stream)
    assert (
        pending is None
        and history[0].result.context_event_refs == result.result.context_event_refs
    )
    # Same-ID retry uses the recorded answer and cannot invoke the model again.
    assert (
        await assistant.turn(
            session_id="question", turn_id="q", message="What is the budget?"
        )
    ).result.cached


async def test_recent_budget_cannot_resurrect_an_older_fact(
    workspace: Workspace,
) -> None:
    from agent_context.contracts import RecentRequest

    await workspace.user.record_events(
        event(event_id="old", session_id="old", project_id="p1", text="Old budget 2000")
    )
    await workspace.user.record_events(
        event(event_id="new", session_id="new", project_id="p1", text="A" * 3000)
    )
    recent = await workspace.user.recent_context(
        RecentRequest(project_id="p1", session_id="question", max_bytes=256)
    )
    assert recent.truncated and not recent.items


async def test_processed_inputs_and_cross_session_derivation_opt_out_are_not_reinjected(
    workspace: Workspace,
) -> None:
    from agent_context.contracts import RecentRequest

    await workspace.user.record_events(
        event(event_id="done", session_id="done", project_id="p1")
    )
    claim = await workspace.events.claim("t1")
    assert claim and await workspace.events.finish(*claim, success=True)
    await workspace.user.record_events(
        event(
            event_id="private",
            session_id="private",
            project_id="p1",
            derive_context=False,
        )
    )
    request = RecentRequest(project_id="p1", session_id="elsewhere")
    assert not (await workspace.user.recent_context(request)).items
    assert (
        len(
            (
                await workspace.user.recent_context(
                    request.model_copy(update={"session_id": "private"})
                )
            ).items
        )
        == 1
    )


async def test_recent_project_window_reports_truncation(workspace: Workspace) -> None:
    from agent_context.contracts import RecentRequest

    for index in range(17):
        await workspace.user.record_events(
            event(event_id=f"e{index}", session_id=f"s{index}", project_id="p1")
        )
    result = await workspace.user.recent_context(
        RecentRequest(project_id="p1", session_id="q", max_bytes=16000, limit=64)
    )
    assert result.truncated and len(result.items) == 16


async def test_recent_window_ignores_fully_processed_conversations(
    workspace: Workspace,
) -> None:
    await workspace.user.record_events(event(project_id="p1", text="Still pending"))
    for index in range(17):
        session_id = f"processed-{index}"
        await workspace.user.record_events(
            event(
                project_id="p1",
                session_id=session_id,
                event_id=session_id,
            )
        )
        # Finish that exact stream; leave the earlier stream pending.
        await workspace.events.collection.update_one(
            {"tenant_id": "t1", "session_id": session_id},
            {"$set": {"data.available_sequence": 1, "data.state": "available"}},
        )
    recent = await workspace.user.recent_context(
        RecentRequest(project_id="p1", session_id="q")
    )
    assert [item.text for item in recent.items] == [
        "Still pending"
    ] and not recent.truncated


async def test_revocation_cannot_reintroduce_old_pending_text(
    workspace: Workspace,
) -> None:
    await workspace.user.record_events(event(project_id="p1", text="An old assertion"))
    await workspace.events.privacy.block(workspace.actor, "derived-memory")
    await workspace.user.record_events(
        event(
            project_id="p1",
            session_id="later",
            event_id="later",
            text="An assertion after revocation",
        )
    )
    recent = await workspace.user.recent_context(
        RecentRequest(project_id="p1", session_id="q")
    )
    assert recent.truncated
    assert [item.text for item in recent.items] == ["An assertion after revocation"]


def maintenance(workspace: Workspace, llm: FakeLLMProvider):
    from agent_context.maintenance import ProjectMaintenance
    from agent_context.project_store import ProjectStore

    return ProjectMaintenance(
        workspace.tasks,
        ProjectStore(
            workspace.events.collection.database.client,
            workspace.events.collection.database.name,
        ),
        {
            "user": workspace.actor,
            "host": workspace.actor.model_copy(
                update={"actor_id": "research-agent", "actor_kind": "agent"}
            ),
        },
        llm,
    )


async def test_worker_finishes_project_updates_after_answer_without_generating_another_answer(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.bridge import EventWorker
    from agent_context.contracts import PROJECT_TASK_ID
    from context_graph.domain.conversation import SessionInput
    from context_graph.pipeline.orchestrator import IngestionReport

    async def no_wait(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("waited")

    monkeypatch.setattr(AgentContextClient, "wait_available", no_wait)
    answerer = FakeLLMProvider(
        responder=lambda user, schema: WorkspaceAnswer(
            answer="Your message is recorded.", citations=()
        )
    )
    assistant = WorkspaceAssistant(
        user=workspace.user,
        host=workspace.host,
        llm=answerer,
        project_id="p1",
        documents={},
        background_updates=True,
    )
    await assistant.turn(session_id="s1", turn_id="one", message="Plan a garden")
    assert (await workspace.user.session("s1")).available_sequence == 0

    def plan(user: str, schema: type[BaseModel]) -> BaseModel:
        assert schema is TaskIntent
        return TaskIntent(goal_quote="Plan a garden")

    planner = FakeLLMProvider(responder=plan)

    async def ingest(session: SessionInput) -> IngestionReport:
        return IngestionReport(run_id="test", session_id=session.session_id)

    worker = EventWorker(
        workspace.events,
        ingest,
        tenant_id="t1",
        maintain=maintenance(workspace, planner),
    )
    assert await worker.run_once()
    state = await workspace.tasks.current(workspace.actor, "p1", PROJECT_TASK_ID)
    assert state.content.goal == "Plan a garden" and state.source_available
    assert len((await workspace.user.session("s1")).events) == 2
    assert not await worker.run_once()


async def test_background_maintenance_failure_does_not_lose_the_recorded_answer(
    workspace: Workspace,
) -> None:
    from agent_context.bridge import EventWorker
    from agent_context.contracts import ProcessingState
    from context_graph.domain.conversation import SessionInput
    from context_graph.pipeline.orchestrator import IngestionReport

    await workspace.user.record_events(event(project_id="p1", background_updates=True))

    async def ingest(session: SessionInput) -> IngestionReport:
        return IngestionReport(run_id="test", session_id=session.session_id)

    async def fail(stream: Any) -> None:
        raise RuntimeError("model unavailable")

    worker = EventWorker(
        workspace.events, ingest, tenant_id="t1", maintain=fail, max_attempts=1
    )
    assert await worker.run_once()
    stream = await workspace.user.session("s1")
    assert stream.state == ProcessingState.DEAD and stream.available_sequence == 0
    # Answering remains possible even when background processing needs review.
    assistant = WorkspaceAssistant(
        user=workspace.user,
        host=workspace.host,
        llm=FakeLLMProvider(
            responder=lambda user, schema: WorkspaceAnswer(
                answer="Your prior request is recorded.",
                citations=(
                    json.loads(user)["recent_user_events"][0]["id"],
                ),
            )
        ),
        project_id="p1",
        documents={},
        background_updates=True,
    )
    result = await assistant.turn(
        session_id="s1", turn_id="new", message="What did I just say?", sequence=2
    )
    assert (
        result.result.answer and len((await workspace.user.session("s1")).events) == 3
    )


async def test_background_updates_cannot_upgrade_the_original_event_permissions(
    workspace: Workspace,
) -> None:
    from agent_context.contracts import PROJECT_TASK_ID, Permission

    initial = event(
        event_id="initial",
        session_id="initial",
        project_id="p1",
        text="Plan a garden",
        background_updates=True,
    )
    await workspace.user.record_events(initial)
    processor = maintenance(
        workspace,
        FakeLLMProvider(
            responder=lambda user, schema: TaskIntent(goal_quote="Plan a garden")
        ),
    )
    await processor(await workspace.user.session("initial"))
    limited = workspace.actor.model_copy(
        update={"permissions": frozenset({Permission.VIEW, Permission.ASSERT})}
    )
    await workspace.events.record(
        limited,
        event(
            event_id="limited",
            session_id="limited",
            project_id="p1",
            text="Plan a library",
            background_updates=True,
        ),
    )
    processor = maintenance(
        workspace,
        FakeLLMProvider(
            responder=lambda user, schema: TaskIntent(goal_quote="Plan a library")
        ),
    )
    with pytest.raises(PermissionError):
        await processor(await workspace.user.session("limited"))
    assert (
        await workspace.tasks.current(workspace.actor, "p1", PROJECT_TASK_ID)
    ).content.goal == "Plan a garden"


async def test_recorded_task_can_be_used_only_when_explicitly_requested(
    workspace: Workspace,
) -> None:
    from agent_context.contracts import PROJECT_TASK_ID
    from tests.unit.test_assembly import request

    await workspace.user.record_events(
        event(project_id="p1", text="Plan a garden", background_updates=True)
    )
    processor = maintenance(
        workspace,
        FakeLLMProvider(
            responder=lambda user, schema: TaskIntent(goal_quote="Plan a garden")
        ),
    )
    await processor(await workspace.user.session("s1"))
    args = request(project_id="p1", task_id=PROJECT_TASK_ID)
    with pytest.raises(httpx.HTTPStatusError) as unavailable:
        await workspace.user.assemble_context(args)
    assert unavailable.value.response.status_code == 503
    bundle = await workspace.user.assemble_context(
        args.model_copy(update={"include_recorded_task": True})
    )
    assert any("Plan a garden" in item.text for item in bundle.items)


async def test_recent_rechecks_privacy_after_read(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.contracts import RecentRequest

    original = workspace.events.privacy.require_active
    count = 0

    async def revoke_between_reads(tenant: str, user: str):
        nonlocal count
        state = await original(tenant, user)
        count += 1
        return state.model_copy(update={"revision": state.revision + int(count > 1)})

    monkeypatch.setattr(
        workspace.events.privacy, "require_active", revoke_between_reads
    )
    with pytest.raises(RuntimeError, match="privacy changed"):
        await workspace.events.recent(
            workspace.actor, RecentRequest(project_id="p1", session_id="s1")
        )


async def test_answer_completes_while_worker_is_blocked(workspace: Workspace) -> None:
    import asyncio
    import json

    from agent_context.bridge import EventWorker
    from context_graph.domain.conversation import SessionInput
    from context_graph.pipeline.orchestrator import IngestionReport

    await workspace.user.record_events(event(project_id="p1", text="Budget 3000"))
    started, release = asyncio.Event(), asyncio.Event()

    async def ingest(session: SessionInput) -> IngestionReport:
        started.set()
        await release.wait()
        return IngestionReport(run_id="test", session_id=session.session_id)

    worker = EventWorker(workspace.events, ingest, tenant_id="t1")
    running = asyncio.create_task(worker.run_once())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        assistant = WorkspaceAssistant(
            user=workspace.user,
            host=workspace.host,
            llm=FakeLLMProvider(
                responder=lambda user, schema: WorkspaceAnswer(
                    answer="3000",
                    citations=(json.loads(user)["recent_user_events"][0]["id"],),
                )
            ),
            project_id="p1",
            documents={},
            background_updates=True,
        )
        result = await assistant.turn(
            session_id="new", turn_id="new", message="What is the budget?"
        )
        assert result.result.answer.startswith("3000") and not running.done()
    finally:
        release.set()
        await running


async def test_late_receipts_preserve_user_order_and_replay_without_replanning(
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_context.contracts import PROJECT_TASK_ID, EventKind

    processor = maintenance(
        workspace,
        FakeLLMProvider(
            responder=lambda user, schema: TaskIntent(goal_quote="Plan a garden")
        ),
    )
    await workspace.user.record_events(
        event(project_id="p1", text="Plan a garden", background_updates=True)
    )
    await processor(await workspace.user.session("s1"))
    # The next user assertion is received before a slow tool from the old turn.
    await workspace.user.record_events(
        event(
            event_id="next",
            session_id="next",
            project_id="p1",
            text="Plan a library",
            background_updates=True,
        )
    )
    await workspace.host.record_events(
        event(
            2,
            event_id="tool",
            project_id="p1",
            agent_id="research-agent",
            kind=EventKind.TOOL_RESULT,
            tool_call_id="read",
            tool_succeeded=True,
            causation_id="e1",
            correlation_id="paper",
            text="A registered paper",
        )
    )
    await processor(await workspace.user.session("s1"))
    state = await workspace.tasks.current(workspace.actor, "p1", PROJECT_TASK_ID)
    assert state.content.source_event_id == "tool" and len(state.content.completed) == 1
    processor = maintenance(
        workspace,
        FakeLLMProvider(
            responder=lambda user, schema: TaskIntent(goal_quote="Plan a library")
        ),
    )
    await processor(await workspace.user.session("next"))
    state = await workspace.tasks.current(workspace.actor, "p1", PROJECT_TASK_ID)
    assert state.content.goal == "Plan a library" and len(state.content.completed) == 1

    # Neither replaying a saved intent nor an older receipt may undo the update.
    async def no_model(**kwargs: Any):
        raise AssertionError("already applied intent was replanned")

    monkeypatch.setattr(processor.llm, "structured", no_model)
    await processor(await workspace.user.session("next"))
    await processor(await workspace.user.session("s1"))
    assert (
        await workspace.tasks.current(workspace.actor, "p1", PROJECT_TASK_ID)
    ) == state


async def test_fast_answer_binds_the_actual_task_revision_during_worker_race(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.contracts import PROJECT_TASK_ID

    await workspace.user.record_events(
        event(project_id="p1", text="Plan a garden", background_updates=True)
    )
    processor = maintenance(
        workspace,
        FakeLLMProvider(
            responder=lambda user, schema: TaskIntent(goal_quote="Plan a garden")
        ),
    )
    await processor(await workspace.user.session("s1"))
    original = workspace.user.recent_context

    async def concurrent_update(request: RecentRequest):
        from agent_context.task_state import TaskUpdate

        state = await workspace.tasks.current(workspace.actor, "p1", PROJECT_TASK_ID)
        await workspace.tasks.update(
            workspace.actor,
            TaskUpdate.model_validate(
                {
                    **state.content.model_dump(),
                    "expected_version": state.version,
                    "idempotency_key": "concurrent",
                    "requirements": ["Budget 3000"],
                }
            ),
        )
        return await original(request)

    monkeypatch.setattr(workspace.user, "recent_context", concurrent_update)
    import json

    def respond(user: str, schema: type[BaseModel]) -> BaseModel:
        payload = json.loads(user)
        task = next(
            row for row in payload["current_context"] if "Budget 3000" in row["text"]
        )
        return WorkspaceAnswer(answer="Budget 3000", citations=(task["id"],))

    assistant = WorkspaceAssistant(
        user=workspace.user,
        host=workspace.host,
        llm=FakeLLMProvider(responder=respond),
        project_id="p1",
        documents={},
        background_updates=True,
    )
    result = await assistant.turn(
        session_id="new", turn_id="q", message="What is the budget?"
    )
    assert result.result.task_context and result.result.task_context.version == 2
