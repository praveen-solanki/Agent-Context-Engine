"""Scoped adapter over the original Neo4j representation; no graph API leaks."""

from __future__ import annotations

import json
from typing import Any, LiteralString

from neo4j import AsyncDriver, RoutingControl

from agent_context.assembly import AssembleRequest, ContextItem
from agent_context.bridge import scoped_id
from agent_context.contracts import Permission, Principal, utcnow
from agent_context.privacy import PrivacyControls
from context_graph.domain.enums import Cardinality, ContextType, ScopeType
from context_graph.graph.mapping import context_from_node

_QUERY: LiteralString = """
MATCH (c:Context {subject_user_id: $user_id, status: 'active'})
WHERE (c.valid_from IS NULL OR c.valid_from <= $now)
  AND (c.valid_until IS NULL OR c.valid_until > $now)
  AND NOT c.context_id IN $blocked_ids
  AND coalesce(c.user_revoked,false)=false
  AND ((c.scope_type = 'USER' AND c.scope_id = $user_id)
       OR (c.scope_type = 'SESSION' AND c.scope_id = $session_id)
       OR (c.scope_type = 'PROJECT' AND c.scope_id = $project_id))
WITH c ORDER BY CASE WHEN c.context_type IN ['Constraint','Preference','WorkingStyle']
                    THEN 0 ELSE 1 END, c.observed_at DESC, c.context_id
LIMIT $limit
RETURN properties(c) AS context
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
    ) -> None:
        self.driver, self.database, self.tenant_id = driver, database, tenant_id
        self.privacy = privacy

    async def fetch(
        self, principal: Principal, request: AssembleRequest, *, limit: int
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
        records, _, _ = await self.driver.execute_query(
            _QUERY,
            user_id=scoped_id(self.tenant_id, principal.user_id),
            session_id=scoped_id(self.tenant_id, request.session_id),
            project_id=scoped_id(self.tenant_id, request.project_id)
            if request.project_id
            else None,
            now=utcnow(),
            blocked_ids=list(state.blocked_item_ids) if state else [],
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
