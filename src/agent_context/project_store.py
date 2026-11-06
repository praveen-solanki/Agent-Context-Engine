"""Owned personal projects: one bounded, atomically versioned directory per owner."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any
from uuid import uuid4

from pydantic import AwareDatetime, Field
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError

from agent_context.contracts import (
    PROJECT_TASK_ID,
    Contract,
    Permission,
    Principal,
    utcnow,
)
from agent_context.task_state import TaskStateService
from agent_context.events import CapacityExceeded, EventConflict
from agent_context.navigation import (
    ProjectCreate,
    ProjectDirectory,
    ProjectEdit,
    ProjectEntry,
)
from agent_context.privacy import PrivacyControls

MAX_PROJECTS = 64
COLLECTION = "ace_projects_v1"


def normalized_name(value: str) -> str:
    result = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not result or any(unicodedata.category(char) == "Cc" for char in result):
        raise ValueError("invalid project name")
    return result


class StoredProject(ProjectEntry):
    creation_key: str
    creation_digest: str
    delegates: frozenset[str] = frozenset()


class DirectoryState(Contract):
    revision: int = 0
    entries: tuple[StoredProject, ...] = Field(default=(), max_length=MAX_PROJECTS)


class GoalHint(Contract):
    handoff_id: str
    version: int
    goal: str
    status: str = "active"
    expires_at: AwareDatetime | None = None


class ProjectStore:
    def __init__(self, client: AsyncMongoClient[Any], database: str) -> None:
        self.collection = client[database][COLLECTION]
        self.privacy = PrivacyControls(client, database)

    async def ensure_indexes(self) -> None:
        await self.privacy.ensure_indexes()
        await self.collection.create_index(
            [("tenant_id", 1), ("user_id", 1)], unique=True
        )

    @staticmethod
    def key(actor: Principal) -> dict[str, str]:
        return {"tenant_id": actor.tenant_id, "user_id": actor.user_id}

    async def state(self, actor: Principal) -> DirectoryState:
        await self.privacy.require_active(actor.tenant_id, actor.user_id)
        row = await self.collection.find_one(self.key(actor))
        result = (
            DirectoryState.model_validate(
                {key: row[key] for key in ("revision", "entries")}
            )
            if row
            else DirectoryState()
        )
        await self.privacy.require_active(actor.tenant_id, actor.user_id)
        return result

    @staticmethod
    def visible(actor: Principal, entry: StoredProject) -> bool:
        return (
            actor.actor_kind == "user"
            or actor.actor_id in entry.delegates
            or entry.project_id in actor.projects
        )

    async def authorize(self, actor: Principal) -> Principal:
        state = await self.state(actor)
        return actor.model_copy(
            update={
                "projects": actor.projects
                | frozenset(
                    entry.project_id
                    for entry in state.entries
                    if self.visible(actor, entry)
                )
            }
        )

    async def directory(self, actor: Principal) -> ProjectDirectory:
        actor.require(Permission.VIEW)
        state = await self.state(actor)
        entries = {
            identifier: ProjectEntry(
                project_id=identifier,
                title=identifier.replace("-", " ").replace("_", " ").capitalize(),
            )
            for identifier in actor.projects
        }
        for entry in state.entries:
            if self.visible(actor, entry):
                entries[entry.project_id] = ProjectEntry.model_validate(
                    entry.model_dump(include=set(ProjectEntry.model_fields))
                )
        # Existing configured projects can have generic labels (alpha/beta).
        # Read only current approved goal hints, never replay raw transcripts or
        # retrieve revoked task content as routing metadata.
        identifiers = {
            TaskStateService.identifier(actor, identifier, PROJECT_TASK_ID): identifier
            for identifier in entries
        }
        privacy = await self.privacy.require_active(actor.tenant_id, actor.user_id)
        blocked = set(privacy.blocked_item_ids)
        cursor = self.collection.database["ace_handoffs_v1"].aggregate(
            [
                {
                    "$match": {
                        **self.key(actor),
                        "handoff_id": {"$in": list(identifiers)},
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "handoff_id": 1,
                        "version": 1,
                        "last": {"$arrayElemAt": ["$revisions", -1]},
                    }
                },
                {
                    "$project": {
                        "handoff_id": 1,
                        "version": 1,
                        "goal": "$last.artifact.content.goal",
                        "status": "$last.artifact.content.status",
                        "expires_at": "$last.artifact.content.expires_at",
                    }
                },
            ]
        )
        async for row in await cursor:
            hint = GoalHint.model_validate(row)
            if (
                hint.status == "active"
                and (hint.expires_at is None or hint.expires_at > utcnow())
                and f"{hint.handoff_id}:{hint.version}" not in blocked
            ):
                identifier = identifiers[hint.handoff_id]
                entries[identifier] = entries[identifier].model_copy(
                    update={"task_goal": hint.goal}
                )
        current_privacy = await self.privacy.require_active(
            actor.tenant_id, actor.user_id
        )
        if current_privacy.revision != privacy.revision:
            raise EventConflict("privacy changed while reading project hints; refresh")
        return ProjectDirectory(
            projects=tuple(
                sorted(
                    entries.values(),
                    key=lambda entry: (entry.title.casefold(), entry.project_id),
                )
            ),
            permissions=actor.permissions,
            revision=state.revision,
        )

    async def write(
        self,
        actor: Principal,
        previous: DirectoryState,
        entries: tuple[StoredProject, ...],
    ) -> None:
        await self.privacy.require_active(actor.tenant_id, actor.user_id)
        value = DirectoryState(revision=previous.revision + 1, entries=entries)
        try:
            result = await self.collection.update_one(
                {**self.key(actor), "revision": previous.revision},
                {"$set": value.model_dump(mode="json")},
                upsert=previous.revision == 0,
            )
        except DuplicateKeyError as error:
            raise EventConflict(
                "project directory changed; refresh before resolving"
            ) from error
        if not result.modified_count and result.upserted_id is None:
            raise EventConflict("project directory changed; refresh before resolving")
        try:
            await self.privacy.require_active(actor.tenant_id, actor.user_id)
        except PermissionError:
            await self.collection.delete_one(self.key(actor))
            raise

    @staticmethod
    def user(actor: Principal, permission: Permission) -> None:
        actor.require(permission)
        actor.require(Permission.VIEW)
        if actor.actor_kind != "user":
            raise PermissionError("only the owner can create or edit personal projects")

    @staticmethod
    def assert_names(
        entries: tuple[StoredProject, ...],
        names: tuple[str, ...],
        *,
        exclude: str | None = None,
        configured: tuple[ProjectEntry, ...] = (),
    ) -> None:
        keys = {normalized_name(name) for name in names}
        if any(len(name) > 120 for name in names):
            raise ValueError("project aliases must be at most 120 characters")
        if len(keys) != len(names):
            raise ValueError("project aliases must be distinct")
        for entry in (*entries, *configured):
            if entry.project_id != exclude and keys & {
                normalized_name(name)
                for name in (entry.title, *entry.aliases, entry.project_id)
            }:
                raise EventConflict(
                    "project name already exists; select it or use a distinct name"
                )

    async def create(
        self, actor: Principal, body: ProjectCreate, *, personal: bool = False
    ) -> ProjectEntry:
        self.user(actor, Permission.ASSERT)
        if not personal and body.idempotency_key.startswith("ace-"):
            raise ValueError("reserved project creation key")
        if not personal and normalized_name(body.title) == "personal":
            raise ValueError("Personal is reserved for nonproject conversations")
        if normalized_name(body.title) != normalized_name(body.name_quote):
            raise ValueError("project title must preserve the quoted name")
        state = await self.state(actor)
        digest = hashlib.sha256(
            json.dumps(
                body.model_dump(mode="json", exclude={"expected_revision"}),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        for entry in state.entries:
            if entry.creation_key == body.idempotency_key:
                if entry.creation_digest != digest:
                    raise EventConflict(
                        "project creation key reused for different input"
                    )
                return ProjectEntry.model_validate(
                    entry.model_dump(include=set(ProjectEntry.model_fields))
                )
        if state.revision != body.expected_revision:
            raise EventConflict("project directory changed; refresh before resolving")
        if len(state.entries) >= MAX_PROJECTS:
            raise CapacityExceeded("personal project directory is full")
        directory = await self.directory(actor)
        configured = tuple(entry for entry in directory.projects if not entry.managed)
        self.assert_names(state.entries, (body.title,), configured=configured)
        entry = StoredProject(
            project_id="project-" + uuid4().hex,
            title=body.title.strip(),
            description=body.description,
            managed=True,
            kind="personal" if personal else "project",
            creation_key=body.idempotency_key,
            creation_digest=digest,
            delegates=frozenset({body.delegate_agent_id}),
        )
        try:
            await self.write(actor, state, (*state.entries, entry))
        except EventConflict:
            latest = await self.state(actor)
            replay = next(
                (
                    item
                    for item in latest.entries
                    if item.creation_key == body.idempotency_key
                    and item.creation_digest == digest
                ),
                None,
            )
            if replay is None:
                raise
            entry = replay
        return ProjectEntry.model_validate(
            entry.model_dump(include=set(ProjectEntry.model_fields))
        )

    async def personal(self, actor: Principal, delegate: str) -> ProjectEntry:
        self.user(actor, Permission.ASSERT)
        for _ in range(3):
            state = await self.state(actor)
            existing = next(
                (entry for entry in state.entries if entry.kind == "personal"), None
            )
            if existing:
                if delegate not in existing.delegates:
                    updated = existing.model_copy(
                        update={
                            "delegates": existing.delegates | {delegate},
                            "version": existing.version + 1,
                        }
                    )
                    try:
                        await self.write(
                            actor,
                            state,
                            tuple(
                                updated
                                if item.project_id == existing.project_id
                                else item
                                for item in state.entries
                            ),
                        )
                    except EventConflict:
                        continue
                    existing = updated
                return ProjectEntry.model_validate(
                    existing.model_dump(include=set(ProjectEntry.model_fields))
                )
            try:
                return await self.create(
                    actor,
                    ProjectCreate(
                        title="Personal",
                        source_text="Personal",
                        name_quote="Personal",
                        idempotency_key="ace-personal",
                        expected_revision=state.revision,
                        delegate_agent_id=delegate,
                    ),
                    personal=True,
                )
            except EventConflict:
                continue
        raise EventConflict("project directory changed; retry personal-space selection")

    async def edit(
        self, actor: Principal, identifier: str, body: ProjectEdit
    ) -> ProjectEntry:
        self.user(actor, Permission.CORRECT)
        state = await self.state(actor)
        existing = next(
            (entry for entry in state.entries if entry.project_id == identifier), None
        )
        adopting = existing is None
        if not existing:
            if identifier not in actor.projects:
                raise LookupError("owned project not found")
            if len(state.entries) >= MAX_PROJECTS:
                raise CapacityExceeded("personal project directory is full")
            existing = StoredProject(
                project_id=identifier,
                title=identifier.replace("-", " ").replace("_", " ").capitalize(),
                managed=True,
                creation_key="ace-configured-"
                + hashlib.sha256(identifier.encode()).hexdigest(),
                creation_digest="configured-grant",
            )
        if existing.kind == "personal":
            raise ValueError("personal space cannot be renamed")
        if existing.version != body.expected_version:
            raise EventConflict("project metadata changed; refresh before editing")
        aliases = body.aliases if body.aliases is not None else existing.aliases
        if normalized_name(existing.title) != normalized_name(
            body.title
        ) and normalized_name(existing.title) not in {
            normalized_name(name) for name in aliases
        }:
            aliases = (*aliases, existing.title)
        aliases = tuple(
            name
            for name in aliases
            if normalized_name(name) != normalized_name(body.title)
        )
        if any(normalized_name(name) == "personal" for name in (body.title, *aliases)):
            raise ValueError("Personal is reserved for nonproject conversations")
        if (
            not adopting
            and body.title.strip() == existing.title
            and aliases == existing.aliases
        ):
            return ProjectEntry.model_validate(
                existing.model_dump(include=set(ProjectEntry.model_fields))
            )
        if len(aliases) > 8:
            raise CapacityExceeded(
                "project alias limit reached; explicitly review aliases"
            )
        directory = await self.directory(actor)
        self.assert_names(
            state.entries,
            (body.title, *aliases),
            exclude=identifier,
            configured=tuple(
                entry for entry in directory.projects if not entry.managed
            ),
        )
        updated = existing.model_copy(
            update={
                "title": body.title.strip(),
                "aliases": aliases,
                "version": existing.version + 1,
            }
        )
        await self.write(
            actor,
            state,
            (*state.entries, updated)
            if adopting
            else tuple(
                updated if entry.project_id == identifier else entry
                for entry in state.entries
            ),
        )
        return ProjectEntry.model_validate(
            updated.model_dump(include=set(ProjectEntry.model_fields))
        )
