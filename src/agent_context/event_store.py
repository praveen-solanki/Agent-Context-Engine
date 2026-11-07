"""Atomic single-document outbox; no cross-database transaction is assumed."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError

from agent_context.contracts import (
    EventInput,
    EventKind,
    Permission,
    Principal,
    ProcessingState,
    RecentContext,
    RecentEvent,
    RecentRequest,
    Stream,
    utcnow,
)
from agent_context.events import EventConflict, append_event
from agent_context.navigation import SessionEntry, SessionPage, SessionTitle
from agent_context.privacy import PrivacyControls

RECENT_SESSION_WINDOW = 16


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
        self.privacy = PrivacyControls(client, database)

    async def ensure_indexes(self) -> None:
        await self.privacy.ensure_indexes()
        await self.collection.create_index(
            [("tenant_id", 1), ("session_id", 1)], unique=True
        )
        await self.collection.create_index(
            [("tenant_id", 1), ("event_ids", 1)], unique=True, sparse=True
        )
        await self.collection.create_index([("tenant_id", 1), ("lease_until", 1)])
        await self.collection.create_index(
            [
                ("tenant_id", 1),
                ("data.user_id", 1),
                ("data.project_id", 1),
                ("updated_at", -1),
                ("session_id", -1),
            ]
        )

    async def record(self, principal: Principal, event: EventInput) -> Stream:
        privacy = await self.privacy.require_active(
            principal.tenant_id, principal.user_id
        )
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
                await self.privacy.require_active(
                    principal.tenant_id, principal.user_id
                )
                return stream
            fields = {
                "data": updated.model_dump(mode="json"),
                "event_ids": [item.event.event_id for item in updated.events],
                "updated_at": utcnow(),
                "assertion_grants": {
                    **(document.get("assertion_grants", {}) if document else {}),
                    event.event_id: {
                        "permissions": sorted(principal.permissions),
                        "privacy_revision": privacy.revision,
                    },
                },
            }
            try:
                if document is None:
                    await self.collection.insert_one(
                        {
                            **key,
                            **fields,
                            "revision": 1,
                            "lease_until": utcnow(),
                            "console_title": " ".join(event.text.split())[:80]
                            or "Conversation",
                        }
                    )
                    await self.privacy.require_active_after_write(
                        principal, self.collection, user_field="data.user_id"
                    )
                    return updated
                result = await self.collection.update_one(
                    {**key, "revision": document["revision"]},
                    {"$set": fields, "$inc": {"revision": 1}},
                )
                if result.modified_count:
                    await self.privacy.require_active_after_write(
                        principal, self.collection, user_field="data.user_id"
                    )
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

    async def recent(
        self, principal: Principal, request: RecentRequest
    ) -> RecentContext:
        """Bounded project-local pending user assertions, never a second memory store."""
        principal.require(Permission.VIEW, request.project_id)
        privacy = await self.privacy.require_active(
            principal.tenant_id, principal.user_id
        )
        cursor = await self.collection.aggregate(
            [
                {
                    "$match": {
                        "tenant_id": principal.tenant_id,
                        "data.user_id": principal.user_id,
                        "data.project_id": request.project_id,
                        "$expr": {
                            "$lt": [
                                "$data.available_sequence",
                                {"$size": "$data.events"},
                            ]
                        },
                        "$or": [
                            {"data.derive_context": True},
                            {"session_id": request.session_id},
                        ],
                    }
                },
                {"$sort": {"updated_at": -1, "session_id": -1}},
                {"$limit": RECENT_SESSION_WINDOW + 1},
                {
                    "$facet": {
                        "window": [{"$count": "count"}],
                        "items": [
                            {"$limit": RECENT_SESSION_WINDOW},
                            {"$unwind": "$data.events"},
                            {
                                "$match": {
                                    "data.events.actor_kind": "user",
                                    "data.events.event.kind": {
                                        "$in": ["user_message", "correction"]
                                    },
                                    "data.events.event.event_id": {
                                        "$ne": request.exclude_event_id
                                    },
                                    "$expr": {
                                        "$gt": [
                                            "$data.events.event.sequence",
                                            "$data.available_sequence",
                                        ]
                                    },
                                }
                            },
                            {
                                "$sort": {
                                    "data.events.received_at": -1,
                                    "data.events.event.event_id": -1,
                                }
                            },
                            {"$limit": request.limit + 1},
                            {
                                "$project": {
                                    "_id": 0,
                                    "record": "$data.events",
                                    "assertion_grants": 1,
                                }
                            },
                        ],
                    }
                },
            ]
        )
        result = (await cursor.to_list())[0]
        rows = result["items"]
        items: list[RecentEvent] = []
        used = 0
        truncated = len(rows) > request.limit or bool(
            result["window"] and result["window"][0]["count"] > RECENT_SESSION_WINDOW
        )
        for row in rows[: request.limit]:
            record = row["record"]
            event = record["event"]
            grant = row.get("assertion_grants", {}).get(event["event_id"], {})
            if grant.get("privacy_revision", 0) != privacy.revision:
                # Raw pending text must not bypass a revocation of its derived
                # memory. Without exact derived lineage, withhold the old input
                # conservatively; retain it in the inspectable event history.
                truncated = True
                continue
            if event["event_id"] == request.exclude_event_id:
                continue
            item = RecentEvent(
                session_id=event["session_id"],
                event_id=event["event_id"],
                text=event["text"],
                kind=EventKind(event["kind"]),
                received_at=record["received_at"],
            )
            size = len(item.model_dump_json().encode())
            if used + size > request.max_bytes:
                truncated = True
                break  # Never let an older assertion displace an oversized newer correction.
            used += size
            items.append(item)
        current = await self.privacy.require_active(
            principal.tenant_id, principal.user_id
        )
        if current.revision != privacy.revision:
            raise RuntimeError("privacy changed during pending context retrieval")
        return RecentContext(items=tuple(reversed(items)), truncated=truncated)

    async def sessions(
        self,
        principal: Principal,
        project_id: str,
        *,
        limit: int = 30,
        cursor: str | None = None,
    ) -> SessionPage:
        principal.require(Permission.VIEW, project_id)
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        if not 1 <= limit <= 100:
            raise ValueError("session page limit is out of range")
        query: dict[str, Any] = {
            "tenant_id": principal.tenant_id,
            "data.user_id": principal.user_id,
            "data.project_id": project_id,
        }
        binding = hashlib.sha256(
            json.dumps([principal.tenant_id, principal.user_id, project_id]).encode()
        ).hexdigest()
        if cursor:
            try:
                if len(cursor) > 1024:
                    raise ValueError
                page = json.loads(
                    base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
                )
                if page["binding"] != binding:
                    raise ValueError
                previous = SessionEntry.model_validate(page["last"])
                if previous.project_id != project_id:
                    raise ValueError
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError("invalid session cursor") from error
            if previous.updated_at is None:
                query.update(
                    {"updated_at": None, "session_id": {"$lt": previous.session_id}}
                )
            else:
                query["$or"] = [
                    {"updated_at": {"$lt": previous.updated_at}},
                    {
                        "updated_at": previous.updated_at,
                        "session_id": {"$lt": previous.session_id},
                    },
                    {"updated_at": None},
                ]
        rows = (
            await self.collection.find(
                query, {"session_id": 1, "console_title": 1, "updated_at": 1}
            )
            .sort([("updated_at", -1), ("session_id", -1)])
            .limit(limit + 1)
            .to_list()
        )
        entries = tuple(
            SessionEntry(
                session_id=row["session_id"],
                project_id=project_id,
                title=row.get("console_title") or "Conversation",
                updated_at=row.get("updated_at"),
            )
            for row in rows[:limit]
        )
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {"binding": binding, "last": entries[-1].model_dump(mode="json")}
                ).encode()
            )
            .decode()
            .rstrip("=")
            if len(rows) > limit
            else None
        )
        return SessionPage(sessions=entries, next_cursor=next_cursor)

    async def rename(
        self, principal: Principal, session_id: str, request: SessionTitle
    ) -> SessionEntry:
        stream = await self.get(principal, session_id)
        principal.require(Permission.ASSERT, stream.project_id)
        if principal.actor_kind != "user" or stream.project_id is None:
            raise PermissionError("only the user can rename a project conversation")
        title = request.title.strip()
        if not title:
            raise ValueError("conversation title cannot be blank")
        document = await self.collection.find_one_and_update(
            {
                "tenant_id": principal.tenant_id,
                "data.user_id": principal.user_id,
                "session_id": session_id,
            },
            {"$set": {"console_title": title}},
            return_document=ReturnDocument.AFTER,
        )
        if document is None:
            raise LookupError("conversation not found")
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        return SessionEntry(
            session_id=session_id,
            project_id=stream.project_id,
            title=title,
            updated_at=document.get("updated_at"),
        )

    async def get(self, principal: Principal, session_id: str) -> Stream:
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
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
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
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
