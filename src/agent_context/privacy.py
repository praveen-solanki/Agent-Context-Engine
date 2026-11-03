"""Fail-closed user controls independent of eventual graph replay."""

from __future__ import annotations

from typing import Any

from pymongo import AsyncMongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pydantic import Field

from agent_context.contracts import Contract, Identifier, Permission, Principal, utcnow
from agent_context.events import CapacityExceeded

MAX_BLOCKED_IDS = 4096


class PrivacyState(Contract):
    tenant_id: Identifier
    user_id: Identifier
    revision: int = 0
    erased: bool = False
    blocked_item_ids: tuple[str, ...] = Field(default=(), max_length=MAX_BLOCKED_IDS)


class PrivacyControls:
    def __init__(self, client: AsyncMongoClient[Any], database: str) -> None:
        self.collection = client[database]["ace_privacy_v1"]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("tenant_id", 1), ("user_id", 1)], unique=True
        )

    async def state(self, tenant_id: str, user_id: str) -> PrivacyState:
        document = await self.collection.find_one(
            {"tenant_id": tenant_id, "user_id": user_id}, {"_id": 0, "updated_at": 0}
        )
        return (
            PrivacyState(tenant_id=tenant_id, user_id=user_id)
            if document is None
            else PrivacyState.model_validate(document)
        )

    async def require_active(self, tenant_id: str, user_id: str) -> PrivacyState:
        state = await self.state(tenant_id, user_id)
        if state.erased:
            raise PermissionError("subject is quarantined for erasure")
        return state

    async def block(self, principal: Principal, item_id: str) -> PrivacyState:
        principal.require(Permission.CORRECT)
        # The caller must check actual item ownership in its graph query before
        # calling this method. IDs are metadata; never store private item text.
        await self.require_active(principal.tenant_id, principal.user_id)
        query = {
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "$or": [
                {"blocked_item_ids": item_id},
                {f"blocked_item_ids.{MAX_BLOCKED_IDS - 1}": {"$exists": False}},
            ],
        }
        update = {
            "$addToSet": {"blocked_item_ids": item_id},
            "$inc": {"revision": 1},
            "$set": {"updated_at": utcnow()},
            "$setOnInsert": {"erased": False},
        }
        try:
            await self.collection.find_one_and_update(
                query, update, upsert=True, return_document=ReturnDocument.AFTER
            )
        except DuplicateKeyError:
            state = await self.state(principal.tenant_id, principal.user_id)
            if (
                len(state.blocked_item_ids) >= MAX_BLOCKED_IDS
                and item_id not in state.blocked_item_ids
            ):
                raise CapacityExceeded(
                    "revocation metadata quota reached; full subject erasure remains available"
                ) from None
            await self.collection.update_one(query, update)
        return await self.state(principal.tenant_id, principal.user_id)

    async def quarantine(self, principal: Principal) -> PrivacyState:
        principal.require(Permission.DELETE)
        query = {"tenant_id": principal.tenant_id, "user_id": principal.user_id}
        update = {
            "$set": {"erased": True, "updated_at": utcnow()},
            "$inc": {"revision": 1},
            "$setOnInsert": {"blocked_item_ids": []},
        }
        try:
            await self.collection.update_one(query, update, upsert=True)
        except DuplicateKeyError:
            await self.collection.update_one(query, update)
        return await self.state(principal.tenant_id, principal.user_id)
