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
from agent_context.assembly import SearchRequest
from collections.abc import Sequence


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


async def test_semantic_candidates_and_effective_history_share_private_filters() -> None:
    class QueryEmbedding:
        model = "embed-test"
        dimension = 8

        async def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0, *([0.0] * 7)] for _ in texts]

    tag = uuid4().hex
    actor = Principal(tenant_id=tag, user_id="owner", actor_id="owner")
    driver = AsyncGraphDatabase.driver("bolt://127.0.0.1:7690", auth=None)
    at = utcnow()
    shared = {"ace_test": tag, "subject_user_id": scoped_id(tag, "owner"),
              "scope_id": scoped_id(tag, "owner"), "observed_at": at - timedelta(days=5)}
    relevant = {**context_node(concept=f"{tag}_decision", value="Use the on-premises deployment"),
                **shared, "context_type": "Decision", "embedding": [1.0, *([0.0] * 7)]}
    rows = [relevant, {**relevant, "context_id": f"ctx_{tag}_foreign", "subject_user_id": "someone-else"},
            {**relevant, "context_id": f"ctx_{tag}_revoked", "status": "revoked"},
            {**relevant, "context_id": f"ctx_{tag}_expired", "valid_until": at - timedelta(days=4)},
            {**context_node(concept=f"{tag}_old", value="Italian"), **shared,
             "concept_key": "personalization:language", "status": "superseded",
             "superseded_at": at - timedelta(days=1)},
            {**context_node(concept=f"{tag}_new", value="French"), **shared,
             "concept_key": "personalization:language", "observed_at": at - timedelta(days=1)}]
    rows.extend({**context_node(concept=f"{tag}_noise_{i}"), **shared,
                 "observed_at": at, "embedding": [0.0, 1.0, *([0.0] * 6)]} for i in range(220))
    for row in rows:
        row["fingerprint"] = "fp_" + str(row["context_id"])
    try:
        await driver.execute_query("UNWIND $rows AS props CREATE(c:Context) SET c=props", rows=rows, database_="neo4j")
        source = Neo4jCandidateSource(driver, database="neo4j", tenant_id=tag, embeddings=QueryEmbedding())
        request = AssembleRequest(agent_id="agent", session_id="new-session", query="Keep infrastructure in our own facility",
                                  budget=TokenBudget(model_context_tokens=1000))
        # No lexical match: supplied query vector proves vector ranking is
        # performed before LIMIT and is used by the deployed packer.
        result = await source.fetch(actor, request, limit=1)
        assert [i.item_id for i in result] == [relevant["context_id"]]
        assert result[0].semantic_score > 0.99
        bundle = await ContextAssembler(source, settings=AssemblySettings(max_candidates_per_source=8)).assemble(actor, request)
        assert relevant["context_id"] in {i.item_id for i in bundle.items}
        current = await source.fetch(actor, request.model_copy(update={"query": "language"}), limit=32)
        assert f"ctx_{tag}_new" in {i.item_id for i in current}
        assert f"ctx_{tag}_old" not in {i.item_id for i in current}
        history = await ContextAssembler(source).search(actor, SearchRequest(
            agent_id="agent", session_id="new-session", query="language", as_of=at - timedelta(days=2),
        ))
        ids = {i.item_id for i in history.items}
        assert f"ctx_{tag}_old" in ids and f"ctx_{tag}_new" not in ids
        assert not any(i.endswith(("foreign", "revoked", "expired")) for i in ids)
        # A candidate cap must not hide an active competing value and thereby
        # make the remaining half of a conflict look authoritative.
        competing = {**relevant, "context_id": f"ctx_{tag}_competing",
                     "fingerprint": f"fp_{tag}_competing", "value": "Use public cloud",
                     "value_key": "Use public cloud"}
        await driver.execute_query("CREATE(c:Context) SET c=$props", props=competing, database_="neo4j")
        narrow = ContextAssembler(source, settings=AssemblySettings(max_candidates_per_source=1))
        conflict = await narrow.assemble(actor, request)
        assert not conflict.items and "unresolved_single_value_conflicts" in conflict.warnings
    finally:
        await driver.execute_query("MATCH(c:Context {ace_test:$tag}) DETACH DELETE c", tag=tag, database_="neo4j")
        await driver.close()
