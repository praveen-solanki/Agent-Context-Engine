"""Scoped adapter over the original Neo4j representation; no graph API leaks."""

from __future__ import annotations

import json
import math
import re
from typing import Any, LiteralString

from neo4j import AsyncDriver, RoutingControl

from agent_context.assembly import ContextQuery, ContextItem, SearchRequest, lexical_terms
from agent_context.bridge import scoped_id
from agent_context.contracts import Permission, Principal, utcnow
from agent_context.privacy import PrivacyControls
from context_graph.domain.enums import Cardinality, ContextType, ScopeType
from context_graph.graph.mapping import context_from_node
from context_graph.providers.base import EmbeddingProvider

_QUERY: LiteralString = """
MATCH (c:Context {subject_user_id: $user_id})
WHERE (c.status = 'active' OR
       ($historical AND c.status = 'superseded' AND c.superseded_at > $now))
  AND (NOT $historical OR c.observed_at <= $now)
  AND (c.superseded_at IS NULL OR c.superseded_at > $now)
  AND (c.valid_from IS NULL OR c.valid_from <= $now)
  AND (c.valid_until IS NULL OR c.valid_until > $now)
  AND NOT c.context_id IN $blocked_ids
  AND coalesce(c.user_revoked,false)=false
  AND ((c.scope_type = 'USER' AND c.scope_id = $user_id)
       OR (c.scope_type = 'SESSION' AND c.scope_id = $session_id AND EXISTS {
          MATCH (s:Session {session_id:$session_id,user_id:$user_id})
          WHERE s.ace_scope_bound=true
            AND (s.ace_project_id IS NULL OR s.ace_project_id=$project_id) })
       OR (c.scope_type = 'PROJECT' AND c.scope_id = $project_id))
WITH c, toLower(replace(coalesce(c.concept_key,''),'_',' ') + ' ' +
                coalesce(toString(c.value),'')) AS searchable
WITH c, reduce(relevance = 0.0, pattern IN $query_patterns |
               relevance + CASE WHEN searchable =~ pattern THEN 1.0 ELSE 0.0 END)
               / CASE WHEN size($query_patterns) = 0 THEN 1 ELSE size($query_patterns) END AS lexical,
     CASE WHEN $query_vector IS NOT NULL AND size(c.embedding) = size($query_vector)
               AND c.embedding_model = $embedding_model
          THEN vector.similarity.cosine(c.embedding, $query_vector) ELSE 0.0 END AS semantic
WITH c, lexical, CASE WHEN semantic > 0.5 THEN 2.0 * semantic - 1.0 ELSE 0.0 END AS semantic
ORDER BY CASE WHEN lexical > semantic THEN lexical ELSE semantic END DESC,
                CASE WHEN c.context_type IN ['Constraint','Preference','WorkingStyle']
                    THEN 0 ELSE 1 END, c.observed_at DESC, c.context_id
LIMIT $limit
OPTIONAL MATCH (source_session:Session {session_id:c.scope_id,user_id:$user_id})
WHERE c.scope_type='SESSION'
RETURN properties(c) AS context, semantic, source_session.ace_project_id AS scope_project,
c.cardinality = 'single' AND EXISTS {
 MATCH (other:Context {subject_user_id:$user_id, scope_type:c.scope_type,
                       scope_id:c.scope_id, concept_key:c.concept_key})
 WHERE other.context_id <> c.context_id
   AND (other.status='active' OR ($historical AND other.status='superseded'
                                AND other.superseded_at > $now))
   AND (NOT $historical OR other.observed_at <= $now)
   AND (other.superseded_at IS NULL OR other.superseded_at > $now)
   AND (other.valid_from IS NULL OR other.valid_from <= $now)
   AND (other.valid_until IS NULL OR other.valid_until > $now)
   AND coalesce(other.user_revoked,false)=false
   AND NOT other.context_id IN $blocked_ids
   AND coalesce(other.value_key,toString(other.value)) <> coalesce(c.value_key,toString(c.value))
} AS unresolved_conflict
"""


class Neo4jCandidateSource:
    """Initial private-context source for a physically isolated tenant database.

    Do not reuse this driver/database for another tenant: the old concept
    resolution pipeline is not tenant-partitioned. IDs alone cannot fix that.
    Shared/team/task scope support requires a trusted grant adapter and is
    intentionally fail-closed until that adapter exists.
    """

    def __init__(
        self,
        driver: AsyncDriver,
        *,
        database: str,
        tenant_id: str,
        privacy: PrivacyControls | None = None,
        embeddings: EmbeddingProvider | None = None,
    ) -> None:
        self.driver, self.database, self.tenant_id = driver, database, tenant_id
        self.privacy = privacy
        self.embeddings = embeddings

    async def fetch(
        self, principal: Principal, request: ContextQuery, *, limit: int
    ) -> tuple[ContextItem, ...]:
        principal.require(Permission.VIEW, request.project_id)
        if principal.tenant_id != self.tenant_id:
            raise PermissionError("database is bound to another tenant")
        if not 1 <= limit <= 4096:
            raise ValueError("candidate limit is out of range")
        state = (
            await self.privacy.require_active(principal.tenant_id, principal.user_id)
            if self.privacy
            else None
        )
        historical = isinstance(request, SearchRequest) and request.as_of is not None
        at = (
            request.as_of
            if isinstance(request, SearchRequest) and request.as_of
            else utcnow()
        )
        if historical and at > utcnow():
            raise ValueError("historical search cannot request a future instant")
        vector: list[float] | None = None
        if self.embeddings is not None and request.query.strip():
            vectors = await self.embeddings.embed([request.query])
            if (
                len(vectors) != 1
                or len(vectors[0]) != self.embeddings.dimension
                or not all(math.isfinite(value) for value in vectors[0])
                or not any(vectors[0])
            ):
                raise RuntimeError("invalid query embedding")
            vector = vectors[0]
        records, _, _ = await self.driver.execute_query(
            _QUERY,
            user_id=scoped_id(self.tenant_id, principal.user_id),
            session_id=scoped_id(self.tenant_id, request.session_id),
            project_id=scoped_id(self.tenant_id, request.project_id)
            if request.project_id
            else None,
            now=at,
            historical=historical,
            query_vector=vector,
            embedding_model=self.embeddings.model if self.embeddings else None,
            blocked_ids=list(state.blocked_item_ids) if state else [],
            query_patterns=[
                rf"(?s).*\b{re.escape(term)}\b.*"
                for term in sorted(lexical_terms(request.query))
            ],
            limit=limit,
            database_=self.database,
            routing_=RoutingControl.READ,
        )
        items: list[ContextItem] = []
        for record in records:
            properties: dict[str, Any] = dict(record["context"])
            context = context_from_node(properties)
            original_scope = {
                ScopeType.USER: principal.user_id,
                ScopeType.SESSION: request.session_id,
                ScopeType.PROJECT: request.project_id,
            }.get(context.scope_type)
            if original_scope is None:
                raise RuntimeError("unexpected scope returned by private-context query")
            value = (
                context.value
                if isinstance(context.value, str)
                else json.dumps(context.value, sort_keys=True)
            )
            items.append(
                ContextItem(
                    item_id=context.context_id,
                    fingerprint=context.fingerprint,
                    tenant_id=self.tenant_id,
                    user_id=principal.user_id,
                    scope_type=context.scope_type,
                    scope_id=original_scope,
                    project_id=request.project_id if record["scope_project"] is not None else None,
                    canonical_key=context.concept_key,
                    text=f"{context.concept_key}: {value}",
                    value=context.value
                    if isinstance(context.value, (str, float, bool, int))
                    else None,
                    evidence_ids=(context.provenance.source_episode_id,),
                    status=context.status,
                    valid_from=context.valid_from,
                    valid_until=context.valid_until,
                    observed_at=context.observed_at,
                    superseded_at=context.superseded_at,
                    semantic_score=record["semantic"] or 0,
                    unresolved_conflict=bool(record["unresolved_conflict"]),
                    single_valued=context.cardinality == Cardinality.SINGLE,
                    priority=1
                    if context.context_type
                    in (
                        ContextType.CONSTRAINT,
                        ContextType.PREFERENCE,
                        ContextType.WORKING_STYLE,
                    )
                    else 0,
                )
            )
        return tuple(items)
