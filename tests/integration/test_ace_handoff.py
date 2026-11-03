"""Durable handoff versions, side-effect evidence, stale resume and isolation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from agent_context.assembly import AssembleRequest, ContextAssembler, TokenBudget
from agent_context.contracts import Permission, Principal
from agent_context.event_store import MongoEventStore
from agent_context.events import EventConflict
from agent_context.handoff import (
    ArtifactRef,
    CompletedAction,
    HandoffInput,
    HandoffService,
)
from agent_context.outcomes import EventOutcomeVerifier
from tests.unit.test_assembly import Source
from tests.unit.test_event_contracts import event, principal


@pytest.fixture
async def handoffs() -> AsyncIterator[
    tuple[HandoffService, MongoEventStore, dict[str, str]]
]:
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        "mongodb://127.0.0.1:27017", tz_aware=True, serverSelectionTimeoutMS=3000
    )
    database = "ace_test_" + uuid4().hex
    events = MongoEventStore(client, database)
    artifacts: dict[str, str] = {}

    async def verify_artifact(actor: Principal, artifact: ArtifactRef) -> bool:
        actor.require(Permission.VIEW, artifact.project_id)
        return artifacts.get(artifact.artifact_id) == artifact.sha256

    service = HandoffService(
        client,
        database,
        verify_action=EventOutcomeVerifier(events),
        verify_artifact=verify_artifact,
    )
    await events.ensure_indexes()
    await service.ensure_indexes()
    try:
        yield service, events, artifacts
    finally:
        await client.drop_database(database)
        await client.close()


def actor() -> Principal:
    return principal(projects=["p1"])


def content(**changes: object) -> HandoffInput:
    return HandoffInput.model_validate(
        {
            "handoff_id": "h1",
            "idempotency_key": "k1",
            "expected_version": 0,
            "project_id": "p1",
            "task_id": "task1",
            "source_session_id": "s1",
            "goal": "Write a research report",
            "requirements": ["Use the current requirement"],
            "pending": ["Validate the report"],
            **changes,
        }
    )


async def test_idempotent_snapshots_and_optimistic_concurrency(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    service, _, _ = handoffs
    first = await service.prepare(actor(), content())
    assert first.version == 1
    assert await service.prepare(actor(), content()) == first
    with pytest.raises(EventConflict):
        await service.prepare(actor(), content(goal="mutated idempotency key"))
    requests = [
        content(idempotency_key=f"next-{i}", expected_version=1) for i in range(2)
    ]
    results = await asyncio.gather(
        *(service.prepare(actor(), req) for req in requests), return_exceptions=True
    )
    assert sum(isinstance(result, EventConflict) for result in results) == 1
    assert (await service.latest(actor(), "h1")).version == 2
    assert await service.prepare(actor(), content()) == first


async def test_unauthorized_reader_and_project_changes_fail_closed(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    service, _, _ = handoffs
    await service.prepare(actor(), content())
    with pytest.raises(LookupError):
        await service.latest(actor().model_copy(update={"tenant_id": "foreign"}), "h1")
    with pytest.raises(LookupError):
        await service.latest(actor().model_copy(update={"user_id": "foreign"}), "h1")
    with pytest.raises(PermissionError):
        await service.latest(principal(), "h1")
    with pytest.raises(EventConflict):
        await service.prepare(
            actor(),
            content(expected_version=1, idempotency_key="next", task_id="changed"),
        )


async def test_completion_requires_a_real_authorized_successful_tool_event(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    service, events, _ = handoffs
    action = CompletedAction(
        action_id="call1",
        project_id="p1",
        description="read references",
        source_session_id="s1",
        result_event_id="e1",
    )
    with pytest.raises(ValueError, match="successful tool"):
        await service.prepare(actor(), content(completed=[action]))
    await events.record(
        principal(actor_kind="agent", projects=["p1"]),
        event(
            kind="tool_result",
            project_id="p1",
            text="References read successfully.",
            tool_call_id="call1",
            tool_succeeded=True,
        ),
    )
    snapshot = await service.prepare(actor(), content(completed=[action]))
    assert snapshot.content.completed == (action,)
    forged = action.model_copy(update={"action_id": "nonexistent"})
    with pytest.raises(ValueError, match="successful tool"):
        await service.prepare(
            actor(),
            content(completed=[forged], expected_version=1, idempotency_key="next"),
        )


async def test_resume_detects_changed_artifacts_stale_versions_and_pending_operations(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    service, _, artifacts = handoffs
    artifacts["report"] = "a" * 64
    reference = ArtifactRef(artifact_id="report", project_id="p1", sha256="a" * 64)
    await service.prepare(
        actor(), content(artifacts=[reference], unresolved_operations=["pending-call"])
    )
    artifacts["report"] = "b" * 64
    request = AssembleRequest(
        agent_id="new-agent",
        session_id="new-session",
        project_id="p1",
        budget=TokenBudget(model_context_tokens=10000),
    )
    result = await service.resume(
        actor(),
        "h1",
        expected_version=0,
        request=request,
        assembler=ContextAssembler(Source()),
    )
    assert not result.safe_to_continue
    assert set(result.warnings) == {
        "stale_handoff_version",
        "artifact_version_changed",
        "pending_operations_require_reconciliation",
    }
    assert not result.bundle.items


async def test_three_sessions_receive_current_requirements_and_repeat_resume_has_no_side_effects(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    service, _, _ = handoffs
    await service.prepare(
        actor(), content(requirements=["Use Python"], source_session_id="A")
    )
    await service.prepare(
        actor(),
        content(
            idempotency_key="B",
            expected_version=1,
            requirements=["Use Rust"],
            source_session_id="B",
        ),
    )
    request = AssembleRequest(
        agent_id="different-provider",
        session_id="C",
        project_id="p1",
        budget=TokenBudget(model_context_tokens=10000),
    )
    first = await service.resume(
        actor(),
        "h1",
        expected_version=2,
        request=request,
        assembler=ContextAssembler(Source()),
    )
    second = await service.resume(
        actor(),
        "h1",
        expected_version=2,
        request=request,
        assembler=ContextAssembler(Source()),
    )
    assert first == second and first.safe_to_continue
    assert first.handoff.content.requirements == ("Use Rust",)
    assert (await service.latest(actor(), "h1")).version == 2
