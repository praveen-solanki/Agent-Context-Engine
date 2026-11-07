"""Worker-owned project updates over the existing event outbox and task CAS."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from agent_context.continuity import plan_task, successful_actions
from agent_context.contracts import (
    PROJECT_TASK_ID,
    EventKind,
    Permission,
    Principal,
    RecordedEvent,
    Stream,
)
from agent_context.demo import DemoSettings
from agent_context.events import EventConflict
from agent_context.project_store import ProjectStore
from agent_context.task_state import TaskStateService, TaskUpdate
from context_graph.observability import get_logger, log_event
from context_graph.providers.base import LLMProvider


class ProjectMaintenance:
    def __init__(
        self,
        tasks: TaskStateService,
        projects: ProjectStore,
        bindings: Mapping[str, Principal],
        llm: LLMProvider,
    ) -> None:
        self.tasks, self.projects, self.bindings, self.llm = (
            tasks,
            projects,
            bindings,
            llm,
        )

    async def actor(self, stream: Stream, record: RecordedEvent) -> Principal:
        document = await self.tasks.events.collection.find_one(
            {
                "tenant_id": stream.tenant_id,
                "session_id": stream.session_id,
                "data.user_id": stream.user_id,
            },
            {"assertion_grants": 1},
        )
        grants = frozenset(
            Permission(value)
            for value in (document or {})
            .get("assertion_grants", {})
            .get(record.event.event_id, {})
            .get("permissions", ())
        )
        for bound in self.bindings.values():
            if (bound.tenant_id, bound.user_id, bound.actor_id, bound.actor_kind) != (
                stream.tenant_id,
                stream.user_id,
                record.actor_id,
                record.actor_kind,
            ):
                continue
            # A later stronger token must not upgrade the authority of an old event.
            actor = await self.projects.authorize(
                bound.model_copy(update={"permissions": bound.permissions & grants})
            )
            if (
                stream.project_id in actor.projects
                and {Permission.VIEW, Permission.ASSERT} <= actor.permissions
            ):
                return actor
        raise PermissionError("background update is no longer authorized")

    async def latest_user_source(
        self, actor: Principal, project_id: str, version: int
    ) -> RecordedEvent | None:
        """Agent receipts cannot become an ordering boundary for user intent."""
        document = await self.tasks.snapshots.collection.find_one(
            {
                "tenant_id": actor.tenant_id,
                "user_id": actor.user_id,
                "handoff_id": self.tasks.identifier(actor, project_id, PROJECT_TASK_ID),
                "version": version,
            },
            {"revisions": 1},
        )
        if document is None:
            raise EventConflict("project changed during background planning")
        streams: dict[str, Stream] = {}
        # Snapshot history already has a fixed revision bound. Reuse it rather
        # than maintaining another ordering marker or memory collection.
        for revision in reversed(document["revisions"]):
            content = revision["artifact"]["content"]
            session_id = content["source_session_id"]
            if session_id not in streams:
                streams[session_id] = await self.tasks.events.get(actor, session_id)
            for record in streams[session_id].events:
                if (
                    record.event.event_id == content["source_event_id"]
                    and record.actor_kind == "user"
                ):
                    return record
        return None

    async def __call__(self, stream: Stream) -> None:
        if not stream.derive_context or stream.project_id is None:
            return
        for record in stream.events:
            event = record.event
            if (
                event.sequence <= stream.available_sequence
                or record.actor_kind != "user"
                or not event.background_updates
            ):
                continue
            key = hashlib.sha256(
                f"{len(event.session_id)}:{event.session_id}{event.event_id}".encode()
            ).hexdigest()
            actor = await self.actor(stream, record)
            directory = await self.projects.directory(actor)
            if any(
                p.project_id == stream.project_id and p.kind == "personal"
                for p in directory.projects
            ):
                continue
            try:
                state = await self.tasks.current(
                    actor, stream.project_id, PROJECT_TASK_ID
                )
            except LookupError:
                state = None
            if event.sequence > stream.available_sequence and (
                state is None or state.content.source_event_id != event.event_id
            ):
                if state is not None:
                    source = await self.latest_user_source(
                        actor, stream.project_id, state.version
                    )
                    if source is not None and (
                        source.event.session_id,
                        source.event.event_id,
                    ) == (event.session_id, event.event_id):
                        continue
                    if source is not None and source.received_at > record.received_at:
                        log_event(
                            get_logger("maintenance"),
                            "task.older_event_preserved_as_memory",
                        )
                        continue
                planned = await plan_task(
                    self.llm,
                    DemoSettings(project_id=stream.project_id, workspace_mode=True),
                    state.content if state else None,
                    event,
                )
                if planned.content is not None and (
                    state is None or planned.content != state.content
                ):
                    state = await self.tasks.update(
                        actor,
                        TaskUpdate.model_validate(
                            {
                                **planned.content.model_dump(),
                                "source_session_id": event.session_id,
                                "source_event_id": event.event_id,
                                "expected_version": state.version if state else 0,
                                "idempotency_key": key + "-intent",
                            }
                        ),
                    )
                log_event(
                    get_logger("maintenance"),
                    "task.update_processed",
                    feedback=planned.feedback,
                    model_calls=planned.model_calls,
                )

        background_turns = {
            r.event.event_id
            for r in stream.events
            if r.actor_kind == "user" and r.event.background_updates
        }
        for record in stream.events:
            event = record.event
            if (
                event.sequence <= stream.available_sequence
                or event.kind != EventKind.TOOL_RESULT
                or event.causation_id not in background_turns
                or not event.tool_succeeded
            ):
                continue
            actor = await self.actor(stream, record)
            try:
                state = await self.tasks.current(
                    actor, stream.project_id, PROJECT_TASK_ID
                )
            except LookupError:
                continue
            receipts = successful_actions(stream, event.causation_id)
            merged = tuple(
                {r.action_id: r for r in (*state.content.completed, *receipts)}.values()
            )
            if merged != state.content.completed:
                key = hashlib.sha256(
                    f"{len(event.session_id)}:{event.session_id}{event.event_id}".encode()
                ).hexdigest()
                await self.tasks.update(
                    actor,
                    TaskUpdate.model_validate(
                        {
                            **state.content.model_dump(),
                            "completed": merged,
                            "source_session_id": event.session_id,
                            "source_event_id": event.event_id,
                            "expected_version": state.version,
                            "idempotency_key": key + "-progress",
                        }
                    ),
                )
