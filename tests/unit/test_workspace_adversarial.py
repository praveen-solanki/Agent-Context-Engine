"""Adversarial routing metadata and durable history boundary regressions."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock
from typing import Any, cast

import pytest

from agent_context.contracts import Stream
from agent_context.events import EventConflict, append_event
from agent_context.privacy import PrivacyControls, PrivacyState
from agent_context.project_store import DirectoryState, ProjectStore
from agent_context.task_state import TaskStateService
from agent_context.contracts import PROJECT_TASK_ID
from tests.unit.test_event_contracts import event, principal
from ui.workspace import restore


def stream_with(events: list[tuple[int, str, str | None]]) -> Stream:
    stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1")
    for sequence, kind, cause in events:
        actor = principal(
            projects=["p1"], actor_kind="agent" if kind != "user_message" else "user"
        )
        stream = append_event(
            stream,
            actor,
            event(
                sequence,
                project_id="p1",
                kind=kind,
                causation_id=cause,
                correlation_id=f"turn{sequence}",
                text=f"message {sequence}",
            ),
            max_events=16,
        )
    return stream


@pytest.mark.parametrize("cause", ["missing", "e2"])
def test_history_does_not_attach_an_unknown_or_non_user_cause_to_last_user(
    cause: str,
) -> None:
    stream = stream_with(
        [
            (1, "user_message", None),
            (2, "tool_result", "e1"),
            (3, "assistant_message", cause),
        ]
    )
    history, pending = restore(stream)
    assert history == ()
    assert pending is not None and pending.turn_id == "turn1"


def test_history_does_not_let_an_answer_complete_a_future_user_event() -> None:
    stream = stream_with([(1, "assistant_message", "e2"), (2, "user_message", None)])
    history, pending = restore(stream)
    assert history == ()
    assert pending is not None and pending.turn_id == "turn2"


def test_legacy_history_without_causation_still_uses_the_preceding_user() -> None:
    history, pending = restore(
        stream_with([(1, "user_message", None), (2, "assistant_message", None)])
    )
    assert len(history) == 1 and history[0].message == "message 1"
    assert pending is None


def test_explicit_history_reference_keeps_other_user_turn_pending() -> None:
    history, pending = restore(
        stream_with(
            [
                (1, "user_message", None),
                (2, "user_message", None),
                (3, "assistant_message", "e1"),
            ]
        )
    )
    assert len(history) == 1 and history[0].message == "message 1"
    assert pending is not None and pending.turn_id == "turn2"


async def test_project_goal_hint_is_not_returned_after_concurrent_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actor = principal(projects=["p1"])
    handoff = TaskStateService.identifier(actor, "p1", PROJECT_TASK_ID)
    before = PrivacyState(tenant_id="t1", user_id="u1")
    after = before.model_copy(
        update={"revision": 1, "blocked_item_ids": (handoff + ":1",)}
    )
    privacy = MagicMock(spec=PrivacyControls)
    privacy.require_active = AsyncMock(side_effect=[before, after])
    store = object.__new__(ProjectStore)
    store.privacy = cast(PrivacyControls, privacy)
    store.collection = cast(Any, MagicMock())
    monkeypatch.setattr(store, "state", AsyncMock(return_value=DirectoryState()))

    async def hints() -> AsyncIterator[dict[str, object]]:
        yield {
            "handoff_id": handoff,
            "version": 1,
            "goal": "Private goal",
            "status": "active",
        }

    store.collection.database["ace_handoffs_v1"].aggregate = AsyncMock(
        return_value=hints()
    )
    with pytest.raises(EventConflict, match="privacy"):
        await store.directory(actor)


@pytest.mark.parametrize("change", ["target", "kind", "event_kind"])
async def test_turn_retry_cannot_replay_a_different_correction(change: str) -> None:
    from agent_context.client import AgentContextClient
    from agent_context.continuity import WorkspaceAssistant
    from agent_context.contracts import RevocationInput
    from agent_context.demo import ResearchAssistant
    from tests.fakes import FakeLLMProvider

    original = RevocationInput(item_id="memory-a", expected_fingerprint="fingerprint-a")
    identifier = ResearchAssistant.event_identifier("s1", "turn")
    stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1")
    actor = principal(projects=["p1"], permissions=["view", "assert", "correct"])
    recorded_kind = "assistant_message" if change == "event_kind" else "correction"
    if change == "event_kind":
        actor = principal(projects=["p1"], actor_kind="agent")
    stream = append_event(
        stream,
        actor,
        event(
            event_id=identifier,
            project_id="p1",
            kind=recorded_kind,
            text="Use the corrected value",
            correction_target=original if recorded_kind == "correction" else None,
        ),
        max_events=16,
    )
    user = MagicMock(spec=AgentContextClient)
    user.session = AsyncMock(return_value=stream)
    user.revoke = AsyncMock(
        side_effect=AssertionError("no revocation before identity validation")
    )
    user.wait_available = AsyncMock(
        side_effect=AssertionError("no processing before identity validation")
    )
    assistant = WorkspaceAssistant(
        user=cast(AgentContextClient, user),
        host=cast(AgentContextClient, MagicMock(spec=AgentContextClient)),
        llm=FakeLLMProvider(),
        project_id="p1",
        documents={},
    )
    with pytest.raises(ValueError, match="different input"):
        await assistant.turn(
            session_id="s1",
            turn_id="turn",
            message="Use the corrected value",
            correction=change != "kind",
            correction_target=original.model_copy(update={"item_id": "memory-b"})
            if change == "target"
            else original,
        )
    user.revoke.assert_not_awaited()
    user.wait_available.assert_not_awaited()


@pytest.mark.parametrize("mismatch", ["kind", "project"])
async def test_research_host_validates_recorded_turn_before_wait_or_tools(
    mismatch: str,
) -> None:
    from agent_context.client import AgentContextClient
    from agent_context.demo import DemoSettings, ResearchAssistant
    from tests.fakes import FakeLLMProvider

    stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1")
    stream = append_event(
        stream,
        principal(projects=["p1"]),
        event(
            event_id=ResearchAssistant.event_identifier("s1", "turn"),
            project_id="p1",
            text="Keep this statement",
        ),
        max_events=16,
    )
    user = MagicMock(spec=AgentContextClient)
    user.session = AsyncMock(return_value=stream)
    user.wait_available = AsyncMock(
        side_effect=AssertionError("no wait before scope and retry checks")
    )
    assistant = ResearchAssistant(
        user_client=cast(AgentContextClient, user),
        host_client=cast(AgentContextClient, MagicMock(spec=AgentContextClient)),
        llm=FakeLLMProvider(),
        documents={},
        settings=DemoSettings(
            project_id="p2" if mismatch == "project" else "p1", require_sources=False
        ),
    )
    with pytest.raises(
        PermissionError if mismatch == "project" else ValueError,
        match="another project" if mismatch == "project" else "different input",
    ):
        await assistant.turn(
            session_id="s1",
            turn_id="turn",
            message="Keep this statement",
            correction=mismatch == "kind",
        )
    user.wait_available.assert_not_awaited()
