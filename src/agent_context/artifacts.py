"""Private versioned artifact registry; digests are computed from actual bytes."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from pydantic import Field, model_validator
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError
from typing_extensions import Self

from agent_context.contracts import Contract, Identifier, Permission, Principal
from agent_context.events import EventConflict
from agent_context.handoff import ArtifactRef
from agent_context.privacy import PrivacyControls


class ArtifactInput(Contract):
    artifact_id: Identifier
    project_id: Identifier
    expected_version: int = Field(ge=0)
    content: str = Field(max_length=64000)

    @model_validator(mode="after")
    def byte_bound(self) -> Self:
        if len(self.content.encode()) > 64000:
            raise ValueError("artifact exceeds the UTF-8 byte bound")
        return self


class ArtifactDocument(Contract):
    artifact_id: Identifier
    project_id: Identifier
    version: int
    sha256: str
    content: str


class ArtifactStore:
    def __init__(self, client: AsyncMongoClient[Any], database: str) -> None:
        self.collection = client[database]["ace_artifacts_v1"]
        self.privacy = PrivacyControls(client, database)

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("tenant_id", 1), ("user_id", 1), ("project_id", 1), ("artifact_id", 1)],
            unique=True,
        )

    @staticmethod
    def _key(principal: Principal, project_id: str, artifact_id: str) -> dict[str, str]:
        return {
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "project_id": project_id,
            "artifact_id": artifact_id,
        }

    async def publish(
        self, principal: Principal, request: ArtifactInput
    ) -> ArtifactDocument:
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        principal.require(Permission.ASSERT, request.project_id)
        key = self._key(principal, request.project_id, request.artifact_id)
        existing = await self.collection.find_one(key)
        digest = sha256(request.content.encode()).hexdigest()
        if existing is not None:
            old = ArtifactDocument.model_validate(existing["document"])
            if old.sha256 == digest:
                await self.privacy.require_active(
                    principal.tenant_id, principal.user_id
                )
                return old
            if old.version != request.expected_version:
                raise EventConflict("artifact version precondition failed")
        elif request.expected_version != 0:
            raise EventConflict("new artifact requires a version zero precondition")
        document = ArtifactDocument(
            artifact_id=request.artifact_id,
            project_id=request.project_id,
            version=request.expected_version + 1,
            sha256=digest,
            content=request.content,
        )
        try:
            if existing is None:
                await self.collection.insert_one(
                    {**key, "document": document.model_dump()}
                )
            else:
                result = await self.collection.update_one(
                    {**key, "document.version": request.expected_version},
                    {"$set": {"document": document.model_dump()}},
                )
                if not result.modified_count:
                    raise EventConflict("artifact changed concurrently")
        except DuplicateKeyError as error:
            raise EventConflict(
                "artifact created concurrently; retry the request"
            ) from error
        await self.privacy.require_active_after_write(principal, self.collection)
        return document

    async def get(
        self, principal: Principal, project_id: str, artifact_id: str
    ) -> ArtifactDocument:
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        principal.require(Permission.VIEW, project_id)
        document = await self.collection.find_one(
            self._key(principal, project_id, artifact_id)
        )
        if document is None:
            raise LookupError("artifact not found")
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        return ArtifactDocument.model_validate(document["document"])

    async def verify(self, principal: Principal, reference: ArtifactRef) -> bool:
        try:
            document = await self.get(
                principal, reference.project_id, reference.artifact_id
            )
        except (PermissionError, LookupError):
            return False
        return document.sha256 == reference.sha256
