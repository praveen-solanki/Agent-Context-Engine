"""Owned evidence, immediate revocation, export and resumable primary-data erasure."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, LiteralString

from neo4j import AsyncDriver, RoutingControl, READ_ACCESS
from pydantic import Field
from pymongo import AsyncMongoClient

from agent_context.bridge import scoped_id
from agent_context.contracts import Contract, Permission, Principal, utcnow
from agent_context.events import EventConflict
from agent_context.privacy import PrivacyControls
from context_graph.domain.conversation import SourceSpan

_OWNED: LiteralString = """
c.subject_user_id = $user_id AND (
 (c.scope_type='USER' AND c.scope_id=$user_id)
 OR (c.scope_type='PROJECT' AND c.scope_id IN $projects)
 OR (c.scope_type='SESSION' AND EXISTS {
  MATCH (:User {user_id:$user_id})-[:PARTICIPATED_IN]->(s:Session)
  WHERE s.session_id=c.scope_id }))
"""
_ITEM: LiteralString = (
    "MATCH (c:Context {context_id:$item_id}) WHERE "
    + _OWNED
    + " RETURN c.fingerprint AS fingerprint"
)
_EVIDENCE: LiteralString = (
    "MATCH (c:Context {context_id:$item_id}) WHERE "
    + _OWNED
    + """
MATCH (c)-[:SUPPORTED_BY]->(e:Episode)
WHERE EXISTS {
 MATCH (:User {user_id:$user_id})-[:PARTICIPATED_IN]->(:Session)-[:CONTAINS]->(e)
}
RETURN e.episode_id AS episode_id,left(e.text,4000) AS text,
 e.session_id AS session_id,e.timestamp AS observed_at,
 e.spans AS source_spans,e.role AS role,e.sender_id AS sender_id,
 e.source_type AS source_type,c.status AS context_status,
 size(e.text)>4000 AS truncated,
 (c.status='active' AND coalesce(c.user_revoked,false)=false
  AND (c.valid_from IS NULL OR c.valid_from<=$now)
  AND (c.valid_until IS NULL OR c.valid_until>$now)) AS usable_as_current_context
 ORDER BY e.sequence,e.episode_id LIMIT 8
"""
)
_EXPORT: LiteralString = (
    "MATCH (c:Context) WHERE "
    + _OWNED
    + " RETURN properties(c) AS data ORDER BY c.context_id"
)
_REVOKE: LiteralString = (
    "MATCH (c:Context {context_id:$item_id}) WHERE "
    + _OWNED
    + """
AND c.fingerprint=$fingerprint
SET c.status='revoked',c.user_revoked=true,c.revoked_at=coalesce(c.revoked_at,$now)
RETURN c.context_id AS item_id
"""
)


class RevocationInput(Contract):
    item_id: str = Field(min_length=1, max_length=256)
    expected_fingerprint: str = Field(min_length=1, max_length=256)


class GovernanceService:
    def __init__(
        self,
        client: AsyncMongoClient[Any],
        database: str,
        driver: AsyncDriver,
        *,
        graph_database: str,
    ) -> None:
        self.db = client[database]
        self.driver, self.graph_database = driver, graph_database
        self.privacy = PrivacyControls(client, database)

    async def ensure_indexes(self) -> None:
        await self.privacy.ensure_indexes()
        await self.db["ace_erasure_v1"].create_index(
            [("tenant_id", 1), ("user_id", 1)], unique=True
        )

    @staticmethod
    def _parameters(principal: Principal) -> dict[str, Any]:
        return {
            "user_id": scoped_id(principal.tenant_id, principal.user_id),
            "projects": [scoped_id(principal.tenant_id, p) for p in principal.projects],
        }

    async def evidence(
        self, principal: Principal, item_id: str
    ) -> list[dict[str, Any]]:
        principal.require(Permission.VIEW)
        state = await self.privacy.require_active(principal.tenant_id, principal.user_id)
        records, _, _ = await self.driver.execute_query(
            _EVIDENCE,
            **self._parameters(principal),
            item_id=item_id,
            now=utcnow(),
            database_=self.graph_database,
            routing_=RoutingControl.READ,
        )
        if not records:
            raise LookupError("owned evidence not found")
        excerpts: list[dict[str, Any]] = []
        for record in records:
            excerpt = dict(record)
            stored = excerpt.pop("source_spans")
            spans: list[dict[str, Any]] = []
            remaining = 4000
            for raw in json.loads(stored) if stored else []:
                if remaining <= 0 or len(spans) == 32:
                    excerpt["truncated"] = True
                    break
                span = SourceSpan.model_validate(raw)
                text = span.text[:remaining]
                spans.append(
                    {
                        "message_id": span.message_id,
                        "sequence": span.sequence,
                        "role": span.role.value,
                        "sender_id": span.sender_id,
                        "source_type": span.source_type.value,
                        "source_trust": span.source_type.trust.value,
                        "char_start": span.char_start,
                        "char_end": span.char_start + len(text),
                        "text": text,
                    }
                )
                remaining -= len(text)
            excerpt["spans"] = spans
            excerpt["observed_at"] = (
                str(record["observed_at"])
                if record["observed_at"] is not None
                else None
            )
            excerpt["usable_as_current_context"] = bool(
                excerpt["usable_as_current_context"] and item_id not in state.blocked_item_ids
            )
            # Inspection of one's revoked source is intentional, but it must
            # never look like an active instruction or bypass current search.
            excerpts.append(excerpt)
        current = await self.privacy.require_active(principal.tenant_id, principal.user_id)
        if item_id in current.blocked_item_ids:
            for excerpt in excerpts:
                excerpt["usable_as_current_context"] = False
        return excerpts

    async def revoke(
        self, principal: Principal, request: RevocationInput
    ) -> dict[str, object]:
        principal.require(Permission.CORRECT)
        parameters = self._parameters(principal)
        records, _, _ = await self.driver.execute_query(
            _ITEM,
            **parameters,
            item_id=request.item_id,
            database_=self.graph_database,
            routing_=RoutingControl.READ,
        )
        if not records:
            raise LookupError("context item not found")
        if records[0]["fingerprint"] != request.expected_fingerprint:
            raise EventConflict("context version precondition failed")
        # Persist the visibility fence first. Graph retries/replay cannot undo
        # it by changing the same node's lifecycle status back to active.
        state = await self.privacy.block(principal, request.item_id)
        await self.driver.execute_query(
            _REVOKE,
            **parameters,
            item_id=request.item_id,
            fingerprint=request.expected_fingerprint,
            now=utcnow(),
            database_=self.graph_database,
        )
        return {
            "item_id": request.item_id,
            "state": "revoked",
            "privacy_revision": state.revision,
        }

    async def export(self, principal: Principal) -> AsyncIterator[str]:
        principal.require(Permission.VIEW)
        await self.privacy.require_active(principal.tenant_id, principal.user_id)
        async with self.driver.session(
            database=self.graph_database, default_access_mode=READ_ACCESS
        ) as session:
            result = await session.run(_EXPORT, self._parameters(principal))
            async for record in result:
                await self.privacy.require_active(
                    principal.tenant_id, principal.user_id
                )
                yield (
                    json.dumps({"kind": "context", "data": record["data"]}, default=str)
                    + "\n"
                )
        owned = {"tenant_id": principal.tenant_id, "user_id": principal.user_id}
        collections = ("ace_handoffs_v1", "ace_artifacts_v1")
        for name in collections:
            async for document in (
                self.db[name]
                .find(
                    {**owned, "project_id": {"$in": list(principal.projects)}},
                    {"_id": 0},
                )
                .batch_size(1)
            ):
                await self.privacy.require_active(
                    principal.tenant_id, principal.user_id
                )
                yield json.dumps({"kind": name, "data": document}, default=str) + "\n"
        async for document in (
            self.db["ace_event_streams_v1"]
            .find(
                {
                    "tenant_id": principal.tenant_id,
                    "data.user_id": principal.user_id,
                    "data.project_id": {"$in": [None, *principal.projects]},
                },
                {"_id": 0, "lease_token": 0},
            )
            .batch_size(1)
        ):
            await self.privacy.require_active(principal.tenant_id, principal.user_id)
            yield (
                json.dumps({"kind": "events", "data": document["data"]}, default=str)
                + "\n"
            )

    async def request_erasure(self, principal: Principal) -> dict[str, object]:
        principal.require(Permission.DELETE)
        await self.privacy.quarantine(principal)
        key = {"tenant_id": principal.tenant_id, "user_id": principal.user_id}
        await self.db["ace_erasure_v1"].update_one(
            key,
            {"$setOnInsert": {"state": "quarantined", "requested_at": utcnow()}},
            upsert=True,
        )
        return await self.erasure_status(principal)

    async def erasure_status(self, principal: Principal) -> dict[str, object]:
        principal.require(Permission.DELETE)
        document = await self.db["ace_erasure_v1"].find_one(
            {"tenant_id": principal.tenant_id, "user_id": principal.user_id}, {"_id": 0}
        )
        if document is None:
            raise LookupError("erasure request not found")
        return {k: str(v) if k.endswith("_at") else v for k, v in document.items()}

    async def purge(self, principal: Principal) -> dict[str, object]:
        """Idempotent maintenance: quarantine + expired event leases required.

        Only primary application content is deleted. Minimal tombstones/job
        metadata remain; backups and already downloaded exports are external
        responsibilities and are explicitly reported rather than called erased.
        """
        principal.require(Permission.DELETE)
        state = await self.privacy.state(principal.tenant_id, principal.user_id)
        if not state.erased:
            raise ValueError("quarantine must precede erasure")
        owned = {"tenant_id": principal.tenant_id, "user_id": principal.user_id}
        leased = await self.db["ace_event_streams_v1"].find_one(
            {
                "tenant_id": principal.tenant_id,
                "data.user_id": principal.user_id,
                "lease_until": {"$gt": utcnow()},
            },
            {"_id": 1},
        )
        if leased is not None:
            return {"state": "waiting_for_inflight_work"}
        uid = scoped_id(principal.tenant_id, principal.user_id)
        # Remove only this principal's canonical contexts and their unshared
        # concept vectors; never clear a whole graph or another user's nodes.
        while True:
            rows, _, _ = await self.driver.execute_query(
                """
MATCH (c:Context)
WHERE c.subject_user_id=$user_id OR
 (c.subject_user_id='' AND c.source_actor=$user_id AND NOT EXISTS {
   MATCH (c)-[r:SUPPORTED_BY]->() WHERE r.actor_id<>$user_id })
WITH c LIMIT 128
OPTIONAL MATCH (c)-[:INSTANTIATES]->(m:MemoryConcept)
RETURN c.context_id AS context_id,m.concept_id AS concept_id
""",
                user_id=uid,
                database_=self.graph_database,
            )
            if not rows:
                break
            ids = [row["context_id"] for row in rows]
            concepts = [row["concept_id"] for row in rows if row["concept_id"]]
            await self.driver.execute_query(
                "MATCH(c:Context) WHERE c.context_id IN $ids DETACH DELETE c",
                ids=ids,
                database_=self.graph_database,
            )
            await self.driver.execute_query(
                """
MATCH(m:MemoryConcept) WHERE m.concept_id IN $ids AND NOT EXISTS {
 MATCH(:Context)-[:INSTANTIATES]->(m) } DETACH DELETE m
""",
                ids=concepts,
                database_=self.graph_database,
            )
        await self.driver.execute_query(
            """
MATCH(c:Context {subject_user_id:'',source_actor:$user_id})-[r:SUPPORTED_BY]->(e:Episode)
WHERE r.actor_id<>$user_id
WITH c,head(collect({actor:r.actor_id,episode:e.episode_id,session:e.session_id})) AS remaining
SET c.source_actor=remaining.actor,c.source_episode_id=remaining.episode,c.source_session_id=remaining.session
""",
            user_id=uid,
            database_=self.graph_database,
        )
        while True:
            rows, _, _ = await self.driver.execute_query(
                """
MATCH (:User {user_id:$user_id})-[:PARTICIPATED_IN]->(s:Session)
RETURN s.session_id AS session_id LIMIT 128
""",
                user_id=uid,
                database_=self.graph_database,
            )
            ids = [record["session_id"] for record in rows]
            if not ids:
                break
            for name in (
                "session_segmentations",
                "session_checkpoints",
                "extraction_batches",
            ):
                await self.db[name].delete_many({"session_id": {"$in": ids}})
            await self.driver.execute_query(
                """
MATCH (s:Session) WHERE s.session_id IN $ids
OPTIONAL MATCH (s)-[:CONTAINS]->(e:Episode)
WITH collect(DISTINCT s) AS sessions,collect(DISTINCT e) AS episodes
FOREACH(e IN episodes | DETACH DELETE e)
FOREACH(s IN sessions | DETACH DELETE s)
""",
                ids=ids,
                database_=self.graph_database,
            )
        await self.driver.execute_query(
            "MATCH (u:User {user_id:$user_id}) DETACH DELETE u",
            user_id=uid,
            database_=self.graph_database,
        )
        await self.db["ace_event_streams_v1"].delete_many(
            {"tenant_id": principal.tenant_id, "data.user_id": principal.user_id}
        )
        for name in ("ace_handoffs_v1", "ace_artifacts_v1", "ace_assemblies_v1"):
            await self.db[name].delete_many(owned)
        await self.db["ace_erasure_v1"].update_one(
            owned,
            {
                "$set": {
                    "state": "primary_purged",
                    "finished_at": utcnow(),
                    "external_backups": "operator_retention_policy_required",
                }
            },
        )
        return await self.erasure_status(principal)
