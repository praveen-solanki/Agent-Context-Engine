"""Version-one, metadata-only session-scope backfill from the trusted outbox.

Dry-run by default. Plans contain identities/hashes, never conversation text.
Apply/rollback use compare-and-set and are safe to retry after partial progress.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, LiteralString
from uuid import uuid4

from neo4j import AsyncDriver, AsyncGraphDatabase, RoutingControl
from pydantic import Field
from pymongo import AsyncMongoClient

from agent_context.bridge import scoped_id
from agent_context.contracts import Contract, Identifier
from agent_context.events import EventConflict
from agent_context.privacy import PrivacyControls
from agent_context.runtime import RuntimeSettings
from context_graph.config import Settings


class BindingState(Contract):
    bound: bool | None = None
    project_id: str | None = None
    version: int | None = None
    migration: str | None = None


class BindingChange(Contract):
    external_session_id: Identifier
    session_id: str
    user_id: str
    project_id: str | None = None
    before: BindingState


class BindingPlan(Contract):
    schema_version: int = Field(default=1, ge=1, le=1)
    migration_id: Identifier = Field(default_factory=lambda: uuid4().hex)
    tenant_id: Identifier
    user_id: Identifier
    changes: tuple[BindingChange, ...] = Field(default=(), max_length=4096)


_READ: LiteralString = """
MATCH(s:Session {session_id:$session_id})
RETURN s.user_id AS user_id,s.ace_scope_bound AS bound,
 s.ace_project_id AS project_id,s.ace_scope_binding_version AS version,
 s.ace_scope_binding_migration AS migration
"""
# Acquire and retain the node write lock before reading CAS fields. A WHERE
# followed by SET alone can compare stale values while waiting for that lock.
_WRITE: LiteralString = """
MATCH(s:Session {session_id:$session_id})
SET s.ace_scope_binding_lock=true
REMOVE s.ace_scope_binding_lock
WITH s
WHERE s.user_id=$user_id
 AND (s.ace_scope_bound=$before_bound OR (s.ace_scope_bound IS NULL AND $before_bound IS NULL))
 AND (s.ace_project_id=$before_project OR (s.ace_project_id IS NULL AND $before_project IS NULL))
 AND (s.ace_scope_binding_version=$before_version OR (s.ace_scope_binding_version IS NULL AND $before_version IS NULL))
 AND (s.ace_scope_binding_migration=$before_migration OR (s.ace_scope_binding_migration IS NULL AND $before_migration IS NULL))
SET s.ace_scope_bound=$bound,s.ace_project_id=$project_id,
 s.ace_scope_binding_version=$version,s.ace_scope_binding_migration=$migration
RETURN s.session_id AS session_id
"""


async def plan_bindings(
    mongo: AsyncMongoClient[Any],
    database: str,
    driver: AsyncDriver,
    *,
    graph_database: str,
    tenant_id: str,
    user_id: str,
) -> BindingPlan:
    await PrivacyControls(mongo, database).require_active(tenant_id, user_id)
    changes: list[BindingChange] = []
    scanned = 0
    async for record in (
        mongo[database]["ace_event_streams_v1"]
        .find(
            {"tenant_id": tenant_id, "data.user_id": user_id},
            {"session_id": 1, "data.project_id": 1},
        )
        .limit(4097)
    ):
        scanned += 1
        if scanned > 4096:
            raise ValueError("too many streams for one bounded binding plan")
        sid, uid = (
            scoped_id(tenant_id, record["session_id"]),
            scoped_id(tenant_id, user_id),
        )
        project = record["data"].get("project_id")
        pid = scoped_id(tenant_id, project) if project else None
        rows, _, _ = await driver.execute_query(
            _READ,
            session_id=sid,
            database_=graph_database,
            routing_=RoutingControl.READ,
        )
        if not rows:
            continue  # No graph projection yet; normal ingestion will bind it.
        if rows[0]["user_id"] != uid:
            raise EventConflict("session owner does not match trusted stream")
        before = BindingState.model_validate(
            {key: rows[0][key] for key in BindingState.model_fields}
        )
        if before.bound:
            if before.project_id != pid:
                raise EventConflict("graph binding conflicts with trusted stream")
            continue
        changes.append(
            BindingChange(
                external_session_id=record["session_id"],
                session_id=sid,
                user_id=uid,
                project_id=pid,
                before=before,
            )
        )
    if len(changes) > 4096:
        raise ValueError("binding plan exceeds the bounded migration window")
    return BindingPlan(tenant_id=tenant_id, user_id=user_id, changes=tuple(changes))


async def apply_bindings(
    plan: BindingPlan,
    mongo: AsyncMongoClient[Any],
    database: str,
    driver: AsyncDriver,
    *,
    graph_database: str,
    rollback: bool = False,
) -> int:
    applied = 0
    privacy = PrivacyControls(mongo, database)
    for change in plan.changes:
        await privacy.require_active(plan.tenant_id, plan.user_id)
        source = await mongo[database]["ace_event_streams_v1"].find_one(
            {
                "tenant_id": plan.tenant_id,
                "data.user_id": plan.user_id,
                "session_id": change.external_session_id,
            },
            {"data.project_id": 1},
        )
        project = source["data"].get("project_id") if source else None
        pid = scoped_id(plan.tenant_id, project) if project else None
        if (
            source is None
            or pid != change.project_id
            or scoped_id(plan.tenant_id, change.external_session_id)
            != change.session_id
            or scoped_id(plan.tenant_id, plan.user_id) != change.user_id
        ):
            raise EventConflict("migration source identity changed")
        after = BindingState(
            bound=True, project_id=pid, version=1, migration=plan.migration_id
        )
        expected, target = (
            (after, change.before) if rollback else (change.before, after)
        )
        rows, _, _ = await driver.execute_query(
            _READ,
            session_id=change.session_id,
            database_=graph_database,
            routing_=RoutingControl.READ,
        )
        if not rows or rows[0]["user_id"] != change.user_id:
            raise EventConflict("migration session disappeared or changed owner")
        current = BindingState.model_validate(
            {key: rows[0][key] for key in BindingState.model_fields}
        )
        if current == target or (
            not rollback and current.bound and current.project_id == pid
        ):
            continue
        if current != expected:
            raise EventConflict(
                "migration session changed; re-plan instead of overwriting"
            )
        updated, _, _ = await driver.execute_query(
            _WRITE,
            session_id=change.session_id,
            user_id=change.user_id,
            before_bound=expected.bound,
            before_project=expected.project_id,
            before_version=expected.version,
            before_migration=expected.migration,
            **target.model_dump(),
            database_=graph_database,
        )
        if not updated:
            raise EventConflict("session binding changed during migration")
        applied += 1
    return applied


async def _main(mode: str, path: Path) -> None:
    runtime, settings = RuntimeSettings(), Settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.user, settings.neo4j.password.get_secret_value()),
    )
    async with AsyncMongoClient[dict[str, Any]](
        settings.mongo.uri, tz_aware=True
    ) as mongo:
        try:
            if mode == "plan":
                plan = await plan_bindings(
                    mongo,
                    settings.mongo.database,
                    driver,
                    graph_database=settings.neo4j.database,
                    tenant_id=runtime.tenant_id,
                    user_id=runtime.user_id,
                )
                path.write_text(plan.model_dump_json(indent=2) + "\n")
                path.chmod(0o600)
                print(
                    json.dumps(
                        {
                            "plan_file": str(path),
                            "changes": len(plan.changes),
                            "applied": False,
                        }
                    )
                )
            else:
                plan = BindingPlan.model_validate_json(path.read_text())
                if (plan.tenant_id, plan.user_id) != (
                    runtime.tenant_id,
                    runtime.user_id,
                ):
                    raise PermissionError("plan belongs to another trust partition")
                count = await apply_bindings(
                    plan,
                    mongo,
                    settings.mongo.database,
                    driver,
                    graph_database=settings.neo4j.database,
                    rollback=mode == "rollback",
                )
                print(json.dumps({"mode": mode, "changed_sessions": count}))
        finally:
            await driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", nargs="?", choices=("plan", "apply", "rollback"), default="plan"
    )
    parser.add_argument(
        "--plan-file", type=Path, default=Path("/tmp/ace-session-bindings-v1.json")
    )
    args = parser.parse_args()
    asyncio.run(_main(args.mode, args.plan_file))
