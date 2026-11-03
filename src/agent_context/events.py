"""Deterministic authorization and append-only event semantics."""

from __future__ import annotations

import re

from agent_context.contracts import (
    EventInput,
    EventKind,
    Permission,
    Principal,
    ProcessingState,
    RecordedEvent,
    Stream,
)


class EventConflict(ValueError):
    """Idempotency, sequence or immutable identity precondition failed."""


class CapacityExceeded(ValueError):
    """Caller must start another bounded session."""


def append_event(
    stream: Stream, principal: Principal, event: EventInput, *, max_events: int
) -> Stream:
    """Pure append policy shared by the real store and test doubles."""
    permission = (
        Permission.CORRECT
        if event.kind in (EventKind.CORRECTION, EventKind.REVOCATION)
        else Permission.ASSERT
    )
    principal.require(permission, event.project_id)
    if (stream.tenant_id, stream.user_id) != (principal.tenant_id, principal.user_id):
        raise PermissionError("session is not accessible")
    if (stream.session_id, stream.project_id) != (event.session_id, event.project_id):
        raise EventConflict("session identity cannot change")
    if (
        stream.events
        and event.derive_context is not None
        and event.derive_context != stream.derive_context
    ):
        raise EventConflict("derivation consent is immutable within a session")
    if principal.actor_kind == "agent" and event.kind in (
        EventKind.USER_MESSAGE,
        EventKind.CORRECTION,
        EventKind.REVOCATION,
    ):
        raise PermissionError("agent cannot claim user authority")
    if principal.actor_kind == "user" and event.kind in (
        EventKind.ASSISTANT_MESSAGE,
        EventKind.TOOL_RESULT,
    ):
        raise PermissionError("user cannot attest agent or tool outcomes")
    if principal.actor_kind == "agent" and event.agent_id != principal.actor_id:
        raise PermissionError("agent cannot claim another agent's identity")
    for old in stream.events:
        if old.event.event_id == event.event_id:
            if old.event != event or old.actor_id != principal.actor_id:
                raise EventConflict("event ID was already used with different content")
            return stream
    if len(stream.events) >= max_events:
        raise CapacityExceeded("session event limit reached")
    if stream.events and stream.events[-1].event.kind == EventKind.SESSION_CLOSE:
        raise EventConflict("closed session cannot accept new events")
    if event.sequence != len(stream.events) + 1:
        raise EventConflict("events must arrive in contiguous sequence starting at 1")
    if stream.events and event.event_time < stream.events[-1].event.event_time:
        raise EventConflict("late events require an explicit historical import")
    # Reject likely raw credentials rather than persisting a secret and then
    # claiming it was sanitized. Callers send a redacted result or artifact ref.
    if event.kind == EventKind.TOOL_RESULT and re.search(
        r"(?i)(?:bearer\s+\S+|(?:api[_-]?key|password|secret|token)\s*[=:]\s*\S+)",
        event.text,
    ):
        raise ValueError("tool results must be sanitized before submission")
    state = (
        stream.state
        if stream.state in (ProcessingState.PROCESSING, ProcessingState.DEAD)
        else ProcessingState.RECORDED
    )
    return stream.model_copy(
        update={
            "events": (
                *stream.events,
                RecordedEvent(
                    event=event,
                    actor_id=principal.actor_id,
                    actor_kind=principal.actor_kind,
                ),
            ),
            "state": state,
            "derive_context": stream.derive_context
            if stream.events
            else (event.derive_context if event.derive_context is not None else True),
        }
    )
