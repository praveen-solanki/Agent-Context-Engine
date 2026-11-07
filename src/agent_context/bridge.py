"""Event-to-session adapter reusing the original extraction/writer pipeline."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from hashlib import sha256

from agent_context.contracts import EventKind, Stream
from agent_context.event_store import MongoEventStore
from context_graph.domain.conversation import MessageInput, SessionInput
from context_graph.domain.enums import Role, SessionState
from context_graph.observability import get_logger, log_context, log_event, stage
from context_graph.pipeline.orchestrator import IngestionReport


def scoped_id(tenant_id: str, identifier: str) -> str:
    """Length-framed IDs prevent delimiter collisions and legacy ID overlap."""
    return (
        "ace_"
        + sha256(f"{len(tenant_id)}:{tenant_id}{identifier}".encode()).hexdigest()
    )


def to_session(stream: Stream) -> SessionInput:
    roles = {
        EventKind.USER_MESSAGE: Role.USER,
        EventKind.CORRECTION: Role.USER,
        EventKind.REVOCATION: Role.USER,
        EventKind.ASSISTANT_MESSAGE: Role.AGENT,
        EventKind.TOOL_RESULT: Role.TOOL,
    }
    messages = tuple(
        MessageInput(
            message_id=scoped_id(stream.tenant_id, recorded.event.event_id),
            sequence=recorded.event.sequence,
            timestamp=recorded.event.event_time,
            role=roles[recorded.event.kind],
            text=recorded.event.text,
            sender_id=scoped_id(
                stream.tenant_id,
                stream.user_id
                if roles[recorded.event.kind] == Role.USER
                else recorded.actor_id,
            ),
            agent_id=scoped_id(stream.tenant_id, recorded.event.agent_id),
            metadata={
                "event_id": recorded.event.event_id,
                "tenant_id": stream.tenant_id,
                "event_kind": recorded.event.kind.value,
            },
        )
        for recorded in stream.events
        if recorded.event.kind in roles
    )
    closed = bool(
        stream.events and stream.events[-1].event.kind == EventKind.SESSION_CLOSE
    )
    return SessionInput(
        session_id=scoped_id(stream.tenant_id, stream.session_id),
        user_id=scoped_id(stream.tenant_id, stream.user_id),
        messages=messages,
        agent_ids=tuple(
            sorted({message.agent_id for message in messages if message.agent_id})
        ),
        state=SessionState.CLOSED if closed else SessionState.OPEN,
        session_end_time=stream.events[-1].event.event_time if closed else None,
        metadata={
            "tenant_id": stream.tenant_id,
            "external_session_id": stream.session_id,
            "ace_event_bridge": True,
            "ace_derive_context": stream.derive_context,
            # Stream identity is authorized on intake and immutable. Keep the
            # binding outside message metadata to preserve old fingerprints.
            "ace_project_id": scoped_id(stream.tenant_id, stream.project_id)
            if stream.project_id
            else None,
        },
    )


class EventWorker:
    """One bounded claim; cancellation/crash leaves the outbox replayable.

    The supplied pipeline must use a stable run_id for this deployment, so its
    segmentation, extraction cache and checkpoints survive retries. A pipeline
    per deployment is shared across streams; workers serialize each session.
    """

    def __init__(
        self,
        store: MongoEventStore,
        ingest: Callable[[SessionInput], Awaitable[IngestionReport]],
        *,
        tenant_id: str,
        timeout_seconds: float = 90,
        lease_seconds: int = 120,
        max_attempts: int = 3,
        maintain: Callable[[Stream], Awaitable[None]] | None = None,
    ) -> None:
        if not 0 < timeout_seconds < lease_seconds or max_attempts < 1:
            raise ValueError(
                "positive processing timeout must be shorter than the lease"
            )
        self.store, self.ingest, self.tenant_id = store, ingest, tenant_id
        self.maintain = maintain
        self.timeout_seconds, self.lease_seconds, self.max_attempts = (
            timeout_seconds,
            lease_seconds,
            max_attempts,
        )

    async def run_once(self) -> bool:
        claim = await self.store.claim(self.tenant_id, lease_seconds=self.lease_seconds)
        if claim is None:
            return False
        stream, token = claim
        try:
            await self.store.privacy.require_active(stream.tenant_id, stream.user_id)
        except PermissionError:
            await self.store.finish(stream, token, success=False, max_attempts=1)
            return True
        success = False
        try:
            with (
                log_context(
                    stream_id=scoped_id(stream.tenant_id, stream.session_id),
                    available_sequence=stream.available_sequence,
                ),
                stage(get_logger("worker"), "worker.ingestion"),
            ):
                async with asyncio.timeout(self.timeout_seconds):
                    report = await self.ingest(to_session(stream))
                    success = not report.batches_failed and not report.errors
                    if success and self.maintain is not None:
                        await self.maintain(stream)
                    log_event(
                        get_logger("worker"),
                        "worker.ingestion_result",
                        success=success,
                        batches_failed=report.batches_failed,
                        error_count=len(report.errors),
                        event_count=len(stream.events),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # No private provider error/content is persisted in status. Detailed
            # diagnostics belong in a separately permissioned redacted sink.
            success = False
            logging.getLogger(__name__).warning(
                "event_processing_failed",
                extra={
                    "error_type": type(error).__name__,
                    "stream_id": scoped_id(stream.tenant_id, stream.session_id),
                },
            )
        if not await self.store.finish(
            stream, token, success=success, max_attempts=self.max_attempts
        ):
            raise RuntimeError("worker lease expired; outcome requires reconciliation")
        return True
