"""Canonical state uses the existing handoff CAS and authenticated event proofs."""

import pytest
import asyncio
import hashlib
import json

from agent_context.assembly import ContextAssembler, MandatoryContextTooLarge
from agent_context.task_state import TaskStateService, TaskUpdate, TaskCandidateSource
from agent_context.events import EventConflict
from tests.integration.test_ace_handoff import (
    handoffs as handoffs,
    actor as snapshot_actor,
    content,
)
from agent_context.contracts import Permission, Principal
from agent_context.handoff import (
    HandoffService,
    WorkState,
    CompletedAction,
    HandoffArtifact,
    ArtifactRef,
)
from agent_context.event_store import MongoEventStore
from tests.unit.test_event_contracts import event, principal
from tests.unit.test_assembly import Source, request


def actor() -> Principal:
    return snapshot_actor().model_copy(update={"permissions": frozenset(Permission)})


async def test_current_task_requirements_override_old_snapshot_and_fit_atomically(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    snapshots, events, _ = handoffs
    tasks = TaskStateService(snapshots, events)
    await events.record(
        actor(), event(project_id="p1", text="Use Python; audit the report.")
    )
    body = content().model_dump(include=set(WorkState.model_fields))
    update = TaskUpdate.model_validate(
        {
            **body,
            "source_event_id": "e1",
            "expected_version": 0,
            "idempotency_key": "task-A",
            "requirements": ["Use Python"],
            "must_keep": ["Use Python"],
            "pending": ["obsolete", "audit"],
        }
    )
    first = await tasks.update(actor(), update)
    assert first.version == 1
    assert await tasks.update(actor(), update) == first
    await snapshots.prepare(
        actor(), content(requirements=["Use Python"], task_state_version=1)
    )
    await events.record(
        actor(),
        event(
            2,
            project_id="p1",
            kind="correction",
            text="Use Rust instead; cancel obsolete.",
        ),
    )
    newer = update.model_copy(
        update={
            "expected_version": 1,
            "idempotency_key": "task-B",
            "source_event_id": "e2",
            "requirements": ("Use Rust",),
            "must_keep": ("Use Rust",),
            "pending": ("audit",),
            "cancelled": ("obsolete",),
        }
    )
    second = await tasks.update(actor(), newer)
    assert second.version == 2
    claim = await events.claim(actor().tenant_id)
    assert claim is not None
    assert await events.finish(*claim, success=True)
    with pytest.raises(EventConflict):
        await tasks.update(
            actor(), newer.model_copy(update={"idempotency_key": "conflict"})
        )
    assembler = ContextAssembler(
        Source(), required_sources=(TaskCandidateSource(tasks),)
    )
    query = request(project_id="p1", task_id="task1")
    bundle = await assembler.assemble(actor(), query)
    assert "Use Rust" in bundle.rendered and "Use Python" not in bundle.rendered
    assert '"cancelled":["obsolete"]' in bundle.rendered.replace('\\"', '"')
    with pytest.raises(MandatoryContextTooLarge):
        await assembler.assemble(actor(), request(10, project_id="p1", task_id="task1"))
    resumed = await snapshots.resume(
        actor(),
        "h1",
        expected_version=1,
        request=query,
        assembler=assembler,
        current_task=tasks.snapshot,
    )
    assert not resumed.safe_to_continue
    assert "stale_task_state" in resumed.warnings and resumed.current_task
    assert (
        resumed.current_task.version == 2
        and "Use Python" not in resumed.bundle.rendered
    )
    with pytest.raises(PermissionError):
        await tasks.current(principal(), "p1", "task1")
    with pytest.raises(LookupError):
        await tasks.current(
            actor().model_copy(update={"user_id": "foreign"}), "p1", "task1"
        )
    item_id = bundle.items[0].item_id
    await snapshots.privacy.block(actor(), item_id)
    with pytest.raises(RuntimeError, match="required context source"):
        await assembler.assemble(actor(), query)
    assert not (await tasks.evidence(actor(), item_id))[0]["usable_as_current_context"]
    with pytest.raises(PermissionError, match="revoked task"):
        await tasks.update(
            principal(actor_kind="agent", projects=["p1"]),
            newer.model_copy(update={"expected_version": 2, "idempotency_key": "revive"}),
        )


def task_update(**changes: object) -> TaskUpdate:
    return TaskUpdate.model_validate(
        {
            **content().model_dump(include=set(WorkState.model_fields)),
            "source_event_id": "e1",
            "expected_version": 0,
            "idempotency_key": "initial",
            **changes,
        }
    )


async def test_agents_can_report_proven_progress_but_cannot_approve_requirements(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    snapshots, events, _ = handoffs
    tasks = TaskStateService(snapshots, events)
    host = principal(actor_kind="agent", projects=["p1"])
    with pytest.raises(PermissionError):
        await tasks.update(host, task_update())
    await events.record(actor(), event(project_id="p1"))
    first = await tasks.update(actor(), task_update())
    assert not first.source_available
    with pytest.raises(RuntimeError, match="required context source"):
        await ContextAssembler(
            Source(), required_sources=(TaskCandidateSource(tasks),)
        ).assemble(actor(), request(project_id="p1", task_id="task1"))
    await events.record(
        host,
        event(
            2,
            project_id="p1",
            kind="tool_result",
            text="Action X succeeded.",
            tool_call_id="X",
            tool_succeeded=True,
        ),
    )
    action = CompletedAction(
        action_id="X",
        project_id="p1",
        description="Action X",
        source_session_id="s1",
        result_event_id="e2",
    )
    progress = task_update(
        expected_version=1,
        idempotency_key="progress",
        source_event_id="e2",
        completed=[action],
    )
    second = await tasks.update(host, progress)
    assert second.version == 2 and second.content.completed == (action,)
    assert (await tasks.update(actor(), task_update())).version == 1
    assert (await tasks.current(actor(), "p1", "task1")).version == 2
    with pytest.raises(PermissionError):
        await tasks.update(
            host,
            progress.model_copy(
                update={
                    "expected_version": 2,
                    "idempotency_key": "forged",
                    "requirements": ("New policy",),
                }
            ),
        )
    with pytest.raises(EventConflict, match="cannot be removed"):
        await tasks.update(
            actor(), task_update(expected_version=2, idempotency_key="erase-completion")
        )
    forged = action.model_copy(update={"action_id": "unproven"})
    with pytest.raises(ValueError, match="successful tool outcome"):
        await tasks.update(
            host,
            progress.model_copy(
                update={
                    "expected_version": 2,
                    "idempotency_key": "fake",
                    "completed": (action, forged),
                }
            ),
        )
    with pytest.raises(PermissionError, match="owned by the task service"):
        await snapshots.prepare(
            actor(), content(handoff_id=tasks.identifier(actor(), "p1", "task1"))
        )


async def test_task_cas_retry_and_changed_source_fail_closed(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    snapshots, events, _ = handoffs
    tasks = TaskStateService(snapshots, events)
    await events.record(actor(), event(project_id="p1"))
    await tasks.update(actor(), task_update())
    proposals = [
        task_update(
            expected_version=1, idempotency_key=f"race-{i}", pending=[f"next-{i}"]
        )
        for i in range(2)
    ]
    results = await asyncio.gather(
        *(tasks.update(actor(), update) for update in proposals), return_exceptions=True
    )
    assert sum(isinstance(result, EventConflict) for result in results) == 1
    assert (await tasks.current(actor(), "p1", "task1")).version == 2
    with pytest.raises(ValueError, match="source event"):
        await tasks.update(
            actor(),
            task_update(
                expected_version=2, idempotency_key="missing", source_event_id="missing"
            ),
        )
    with pytest.raises(PermissionError):
        await tasks.update(
            principal(projects=["p1"]),
            task_update(
                expected_version=2,
                idempotency_key="no-correct",
                requirements=["Changed"],
            ),
        )


async def test_changed_artifact_is_visible_in_current_state_and_blocks_resume(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    snapshots, events, artifacts = handoffs
    tasks = TaskStateService(snapshots, events)
    await events.record(actor(), event(project_id="p1"))
    claim = await events.claim(actor().tenant_id)
    assert claim is not None and await events.finish(*claim, success=True)
    artifacts["report"] = "a" * 64
    reference = ArtifactRef(artifact_id="report", project_id="p1", sha256="a" * 64)
    update = task_update(artifacts=[reference])
    state = await tasks.update(actor(), update)
    await snapshots.prepare(
        actor(),
        content(
            **state.content.model_dump(
                exclude={"project_id", "task_id", "source_session_id", "goal"}
            ),
            task_state_version=1,
        ),
        current_task=tasks.snapshot,
    )
    assembler = ContextAssembler(
        Source(), required_sources=(TaskCandidateSource(tasks),)
    )
    query = request(project_id="p1", task_id="task1")
    before = await assembler.assemble(actor(), query)
    artifacts["report"] = "b" * 64
    after = await assembler.assemble(actor(), query)
    assert before.items[0].text == after.items[0].text
    assert "artifact_version_changed" in after.warnings
    resumed = await snapshots.resume(
        actor(),
        "h1",
        expected_version=1,
        request=query,
        assembler=assembler,
        current_task=tasks.snapshot,
    )
    assert (
        not resumed.safe_to_continue and "artifact_version_changed" in resumed.warnings
    )


async def test_additive_work_fields_preserve_existing_handoff_idempotency_hashes(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> None:
    snapshots, _, _ = handoffs
    original = content()
    new_fields = {
        "status",
        "cancelled",
        "dependencies",
        "source_event_id",
        "must_keep",
        "task_state_version",
    }
    old_payload = original.model_dump(mode="json", exclude=new_fields)
    old_digest = hashlib.sha256(
        json.dumps(old_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    artifact = HandoffArtifact(version=1, content=original).model_dump(mode="json")
    artifact["content"] = old_payload
    await snapshots.collection.insert_one(
        {
            "tenant_id": actor().tenant_id,
            "user_id": actor().user_id,
            "handoff_id": "h1",
            "project_id": "p1",
            "task_id": "task1",
            "version": 1,
            "revisions": [
                {"idempotency_key": "k1", "digest": old_digest, "artifact": artifact}
            ],
        }
    )
    replay = await snapshots.prepare(actor(), original)
    assert replay.version == 1 and replay.content == original
