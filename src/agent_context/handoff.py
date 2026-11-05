"""Versioned durable handoff state; resume validates without replaying side effects."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator
from typing_extensions import Self
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from agent_context.assembly import AssembleRequest, ContextAssembler, ContextBundle
from agent_context.contracts import Contract, Identifier, Permission, Principal, utcnow
from agent_context.events import CapacityExceeded, EventConflict
from agent_context.privacy import PrivacyControls


class ArtifactRef(Contract):
    artifact_id: Identifier
    project_id: Identifier
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CompletedAction(Contract):
    action_id: Identifier
    project_id: Identifier
    description: str = Field(min_length=1, max_length=2000)
    source_session_id: Identifier
    result_event_id: Identifier


TASK_STATE_PREFIX = "ace_task."


class WorkState(Contract):
    """The same bounded work contract for live state and historical handoffs."""

    project_id: Identifier
    task_id: Identifier
    source_session_id: Identifier
    goal: str = Field(min_length=1, max_length=4000)
    requirements: tuple[str, ...] = Field(default=(), max_length=32)
    completed: tuple[CompletedAction, ...] = Field(default=(), max_length=32)
    pending: tuple[str, ...] = Field(default=(), max_length=32)
    blockers: tuple[str, ...] = Field(default=(), max_length=32)
    unresolved_operations: tuple[Identifier, ...] = Field(default=(), max_length=32)
    artifacts: tuple[ArtifactRef, ...] = Field(default=(), max_length=32)
    expires_at: AwareDatetime | None = None
    status: Literal["active", "completed", "cancelled"] = "active"
    cancelled: tuple[str, ...] = Field(default=(), max_length=32)
    dependencies: tuple[str, ...] = Field(default=(), max_length=32)
    source_event_id: Identifier | None = None
    must_keep: tuple[str, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def coherent_state(self) -> Self:
        if not set(self.must_keep).issubset(self.requirements):
            raise ValueError("must-keep constraints must be current requirements")
        if set(self.cancelled) & set(self.pending):
            raise ValueError("cancelled steps cannot remain pending")
        if self.status != "active" and (self.pending or self.unresolved_operations):
            raise ValueError("finished tasks cannot retain pending operations")
        return self


class HandoffInput(WorkState):
    schema_version: int = Field(default=1, ge=1, le=1)
    handoff_id: Identifier
    idempotency_key: Identifier
    expected_version: int = Field(ge=0)
    task_state_version: int | None = Field(default=None, ge=1)


class HandoffArtifact(Contract):
    version: int
    created_at: AwareDatetime = Field(default_factory=utcnow)
    content: HandoffInput


class ResumeResult(Contract):
    handoff: HandoffArtifact
    bundle: ContextBundle
    safe_to_continue: bool
    warnings: tuple[str, ...]
    current_task: HandoffArtifact | None = None


ActionVerifier = Callable[[Principal, CompletedAction], Awaitable[bool]]
ArtifactVerifier = Callable[[Principal, ArtifactRef], Awaitable[bool]]
TaskReader = Callable[[Principal, str, str], Awaitable[HandoffArtifact | None]]


class HandoffService:
    """Bounded immutable revisions + optimistic updates in one Mongo document."""

    def __init__(
        self,
        client: AsyncMongoClient[Any],
        database: str,
        *,
        verify_action: ActionVerifier,
        verify_artifact: ArtifactVerifier,
        max_versions: int = 64,
    ) -> None:
        if not 1 <= max_versions <= 64:
            raise ValueError("max_versions must be between 1 and 64")
        self.collection = client[database]["ace_handoffs_v1"]
        self.privacy = PrivacyControls(client, database)
        self.verify_action, self.verify_artifact = verify_action, verify_artifact
        self.max_versions = max_versions

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [("tenant_id", 1), ("user_id", 1), ("handoff_id", 1)], unique=True
        )

    @staticmethod
    def _key(principal: Principal, identifier: str) -> dict[str, str]:
        return {
            "tenant_id": principal.tenant_id,
            "user_id": principal.user_id,
            "handoff_id": identifier,
        }

    @staticmethod
    def _digest(request: HandoffInput) -> str:
        payload = request.model_dump(mode="json")
        # Preserve idempotency hashes written before additive task fields.
        defaults: dict[str, object] = {
            "status": "active", "cancelled": [], "dependencies": [],
            "source_event_id": None, "must_keep": [], "task_state_version": None,
        }
        for name, default in defaults.items():
            if payload[name] == default:
                payload.pop(name)
        return hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    async def prepare(
        self, principal: Principal, request: HandoffInput, *,
        internal_task: bool = False, current_task: TaskReader | None = None,
    ) -> HandoffArtifact:
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        principal.require(Permission.ASSERT, request.project_id)
        if request.handoff_id.startswith(TASK_STATE_PREFIX) and not internal_task:
            raise PermissionError("task state IDs are owned by the task service")
        if len(request.model_dump_json().encode()) > 64000:
            raise CapacityExceeded("handoff exceeds 64KB bound")
        if request.expires_at is not None and request.expires_at <= utcnow():
            raise ValueError("cannot prepare an already expired handoff")
        key = self._key(principal, request.handoff_id)
        existing = await self.collection.find_one(key)
        if existing is not None:
            if (existing["project_id"], existing["task_id"]) != (
                request.project_id,
                request.task_id,
            ):
                raise EventConflict("handoff project and task are immutable")
            for revision in existing["revisions"]:
                if revision["idempotency_key"] == request.idempotency_key:
                    if revision["digest"] != self._digest(request):
                        raise EventConflict("handoff idempotency key was reused")
                    return HandoffArtifact.model_validate(revision["artifact"])
            if existing["version"] != request.expected_version:
                raise EventConflict("handoff version precondition failed")
        elif request.expected_version != 0:
            raise EventConflict("new handoff must use version zero precondition")
        if current_task is not None:
            current = await current_task(principal, request.project_id, request.task_id)
            if current is not None and (
                request.task_state_version != current.version
                or not work_matches(request, current.content)
            ):
                raise EventConflict("handoff must match current task state")
        if request.expected_version >= self.max_versions:
            raise CapacityExceeded(
                "handoff revision limit reached; create a new handoff"
            )
        for action in request.completed:
            if action.project_id != request.project_id or not await self.verify_action(
                principal, action
            ):
                raise ValueError(
                    "completed action lacks an authorized successful tool outcome"
                )
        for artifact in request.artifacts:
            if (
                artifact.project_id != request.project_id
                or not await self.verify_artifact(principal, artifact)
            ):
                raise ValueError("artifact version could not be verified")
        artifact = HandoffArtifact(
            version=request.expected_version + 1, content=request
        )
        revision = {
            "idempotency_key": request.idempotency_key,
            "digest": self._digest(request),
            "artifact": artifact.model_dump(mode="json"),
        }
        try:
            if existing is None:
                await self.collection.insert_one(
                    {
                        **key,
                        "project_id": request.project_id,
                        "task_id": request.task_id,
                        "version": artifact.version,
                        "revisions": [revision],
                    }
                )
            else:
                result = await self.collection.update_one(
                    {**key, "version": request.expected_version},
                    {
                        "$set": {"version": artifact.version},
                        "$push": {"revisions": revision},
                    },
                )
                if not result.modified_count:
                    raise EventConflict(
                        "handoff changed concurrently; retry the same request"
                    )
        except DuplicateKeyError as error:
            # A first-create race must not produce two version-one snapshots.
            raise EventConflict(
                "handoff created concurrently; retry the same request"
            ) from error
        return artifact

    async def latest(self, principal: Principal, identifier: str) -> HandoffArtifact:
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        principal.require(Permission.VIEW)
        # Do not project private state before checking the current project grant.
        metadata = await self.collection.find_one(
            self._key(principal, identifier), {"project_id": 1}
        )
        if metadata is None:
            raise LookupError("handoff not found")
        principal.require(Permission.VIEW, metadata["project_id"])
        document = await self.collection.find_one(
            {
                **self._key(principal, identifier),
                "project_id": {"$in": list(principal.projects)},
            },
            {"revisions": {"$slice": -1}},
        )
        if document is None:
            raise LookupError("handoff not found")
        return HandoffArtifact.model_validate(document["revisions"][0]["artifact"])

    async def resume(
        self,
        principal: Principal,
        identifier: str,
        *,
        expected_version: int,
        request: AssembleRequest,
        assembler: ContextAssembler,
        current_task: TaskReader | None = None,
    ) -> ResumeResult:
        handoff = await self.latest(principal, identifier)
        content = handoff.content
        if content.project_id != request.project_id:
            raise PermissionError("assembly project does not match the handoff")
        if request.task_id is not None and request.task_id != content.task_id:
            raise PermissionError("assembly task does not match the handoff")
        warnings: list[str] = []
        if expected_version != handoff.version:
            warnings.append("stale_handoff_version")
        if content.expires_at is not None and content.expires_at <= utcnow():
            warnings.append("handoff_expired")
        current = (
            await current_task(principal, content.project_id, content.task_id)
            if current_task else None
        )
        if current is not None:
            if content.task_state_version != current.version or not work_matches(content, current.content):
                warnings.append("stale_task_state")
            content = current.content
            request = request.model_copy(update={
                "task_id": content.task_id, "task_version": current.version,
            })
        if content.status != "active":
            warnings.append("task_is_not_active")
        if current is not None and content.expires_at is not None and content.expires_at <= utcnow():
            warnings.append("task_state_expired")
        if content.unresolved_operations:
            warnings.append("pending_operations_require_reconciliation")
        for artifact in content.artifacts:
            if not await self.verify_artifact(principal, artifact):
                warnings.append("artifact_version_changed")
        for action in content.completed:
            if not await self.verify_action(principal, action):
                warnings.append("completed_action_no_longer_verifiable")
        bundle = await assembler.assemble(principal, request)
        if "unresolved_single_value_conflicts" in bundle.warnings:
            warnings.append("unresolved_single_value_conflicts")
        if current_task and current:
            latest = await current_task(principal, content.project_id, content.task_id)
            if latest is None or latest.version != current.version:
                warnings.append("task_changed_during_resume")
        # The host receives live assembled context plus explicitly labeled
        # historical work state. This method never invokes a tool or action.
        return ResumeResult(
            handoff=handoff,
            bundle=bundle,
            safe_to_continue=not warnings,
            warnings=tuple(dict.fromkeys(warnings)),
            current_task=current,
        )


def work_matches(snapshot: WorkState, current: WorkState) -> bool:
    """Session/expiry/recording metadata is lineage, not an effective requirement."""
    excluded = {"source_session_id", "source_event_id", "expires_at"}
    fields = set(WorkState.model_fields) - excluded
    return snapshot.model_dump(include=fields) == current.model_dump(include=fields)
