"""Atomic single-document outbox; no cross-database transaction is assumed."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

from agent_context.contracts import (
    EventInput,
    Permission,
    Principal,
    ProcessingState,
    Stream,
    utcnow,
)
from agent_context.events import EventConflict, append_event


class MongoEventStore:
    """Bounded streams make event + outbox append one atomic Mongo write.

    Sessions have at most 128 * 16KB events by default. Leases are fenced by a
    random token; a worker must finish before expiry or leave work replayable.
    Mongo must use acknowledged durable writes (production URI: w=majority).
    """

    def __init__(
        self, client: AsyncMongoClient[Any], database: str, *, max_events: int = 128
    ) -> None:
        if not 1 <= max_events <= 256:
            raise ValueError("max_events must be between 1 and 256")
        self.collection = client[database]["ace_event_streams_v1"]
        self.max_events = max_events

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("tenant_id", 1), ("session_id", 1)], unique=True
        )
        await self.collection.create_index(
            [("tenant_id", 1), ("event_ids", 1)], unique=True, sparse=True
        )
        await self.collection.create_index([("tenant_id", 1), ("lease_until", 1)])

    async def record(self, principal: Principal, event: EventInput) -> Stream:
        # First check policy even for new sessions. Never let forbidden input
        # allocate a durable session or reserve another principal's identifier.
        empty = Stream(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            session_id=event.session_id,
            project_id=event.project_id,
        )
        append_event(
            empty,
            principal,
            event.model_copy(update={"sequence": 1}),
            max_events=self.max_events,
        )
        key = {"tenant_id": principal.tenant_id, "session_id": event.session_id}
        for _ in range(16):
            document = await self.collection.find_one(key)
            stream = (
                empty if document is None else Stream.model_validate(document["data"])
            )
            updated = append_event(stream, principal, event, max_events=self.max_events)
            if updated == stream:
                return stream
            fields = {
                "data": updated.model_dump(mode="json"),
                "event_ids": [item.event.event_id for item in updated.events],
            }
            try:
                if document is None:
                    await self.collection.insert_one(
                        {**key, **fields, "revision": 1, "lease_until": utcnow()}
                    )
                    return updated
                result = await self.collection.update_one(
                    {**key, "revision": document["revision"]},
                    {"$set": fields, "$inc": {"revision": 1}},
                )
                if result.modified_count:
                    return updated
            except DuplicateKeyError as error:
                # A competing first append is retryable. A globally reused
                # event ID is a conflict, without exposing its owner/content.
                existing = await self.collection.find_one(
                    {**key, "event_ids": event.event_id}
                )
                if existing is None and await self.collection.find_one(key) is not None:
                    raise EventConflict("event ID or sequence conflict") from error
        raise EventConflict("concurrent writes; retry with the same event ID")

    async def get(self, principal: Principal, session_id: str) -> Stream:
        principal.require(Permission.VIEW)
        document = await self.collection.find_one(
            {
                "tenant_id": principal.tenant_id,
                "session_id": session_id,
                "data.user_id": principal.user_id,
            }
        )
        if document is None:
            raise LookupError("session not found")
        stream = Stream.model_validate(document["data"])
        principal.require(Permission.VIEW, stream.project_id)
        return stream

    async def claim(
        self, tenant_id: str, *, lease_seconds: int = 120
    ) -> tuple[Stream, str] | None:
        if lease_seconds <= 0:
            raise ValueError("lease must be positive")
        now, token = utcnow(), uuid4().hex
        document = await self.collection.find_one_and_update(
            {
                "tenant_id": tenant_id,
                "data.state": {"$ne": ProcessingState.DEAD.value},
                "lease_until": {"$lte": now},
                "$expr": {"$lt": ["$data.available_sequence", {"$size": "$event_ids"}]},
            },
            {
                "$set": {
                    "lease_token": token,
                    "lease_until": now + timedelta(seconds=lease_seconds),
                    "data.state": ProcessingState.PROCESSING.value,
                },
                "$inc": {"revision": 1},
            },
            return_document=ReturnDocument.AFTER,
            sort=[("lease_until", 1)],
        )
        return (
            None
            if document is None
            else (Stream.model_validate(document["data"]), token)
        )

    async def finish(
        self, stream: Stream, token: str, *, success: bool, max_attempts: int = 3
    ) -> bool:
        """Advance availability only after durable graph outcomes, never on enqueue."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        key = {
            "tenant_id": stream.tenant_id,
            "session_id": stream.session_id,
            "lease_token": token,
            "lease_until": {"$gt": utcnow()},
        }
        # An append may have arrived during processing. Update only processing
        # fields; never overwrite that newer event list.
        state = (
            ProcessingState.AVAILABLE
            if success
            else (
                ProcessingState.DEAD
                if stream.attempts + 1 >= max_attempts
                else ProcessingState.FAILED
            )
        )
        fields: dict[str, Any] = {"data.state": state.value, "lease_until": utcnow()}
        if success:
            fields["data.available_sequence"] = len(stream.events)
            fields["data.attempts"] = 0
        else:
            fields["data.attempts"] = stream.attempts + 1
        result = await self.collection.update_one(
            key,
            {"$set": fields, "$unset": {"lease_token": ""}, "$inc": {"revision": 1}},
        )
        return bool(result.modified_count)

    async def replay(self, principal: Principal, session_id: str) -> None:
        principal.require(Permission.ADMIN)
        stream = await self.get(principal, session_id)
        result = await self.collection.update_one(
            {
                "tenant_id": principal.tenant_id,
                "session_id": session_id,
                "lease_until": {"$lte": utcnow()},
                "data.state": ProcessingState.DEAD.value,
            },
            {
                "$set": {
                    "data.state": ProcessingState.RECORDED.value,
                    "data.attempts": 0,
                },
                "$inc": {"revision": 1},
            },
        )
        if not result.modified_count and stream.state == ProcessingState.DEAD:
            raise EventConflict("stream is currently leased")
