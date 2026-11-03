"""Trust, sequencing and bounded-payload tests for the authenticated event boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agent_context.bridge import scoped_id, to_session
from agent_context.contracts import EventInput, EventKind, Permission, Principal, Stream
from agent_context.events import CapacityExceeded, EventConflict, append_event


def principal(**changes: object) -> Principal:
    return Principal.model_validate(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "actor_id": "a1" if changes.get("actor_kind") == "agent" else "u1",
            **changes,
        }
    )


def event(sequence: int = 1, /, **changes: object) -> EventInput:
    return EventInput.model_validate(
        {
            "event_id": f"e{sequence}",
            "session_id": "s1",
            "agent_id": "a1",
            "sequence": sequence,
            "event_time": datetime(2026, 1, 1, tzinfo=UTC)
            + timedelta(seconds=sequence),
            "kind": "user_message",
            "text": "Always keep answers concise.",
            **changes,
        }
    )


def empty() -> Stream:
    return Stream(tenant_id="t1", user_id="u1", session_id="s1")


def test_duplicate_exact_delivery_is_idempotent_but_mutation_is_rejected() -> None:
    stream = append_event(empty(), principal(), event(), max_events=8)
    assert append_event(stream, principal(), event(), max_events=8) is stream
    with pytest.raises(EventConflict):
        append_event(stream, principal(), event(text="changed"), max_events=8)


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "other"},
        {"user_id": "other"},
        {"permissions": []},
        {"actor_kind": "agent"},
    ],
)
def test_forged_authority_and_missing_grants_are_rejected(
    changes: dict[str, object],
) -> None:
    with pytest.raises(PermissionError):
        append_event(empty(), principal(**changes), event(), max_events=8)


@pytest.mark.parametrize(
    "changes",
    [{"tenant_id": "forged"}, {"user_id": "forged"}, {"source_trust": "trusted"}],
)
def test_input_cannot_supply_trusted_identity(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        event(**changes)


def test_project_requires_an_independent_trusted_grant() -> None:
    stream = empty().model_copy(update={"project_id": "p1"})
    with pytest.raises(PermissionError):
        append_event(stream, principal(), event(project_id="p1"), max_events=8)
    assert append_event(
        stream, principal(projects=["p1"]), event(project_id="p1"), max_events=8
    )


def test_correction_requires_distinct_permission_and_user_authority() -> None:
    with pytest.raises(PermissionError):
        append_event(
            empty(), principal(), event(kind=EventKind.CORRECTION), max_events=8
        )
    authorized = principal(permissions=[Permission.CORRECT])
    assert append_event(
        empty(), authorized, event(kind=EventKind.CORRECTION), max_events=8
    )


def test_sequence_time_closure_and_backpressure_are_enforced() -> None:
    with pytest.raises(EventConflict):
        append_event(empty(), principal(), event(2), max_events=8)
    stream = append_event(empty(), principal(), event(), max_events=8)
    with pytest.raises(EventConflict):
        append_event(
            stream,
            principal(),
            event(2, event_time=datetime(2020, 1, 1, tzinfo=UTC)),
            max_events=8,
        )
    with pytest.raises(CapacityExceeded):
        append_event(stream, principal(), event(2), max_events=1)
    closed = append_event(
        stream, principal(), event(2, kind="session_close", text=""), max_events=8
    )
    with pytest.raises(EventConflict):
        append_event(closed, principal(), event(3), max_events=8)


@pytest.mark.parametrize(
    "text",
    [
        "Bearer super-secret-value",
        "api_key=super-secret-value",
        "password:super-secret-value",
    ],
)
def test_tool_payloads_must_be_sanitized(text: str) -> None:
    with pytest.raises(ValueError, match="sanitized"):
        append_event(
            empty(),
            principal(actor_kind="agent"),
            event(kind="tool_result", text=text),
            max_events=8,
        )


def test_utf8_bound_and_aware_timestamps() -> None:
    with pytest.raises(ValidationError):
        event(text="😀" * 5000)
    with pytest.raises(ValidationError):
        event(event_time=datetime(2026, 1, 1))


def test_bridge_keeps_exact_text_and_user_provenance_with_collision_safe_ids() -> None:
    stream = append_event(empty(), principal(), event(), max_events=8)
    session = to_session(stream)
    assert session.messages[0].text == event().text
    assert session.messages[0].sender_id == session.user_id
    assert session.messages[0].metadata["event_id"] == "e1"
    assert scoped_id("a", "bc") != scoped_id("ab", "c")
    assert scoped_id("t1", "u1") != scoped_id("t2", "u1")
