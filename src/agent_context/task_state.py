"""Current work state, reusing the existing atomic versioned snapshot store.

The reserved snapshot ID gives each authenticated project/task exactly one head.
No second event log, memory writer, workflow executor or collection is created.
"""

from __future__ import annotations

import hashlib
import json
import asyncio

from pydantic import AwareDatetime, Field, model_validator
from typing_extensions import Self

from agent_context.assembly import (
    ContextItem,
    ContextQuery,
    SearchRequest,
    ContextWarning,
)
from agent_context.bridge import scoped_id
from agent_context.contracts import (
    Contract,
    Permission,
    Principal,
    EventKind,
    Identifier,
    utcnow,
)
from agent_context.event_store import MongoEventStore
from agent_context.events import EventConflict
from agent_context.handoff import (
    HandoffArtifact,
    HandoffInput,
    HandoffService,
    TASK_STATE_PREFIX,
    WorkState,
)
from context_graph.domain.enums import ScopeType


class TaskUpdate(WorkState):
    source_event_id: Identifier | None = Field(...)
    expected_version: int = Field(ge=0)
    idempotency_key: Identifier

    @model_validator(mode="after")
    def bounded_entries(self) -> Self:
        if self.source_event_id is None:
            raise ValueError("task updates require a source event ID")
        for values in (
            self.requirements,
            self.pending,
            self.blockers,
            self.cancelled,
            self.dependencies,
        ):
            if len(set(values)) != len(values) or any(
                not value.strip() or len(value.encode()) > 4000 for value in values
            ):
                raise ValueError("work entries must be distinct, nonempty and bounded")
        action_ids = [action.action_id for action in self.completed]
        if len(set(action_ids)) != len(action_ids):
            raise ValueError("completed action IDs must be distinct")
        return self


class TaskState(Contract):
    version: int
    updated_at: AwareDatetime
    content: WorkState
    source_available: bool
    warnings: tuple[ContextWarning, ...] = ()


class TaskStateService:
    def __init__(self, snapshots: HandoffService, events: MongoEventStore) -> None:
        self.snapshots, self.events = snapshots, events

    @staticmethod
    def identifier(principal: Principal, project_id: str, task_id: str) -> str:
        identity = json.dumps(
            [principal.user_id, project_id, task_id], separators=(",", ":")
        )
        return TASK_STATE_PREFIX + scoped_id(principal.tenant_id, identity)

    async def snapshot(
        self,
        principal: Principal,
        project_id: str,
        task_id: str,
    ) -> HandoffArtifact | None:
        principal.require(Permission.VIEW, project_id)
        identifier = self.identifier(principal, project_id, task_id)
        try:
            return await self.snapshots.latest(principal, identifier)
        except LookupError:
            return None

    async def _state(
        self, principal: Principal, snapshot: HandoffArtifact
    ) -> TaskState:
        content = WorkState.model_validate(
            snapshot.content.model_dump(include=set(WorkState.model_fields))
        )
        stream = await self.events.get(principal, content.source_session_id)
        if stream.project_id != content.project_id:
            raise PermissionError("task source project does not match")
        source = next(
            (
                record
                for record in stream.events
                if record.event.event_id == content.source_event_id
            ),
            None,
        )
        if source is None:
            raise LookupError("task source event no longer exists")
        actions = await asyncio.gather(
            *(
                self.snapshots.verify_action(principal, action)
                for action in content.completed
            )
        )
        artifacts = await asyncio.gather(
            *(
                self.snapshots.verify_artifact(principal, artifact)
                for artifact in content.artifacts
            )
        )
        warnings: list[ContextWarning] = []
        if not all(actions):
            warnings.append("completed_action_no_longer_verifiable")
        if not all(artifacts):
            warnings.append("artifact_version_changed")
        await self.snapshots.privacy.require_active(
            principal.tenant_id, principal.user_id
        )
        return TaskState(
            version=snapshot.version,
            updated_at=snapshot.created_at,
            content=content,
            source_available=stream.available_sequence >= source.event.sequence,
            warnings=tuple(warnings),
        )

    async def current(
        self, principal: Principal, project_id: str, task_id: str
    ) -> TaskState:
        snapshot = await self.snapshot(principal, project_id, task_id)
        if snapshot is None:
            raise LookupError("task not found")
        return await self._state(principal, snapshot)

    async def update(self, principal: Principal, request: TaskUpdate) -> TaskState:
        principal.require(Permission.ASSERT, request.project_id)
        # A direct authenticated user update approves requirements. An agent
        # may report progress, but cannot modify the user's accepted objective,
        # constraints, cancellation or dependency decisions.
        existing = await self.snapshot(principal, request.project_id, request.task_id)
        prepared = HandoffInput(
            **request.model_dump(),
            handoff_id=self.identifier(principal, request.project_id, request.task_id),
        )
        if existing is not None and request.expected_version < existing.version:
            # Let the store distinguish an exact old replay from a stale new
            # mutation before comparing it with newer completed actions.
            replay = await self.snapshots.prepare(
                principal, prepared, internal_task=True
            )
            return await self._state(principal, replay)
        privacy = await self.snapshots.privacy.require_active(
            principal.tenant_id, principal.user_id
        )
        if (
            existing is not None
            and f"{prepared.handoff_id}:{existing.version}" in privacy.blocked_item_ids
        ):
            if principal.actor_kind != "user":
                raise PermissionError(
                    "revoked task context requires user reconciliation"
                )
            principal.require(Permission.CORRECT, request.project_id)
        if existing is None and principal.actor_kind == "agent":
            raise PermissionError("an agent cannot approve a new task")
        if existing is not None:
            protected = {
                "goal",
                "requirements",
                "must_keep",
                "cancelled",
                "dependencies",
                "status",
                "expires_at",
                "reported_completed",
            }
            if request.model_dump(include=protected) != existing.content.model_dump(
                include=protected
            ):
                if principal.actor_kind == "agent":
                    raise PermissionError(
                        "agent cannot change approved task requirements"
                    )
                principal.require(Permission.CORRECT, request.project_id)
        if request.source_event_id is None:
            raise ValueError("task updates require a real source event")
        stream = await self.events.get(principal, request.source_session_id)
        if stream.project_id != request.project_id:
            raise PermissionError("task event belongs to another project")
        source = next(
            (
                record
                for record in stream.events
                if record.event.event_id == request.source_event_id
            ),
            None,
        )
        if source is None:
            raise ValueError("task source event not found")
        if (
            source.actor_kind != principal.actor_kind
            or source.actor_id != principal.actor_id
        ):
            raise PermissionError(
                "task update must cite the caller's authenticated event"
            )
        if principal.actor_kind == "user" and source.event.kind not in (
            EventKind.USER_MESSAGE,
            EventKind.CORRECTION,
        ):
            raise PermissionError("requirements need an authenticated user assertion")
        if (
            principal.actor_kind == "agent"
            and source.event.kind != EventKind.TOOL_RESULT
        ):
            raise PermissionError("agent progress requires a tool outcome")
        if existing is not None:
            completed = {action.action_id: action for action in request.completed}
            if any(
                completed.get(action.action_id) != action
                for action in existing.content.completed
            ):
                raise EventConflict(
                    "verified completed actions cannot be removed or rewritten"
                )
        previous_reports = (
            set(existing.content.reported_completed) if existing else set()
        )
        for report in request.reported_completed:
            if report not in previous_reports and (
                principal.actor_kind != "user"
                or report.source_session_id != request.source_session_id
                or report.source_event_id != request.source_event_id
                or report.quote not in source.event.text
            ):
                raise PermissionError(
                    "reported progress requires the user's exact source quote"
                )
        snapshot = await self.snapshots.prepare(
            principal,
            prepared,
            internal_task=True,
        )
        return await self._state(principal, snapshot)

    async def evidence(
        self, principal: Principal, item_id: str
    ) -> list[dict[str, object]]:
        identifier, separator, version = item_id.rpartition(":")
        if (
            not separator
            or not version.isdigit()
            or not identifier.startswith(TASK_STATE_PREFIX)
        ):
            raise LookupError("task evidence not found")
        snapshot = await self.snapshots.latest(principal, identifier)
        if snapshot.version != int(version):
            raise LookupError("task context changed; refresh context")
        content = snapshot.content
        stream = await self.events.get(principal, content.source_session_id)
        source = next(
            (
                record
                for record in stream.events
                if record.event.event_id == content.source_event_id
            ),
            None,
        )
        if source is None:
            raise LookupError("task source event not found")
        privacy = await self.snapshots.privacy.require_active(
            principal.tenant_id, principal.user_id
        )
        return [
            {
                "event_id": source.event.event_id,
                "session_id": stream.session_id,
                "text": source.event.text[:4000],
                "truncated": len(source.event.text) > 4000,
                "actor_id": source.actor_id,
                "actor_kind": source.actor_kind,
                "event_kind": source.event.kind.value,
                "sequence": source.event.sequence,
                "observed_at": source.event.event_time.isoformat(),
                "source_label": "task_update_causation_event",
                "source_trust": "first_party"
                if source.actor_kind == "user"
                else "unverified",
                "state_assertion": WorkState.model_validate(
                    content.model_dump(include=set(WorkState.model_fields))
                ).model_dump(mode="json"),
                "task_version": snapshot.version,
                "usable_as_current_context": (
                    item_id not in privacy.blocked_item_ids
                    and content.status == "active"
                    and (content.expires_at is None or content.expires_at > utcnow())
                ),
            }
        ]


class TaskCandidateSource:
    def __init__(self, tasks: TaskStateService) -> None:
        self.tasks = tasks

    async def fetch(
        self,
        principal: Principal,
        request: ContextQuery,
        *,
        limit: int,
    ) -> tuple[ContextItem, ...]:
        if not 1 <= limit <= 4096:
            raise ValueError("candidate limit is out of range")
        if request.task_id is None:
            return ()
        if request.project_id is None:
            raise PermissionError("task context requires a bound project")
        if isinstance(request, SearchRequest) and request.as_of is not None:
            # No invented historical operational state: durable memory history
            # remains searchable; task history needs an explicit revision API.
            return ()
        state = await self.tasks.current(principal, request.project_id, request.task_id)
        if request.task_version is not None and request.task_version != state.version:
            raise EventConflict("task version changed; refresh context")
        if not state.source_available and not request.include_recorded_task:
            raise RuntimeError("task source event is not context-available")
        if (
            state.content.expires_at is not None
            and state.content.expires_at <= utcnow()
        ):
            raise RuntimeError("task state expired; reconciliation required")
        # One atomic task section preserves dependencies, cancellations and
        # verified outcomes. Losing half the state is unsafe, so fail the
        # allocated budget rather than silently dropping it.
        rendered = state.model_dump_json(exclude={"source_available", "warnings"})
        identifier = self.tasks.identifier(
            principal, request.project_id, request.task_id
        )
        privacy = await self.tasks.snapshots.privacy.require_active(
            principal.tenant_id, principal.user_id
        )
        if f"{identifier}:{state.version}" in privacy.blocked_item_ids:
            raise RuntimeError("mandatory task context was revoked")
        return (
            ContextItem(
                item_id=f"{identifier}:{state.version}",
                tenant_id=principal.tenant_id,
                user_id=principal.user_id,
                scope_type=ScopeType.TASK,
                scope_id=request.task_id,
                project_id=request.project_id,
                canonical_key=f"task_state:{request.task_id}",
                text=rendered,
                fingerprint=hashlib.sha256(rendered.encode()).hexdigest(),
                observed_at=state.updated_at,
                required=True,
                approved_task_state=True,
                evidence_ids=(f"event:{state.content.source_event_id}",),
                priority=1,
                source_warnings=state.warnings,
            ),
        )
