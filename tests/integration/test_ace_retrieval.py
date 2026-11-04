"""Real Cypher must filter ownership, scope and lifecycle before projecting data."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from agent_context.assembly import AssembleRequest, ContextAssembler, TokenBudget
from agent_context.assembly import AssemblySettings
from agent_context.bridge import scoped_id
from agent_context.contracts import Principal, utcnow
from agent_context.retrieval import Neo4jCandidateSource
from tests.factories import context_node


async def test_private_query_scope_and_assembly_against_real_neo4j() -> None:
    tenant, user = uuid4().hex, uuid4().hex
    actor = Principal(
        tenant_id=tenant,
        user_id=user,
        actor_id=user,
        projects=frozenset({"allowed-project"}),
    )
    request = AssembleRequest(
        agent_id="agent",
        session_id="session",
        project_id="allowed-project",
        budget=TokenBudget(model_context_tokens=12000),
    )
    driver = AsyncGraphDatabase.driver("bolt://127.0.0.1:7690", auth=None)
    variants = [
        ("mine", {}),
        ("other_user", {"subject_user_id": scoped_id(tenant, "another-user")}),
        ("other_tenant", {"subject_user_id": scoped_id("another-tenant", user)}),
        ("revoked", {"status": "revoked"}),
        ("expired", {"valid_until": utcnow() - timedelta(days=1)}),
        ("future", {"valid_from": utcnow() + timedelta(days=1)}),
        (
            "session",
            {"scope_type": "SESSION", "scope_id": scoped_id(tenant, "session")},
        ),
        (
            "other_session",
            {"scope_type": "SESSION", "scope_id": scoped_id(tenant, "other-session")},
        ),
        (
            "project",
            {"scope_type": "PROJECT", "scope_id": scoped_id(tenant, "allowed-project")},
        ),
        (
            "other_project",
            {"scope_type": "PROJECT", "scope_id": scoped_id(tenant, "other-project")},
        ),
        ("claimed_team", {"scope_type": "TEAM", "scope_id": "claimed-team"}),
    ]
    try:
        for name, overrides in variants:
            properties = {
                **context_node(concept=f"{tenant}_{name}"),
                "ace_test": tenant,
                "subject_user_id": scoped_id(tenant, user),
                "scope_id": scoped_id(tenant, user),
                **overrides,
            }
            await driver.execute_query(
                "CREATE (c:Context) SET c = $properties",
                properties=properties,
                database_="neo4j",
            )
        source = Neo4jCandidateSource(driver, database="neo4j", tenant_id=tenant)
        candidates = await source.fetch(actor, request, limit=32)
        assert {c.item_id for c in candidates} == {
            f"ctx_{tenant}_{name}" for name in ("mine", "session", "project")
        }
        bundle = await ContextAssembler(source).assemble(actor, request)
        assert len(bundle.items) == 3 and bundle.token_count <= request.budget.available
        with pytest.raises(PermissionError):
            await source.fetch(
                actor.model_copy(update={"tenant_id": "other"}), request, limit=32
            )
        with pytest.raises(PermissionError):
            await source.fetch(
                actor,
                request.model_copy(update={"project_id": "other-project"}),
                limit=32,
            )
    finally:
        await driver.execute_query(
            "MATCH (c:Context {ace_test: $tag}) DETACH DELETE c",
            tag=tenant,
            database_="neo4j",
        )
        await driver.close()


async def test_older_relevant_decision_survives_recent_irrelevant_candidate_pressure() -> None:
    tag = uuid4().hex
    actor = Principal(tenant_id=tag, user_id="owner", actor_id="owner", projects=frozenset({"project"}))
    driver = AsyncGraphDatabase.driver("bolt://127.0.0.1:7690", auth=None)
    recent = utcnow()
    properties = [
        {
            **context_node(concept=f"{tag}_noise_{index}", value=f"Unrelated display preference {index}"),
            "ace_test": tag, "subject_user_id": scoped_id(tag, "owner"),
            "scope_id": scoped_id(tag, "owner"), "observed_at": recent,
        }
        for index in range(220)
    ]
    decision_id = f"ctx_{tag}_decision"
    properties.append({
        **context_node(concept=f"{tag}_decision", value="Rollback deployment to the stable release"),
        "context_type": "Decision", "ace_test": tag,
        "subject_user_id": scoped_id(tag, "owner"),
        "scope_type": "PROJECT", "scope_id": scoped_id(tag, "project"),
        "observed_at": recent - timedelta(days=90),
    })
    try:
        await driver.execute_query("UNWIND $rows AS properties CREATE (c:Context) SET c = properties",
                                   rows=properties, database_="neo4j")
        source = Neo4jCandidateSource(driver, database="neo4j", tenant_id=tag)
        assembler = ContextAssembler(source, settings=AssemblySettings(max_candidates_per_source=32))
        bundle = await assembler.assemble(actor, AssembleRequest(
            agent_id="agent", session_id="next-session", project_id="project",
            query="Rollback deployment stable release",
            budget=TokenBudget(model_context_tokens=12000, max_engine_tokens=1000),
        ))
        assert decision_id in {entry.item_id for entry in bundle.items}
    finally:
        await driver.execute_query("MATCH (c:Context {ace_test: $tag}) DETACH DELETE c", tag=tag, database_="neo4j")
        await driver.close()
