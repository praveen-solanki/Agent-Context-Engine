"""Versioned boundary types; caller identity is deliberately absent from event input."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    model_validator,
)
from typing_extensions import Self

Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]
SuggestedStep = Annotated[str, Field(min_length=1, max_length=120)]
PROJECT_TASK_ID = "project-work"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Permission(StrEnum):
    VIEW = "view"
    ASSERT = "assert"
    CORRECT = "correct"
    DELETE = "delete"
    ADMIN = "admin"


class Principal(Contract):
    """Constructed by a trusted gateway, never deserialized from a request body."""

    tenant_id: Identifier
    user_id: Identifier
    actor_id: Identifier
    actor_kind: Literal["user", "agent"] = "user"
    projects: frozenset[Identifier] = frozenset()
    permissions: frozenset[Permission] = frozenset({Permission.VIEW, Permission.ASSERT})

    def require(self, permission: Permission, project_id: str | None = None) -> None:
        if permission not in self.permissions:
            raise PermissionError("operation is not permitted")
        if project_id is not None and project_id not in self.projects:
            raise PermissionError("project access is not permitted")


class EventKind(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_RESULT = "tool_result"
    CORRECTION = "correction"
    REVOCATION = "revocation"
    SESSION_CLOSE = "session_close"


class TaskReference(Contract):
    task_id: Identifier
    version: int = Field(ge=1)


class RevocationInput(Contract):
    item_id: str = Field(min_length=1, max_length=256)
    expected_fingerprint: str = Field(min_length=1, max_length=256)


class EventReference(Contract):
    session_id: Identifier
    event_id: Identifier

    @property
    def source_id(self) -> str:
        return (
            "event:"
            + hashlib.sha256(
                f"{len(self.session_id)}:{self.session_id}{self.event_id}".encode()
            ).hexdigest()
        )


class RecentEvent(EventReference):
    text: str
    kind: EventKind
    received_at: AwareDatetime


class RecentRequest(Contract):
    project_id: Identifier
    session_id: Identifier
    max_bytes: int = Field(default=2000, ge=256, le=16000)
    limit: int = Field(default=20, ge=1, le=64)
    exclude_event_id: Identifier | None = None


class RecentContext(Contract):
    items: tuple[RecentEvent, ...] = ()
    truncated: bool = False


class EventInput(Contract):
    schema_version: Literal[1] = 1
    event_id: Identifier
    session_id: Identifier
    agent_id: Identifier
    sequence: int = Field(ge=1)
    event_time: AwareDatetime
    kind: EventKind
    text: str = Field(default="", max_length=16000)
    project_id: Identifier | None = None
    run_id: Identifier | None = None
    correlation_id: Identifier | None = None
    causation_id: Identifier | None = None
    tool_call_id: Identifier | None = None
    tool_succeeded: StrictBool | None = None
    derive_context: StrictBool | None = None
    citations: tuple[Identifier, ...] = Field(default=(), max_length=64)
    suggested_next_steps: tuple[SuggestedStep, ...] = Field(default=(), max_length=4)
    task_context: TaskReference | None = None
    correction_target: RevocationInput | None = None
    background_updates: StrictBool = False
    context_event_refs: tuple[EventReference, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def bounded_payload(self) -> Self:
        if self.background_updates and self.kind not in (
            EventKind.USER_MESSAGE,
            EventKind.CORRECTION,
        ):
            raise ValueError("background updates require a user message")
        if self.context_event_refs and self.kind != EventKind.ASSISTANT_MESSAGE:
            raise ValueError("event evidence references belong to assistant answers")
        if self.correction_target is not None and self.kind != EventKind.CORRECTION:
            raise ValueError("a memory replacement requires an explicit correction")
        if self.suggested_next_steps and self.kind != EventKind.ASSISTANT_MESSAGE:
            raise ValueError("only assistant messages can carry unapproved suggestions")
        if self.task_context is not None and self.kind != EventKind.ASSISTANT_MESSAGE:
            raise ValueError("task context references belong to assistant answers")
        if any(
            not step.strip() or len(step.encode()) > 500
            for step in self.suggested_next_steps
        ):
            raise ValueError("suggestions must be nonempty and bounded")
        if len(self.text.encode("utf-8")) > 16000:
            raise ValueError("event text exceeds UTF-8 byte limit")
        if self.kind != EventKind.SESSION_CLOSE and not self.text.strip():
            raise ValueError("message events require nonempty text")
        if self.kind == EventKind.SESSION_CLOSE and self.text:
            raise ValueError("session close does not carry message content")
        if self.kind != EventKind.TOOL_RESULT and (
            self.tool_call_id is not None or self.tool_succeeded is not None
        ):
            raise ValueError("only tool results carry tool outcome fields")
        if self.citations and self.kind != EventKind.ASSISTANT_MESSAGE:
            raise ValueError("only assistant messages carry answer citations")
        if (self.tool_call_id is None) != (self.tool_succeeded is None):
            raise ValueError("tool call ID and success must be supplied together")
        return self


class RecordedEvent(Contract):
    event: EventInput
    actor_id: Identifier
    actor_kind: Literal["user", "agent"]
    received_at: AwareDatetime = Field(default_factory=utcnow)


class ProcessingState(StrEnum):
    RECORDED = "recorded"
    PROCESSING = "processing"
    AVAILABLE = "available"
    FAILED = "failed"
    DEAD = "dead_letter"


class EventStatus(Contract):
    session_id: Identifier
    recorded_sequence: int
    available_sequence: int
    state: ProcessingState
    attempts: int = 0


class Stream(Contract):
    tenant_id: Identifier
    user_id: Identifier
    session_id: Identifier
    project_id: Identifier | None = None
    derive_context: bool = True
    events: tuple[RecordedEvent, ...] = ()
    available_sequence: int = 0
    state: ProcessingState = ProcessingState.RECORDED
    attempts: int = 0

    def status(self) -> EventStatus:
        state = self.state
        if state == ProcessingState.AVAILABLE and self.available_sequence < len(
            self.events
        ):
            state = ProcessingState.RECORDED
        return EventStatus(
            session_id=self.session_id,
            recorded_sequence=len(self.events),
            available_sequence=self.available_sequence,
            state=state,
            attempts=self.attempts,
        )
