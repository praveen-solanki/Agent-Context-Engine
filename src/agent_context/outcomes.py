"""Only authenticated host tool outcomes can substantiate handoff completion."""

from __future__ import annotations

from agent_context.contracts import EventKind, Principal
from agent_context.event_store import MongoEventStore
from agent_context.handoff import CompletedAction


class EventOutcomeVerifier:
    def __init__(self, store: MongoEventStore) -> None:
        self.store = store

    async def __call__(self, principal: Principal, action: CompletedAction) -> bool:
        try:
            stream = await self.store.get(principal, action.source_session_id)
        except (LookupError, PermissionError):
            return False
        if stream.project_id != action.project_id:
            return False
        return any(
            recorded.event.event_id == action.result_event_id
            and recorded.actor_kind == "agent"
            and recorded.event.kind == EventKind.TOOL_RESULT
            and recorded.event.tool_call_id == action.action_id
            and recorded.event.tool_succeeded is True
            for recorded in stream.events
        )
