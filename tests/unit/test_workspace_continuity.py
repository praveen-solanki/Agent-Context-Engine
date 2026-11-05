"""Source-validated conversation deltas and durable workspace reconstruction."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from agent_context.continuity import ReferencedChange, TaskIntent, apply_intent
from agent_context.contracts import (
    EventKind,
    Permission,
    RevocationInput,
    Stream,
    TaskReference,
)
from agent_context.events import append_event
from agent_context.handoff import CompletedAction, WorkState
from tests.unit.test_event_contracts import event, principal
from ui.workspace import PendingTurn, restore, send


def work(**changes: object) -> WorkState:
    return WorkState.model_validate(
        {
            "project_id": "p1",
            "task_id": "project-work",
            "source_session_id": "s1",
            "source_event_id": "e1",
            "goal": "Build the archive",
            "requirements": ["Keep source references"],
            "pending": ["Read the paper", "Write the report"],
            "blockers": ["Waiting for permission"],
            "dependencies": ["Get permission before publishing"],
            **changes,
        }
    )


@pytest.mark.parametrize(
    "message", ["What do you remember?", "My favourite fruit is pear.", "Hola"]
)
def test_questions_and_preferences_do_not_invent_tasks(message: str) -> None:
    assert (
        apply_intent(None, TaskIntent(), event(text=message, project_id="p1")) is None
    )


@pytest.mark.parametrize(
    "goal", ["Build the archive", "Préparer la recherche", "تحليل التقرير"]
)
def test_task_creation_requires_exact_user_spans(goal: str) -> None:
    result = apply_intent(
        None,
        TaskIntent(goal_quote=goal, add_steps=("Read the paper",)),
        event(text=goal + "; Read the paper", project_id="p1"),
    )
    assert result and result.goal == goal and result.pending == ("Read the paper",)
    with pytest.raises(ValueError, match="absent"):
        apply_intent(
            None,
            TaskIntent(goal_quote="A model invented this"),
            event(text=goal, project_id="p1"),
        )


def test_report_cancellation_and_resolution_preserve_verified_receipts_and_constraints() -> (
    None
):
    receipt = CompletedAction(
        action_id="read1",
        project_id="p1",
        description="Read actual document",
        source_session_id="s1",
        result_event_id="receipt1",
    )
    original = work(completed=[receipt])
    text = "I read the paper. Cancel the report. Permission arrived."
    intent = TaskIntent(
        report_completed=(
            ReferencedChange(target="Read the paper", quote="I read the paper."),
        ),
        cancel_steps=(
            ReferencedChange(target="Write the report", quote="Cancel the report."),
        ),
        resolve_blockers=(
            ReferencedChange(
                target="Waiting for permission", quote="Permission arrived."
            ),
        ),
    )
    result = apply_intent(original, intent, event(2, text=text, project_id="p1"))
    assert result and not result.pending and not result.blockers
    assert result.completed == (receipt,)
    assert (
        result.requirements == original.requirements
        and result.dependencies == original.dependencies
    )
    assert result.cancelled == ("Write the report",)
    assert result.reported_completed[0].quote == "I read the paper."
    assert result.reported_completed[0].source_event_id == "e2"
    assert original.pending == ("Read the paper", "Write the report")


def test_ambiguous_or_invalid_change_never_mutates_state() -> None:
    state = work()
    assert (
        apply_intent(
            state,
            TaskIntent(clarification="Which step?", add_steps=("invented",)),
            event(text="Yes"),
        )
        == state
    )
    with pytest.raises(ValueError, match="missing current entry"):
        apply_intent(
            state,
            TaskIntent(
                report_completed=(
                    ReferencedChange(target="Imaginary step", quote="Done"),
                )
            ),
            event(text="Done"),
        )
    with pytest.raises(ValueError, match="both cancelled"):
        apply_intent(
            state,
            TaskIntent(
                report_completed=(
                    ReferencedChange(target="Read the paper", quote="Done"),
                ),
                cancel_steps=(ReferencedChange(target="Read the paper", quote="Done"),),
            ),
            event(text="Done"),
        )


def test_durable_history_preserves_sources_suggestions_and_pending_correction() -> None:
    actor = principal(projects=["p1"], permissions=frozenset(Permission))
    host = principal(projects=["p1"], actor_kind="agent")
    stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1")
    stream = append_event(
        stream,
        actor,
        event(project_id="p1", text="Plan the archive", correlation_id="turn1"),
        max_events=32,
    )
    stream = append_event(
        stream,
        host,
        event(
            2,
            project_id="p1",
            kind="assistant_message",
            text="Here is the plan.",
            causation_id="e1",
            citations=["memory:m1"],
            suggested_next_steps=["Review citations"],
            task_context=TaskReference(task_id="project-work", version=3),
        ),
        max_events=32,
    )
    target = RevocationInput(item_id="m1", expected_fingerprint="f1")
    stream = append_event(
        stream,
        actor,
        event(
            3,
            project_id="p1",
            kind="correction",
            text="Use new citations",
            correlation_id="turn2",
            correction_target=target,
        ),
        max_events=32,
    )
    history, pending = restore(stream)
    assert len(history) == 1 and history[0].recorded
    assert history[0].result.answer == "Here is the plan."
    assert not history[
        0
    ].result.bundle.items  # No fabricated historical context selection.
    assert history[0].result.citations == ("memory:m1",)
    assert history[0].result.suggested_next_steps == ("Review citations",)
    assert (
        history[0].result.task_context and history[0].result.task_context.version == 3
    )
    assert pending and pending.sequence == 3 and pending.turn_id == "turn2"
    assert pending.correction_target == target and pending.project_id == "p1"


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": EventKind.USER_MESSAGE, "suggested_next_steps": ["Forged suggestion"]},
        {
            "kind": EventKind.USER_MESSAGE,
            "task_context": {"task_id": "t1", "version": 1},
        },
        {
            "kind": EventKind.USER_MESSAGE,
            "correction_target": {"item_id": "m1", "expected_fingerprint": "f1"},
        },
    ],
)
def test_annotation_contracts_reject_wrong_event_kind(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        event(**changes)


async def test_pending_turn_cannot_move_between_projects_or_conversations() -> None:
    from agent_context.assembly import SearchResult
    from agent_context.navigation import ProjectDirectory, SessionPage
    from ui.workspace import WorkspaceSnapshot

    current = WorkspaceSnapshot(
        ProjectDirectory(projects=(), permissions=frozenset()),
        "p1",
        "s1",
        SessionPage(sessions=()),
        None,
        (),
        SearchResult(
            items=(), snapshot_id="test", candidate_window=20, window_full=False
        ),
        None,
    )
    pending = PendingTurn(
        project_id="foreign",
        session_id=current.session_id,
        turn_id="t1",
        message="Hi",
        sequence=1,
    )
    with pytest.raises(PermissionError, match="another conversation"):
        await send(current, pending, {})
    with pytest.raises(PermissionError):
        await send(
            replace(current, session_id="another"),
            pending.model_copy(update={"project_id": current.project_id}),
            {},
        )


def test_unplanned_progress_and_dependency_resolution_require_real_quotes() -> None:
    current = work()
    updated = apply_intent(
        current,
        TaskIntent(
            add_reported_progress=("I created an index",),
            resolve_dependencies=(
                ReferencedChange(
                    target="Get permission before publishing",
                    quote="Publishing was approved",
                ),
            ),
        ),
        event(2, project_id="p1", text="I created an index. Publishing was approved."),
    )
    assert updated and updated.reported_completed[0].description == "I created an index"
    assert (
        not updated.dependencies
        and updated.pending == current.pending
        and not updated.completed
    )
    with pytest.raises(ValueError, match="absent"):
        apply_intent(
            current,
            TaskIntent(add_reported_progress=("Model invention",)),
            event(text="Nothing completed"),
        )


def test_echoing_an_approved_goal_does_not_require_reassertion_or_block_a_new_constraint() -> (
    None
):
    current = work()
    message = "The venue only permits deliveries before noon."
    intent = TaskIntent(goal_quote=current.goal, add_requirements=(message,))
    updated = apply_intent(current, intent, event(2, project_id="p1", text=message))
    assert updated and updated.goal == current.goal
    assert updated.requirements == (*current.requirements, message)
    assert (
        apply_intent(
            current,
            TaskIntent(goal_quote=current.goal),
            event(text="What is the plan?"),
        )
        == current
    )
    with pytest.raises(ValueError, match="goal_quote.*absent"):
        apply_intent(
            current,
            TaskIntent(goal_quote="A different unapproved goal"),
            event(text=message),
        )
