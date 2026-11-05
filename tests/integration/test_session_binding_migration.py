"""Old projections remain private until a reversible, source-bound backfill."""

import asyncio
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from agent_context.assembly import AssembleRequest, TokenBudget
from agent_context.bridge import scoped_id, to_session
from agent_context.contracts import Principal
from agent_context.event_store import MongoEventStore
from agent_context.events import EventConflict
from agent_context.retrieval import Neo4jCandidateSource
from agent_context.session_bindings import BindingPlan, apply_bindings, plan_bindings
from context_graph.config import Neo4jSettings
from context_graph.errors import GraphWriteError
from context_graph.graph.neo4j_store import Neo4jGraphStore
from tests.factories import context_node
from tests.integration.test_ace_events import event_store as event_store
from tests.unit.test_event_contracts import event


async def test_dry_run_apply_retry_rollback_and_reaffirmed_binding(
    event_store: MongoEventStore,
) -> None:
    tag = uuid4().hex
    actor = Principal(
        tenant_id=tag, user_id="owner", actor_id="owner", projects=frozenset({"secret"})
    )
    stream = await event_store.record(actor, event(session_id=tag, project_id="secret"))
    session = to_session(stream)
    driver = AsyncGraphDatabase.driver("bolt://127.0.0.1:7690", auth=None)
    database = event_store.collection.database.name
    mongo = event_store.collection.database.client
    try:
        await driver.execute_query(
            "CREATE(u:User {user_id:$uid,ace_migration_test:$tag}) CREATE(s:Session {session_id:$sid,user_id:$uid,ace_migration_test:$tag}) CREATE(u)-[:PARTICIPATED_IN]->(s) CREATE(c:Context) SET c=$props",
            uid=session.user_id,
            sid=session.session_id,
            tag=tag,
            props={
                **context_node(concept=tag),
                "subject_user_id": session.user_id,
                "scope_type": "SESSION",
                "scope_id": session.session_id,
                "ace_migration_test": tag,
            },
            database_="neo4j",
        )
        source = Neo4jCandidateSource(driver, database="neo4j", tenant_id=tag)
        query = AssembleRequest(
            agent_id="a1",
            session_id=tag,
            project_id="secret",
            budget=TokenBudget(model_context_tokens=12000),
        )
        assert not await source.fetch(actor, query, limit=32)
        plan = await plan_bindings(
            mongo,
            database,
            driver,
            graph_database="neo4j",
            tenant_id=tag,
            user_id="owner",
        )
        assert len(plan.changes) == 1
        plan = BindingPlan.model_validate_json(plan.model_dump_json())
        assert not await source.fetch(actor, query, limit=32)  # dry run made no write
        assert (
            await apply_bindings(plan, mongo, database, driver, graph_database="neo4j")
            == 1
        )
        assert (
            await apply_bindings(plan, mongo, database, driver, graph_database="neo4j")
            == 0
        )
        assert len(await source.fetch(actor, query, limit=32)) == 1
        with pytest.raises(PermissionError):
            await source.fetch(
                actor.model_copy(update={"projects": frozenset()}), query, limit=32
            )
        assert (
            await apply_bindings(
                plan, mongo, database, driver, graph_database="neo4j", rollback=True
            )
            == 1
        )
        assert (
            await apply_bindings(
                plan, mongo, database, driver, graph_database="neo4j", rollback=True
            )
            == 0
        )
        assert not await source.fetch(actor, query, limit=32)
        assert (
            await apply_bindings(plan, mongo, database, driver, graph_database="neo4j")
            == 1
        )
        store = Neo4jGraphStore(
            Neo4jSettings(uri="bolt://127.0.0.1:7690"), driver=driver
        )
        await store.persist_session(session)
        with pytest.raises(EventConflict, match="changed"):
            await apply_bindings(
                plan, mongo, database, driver, graph_database="neo4j", rollback=True
            )
        with pytest.raises(GraphWriteError, match="binding changed"):
            await store.persist_session(
                session.model_copy(
                    update={
                        "metadata": {
                            **session.metadata,
                            "ace_project_id": scoped_id(tag, "other"),
                        }
                    }
                )
            )
        assert len(await source.fetch(actor, query, limit=32)) == 1
    finally:
        await driver.execute_query(
            "MATCH(n {ace_migration_test:$tag}) DETACH DELETE n",
            tag=tag,
            database_="neo4j",
        )
        # persist_session may create the trusted stream's agent node.
        await driver.execute_query(
            "MATCH(a:Agent) WHERE a.agent_id IN $ids DETACH DELETE a",
            ids=list(session.agent_ids),
            database_="neo4j",
        )
        await driver.close()


async def test_concurrent_initial_bindings_cannot_move_a_session_between_projects(
    event_store: MongoEventStore,
) -> None:
    tag = uuid4().hex
    actor = Principal(tenant_id=tag, user_id="owner", actor_id="owner")
    stream = await event_store.record(actor, event(session_id=tag))
    session = to_session(stream)
    driver = AsyncGraphDatabase.driver("bolt://127.0.0.1:7690", auth=None)
    store = Neo4jGraphStore(Neo4jSettings(uri="bolt://127.0.0.1:7690"), driver=driver)
    try:
        for _ in range(8):
            # Both writers initially see an old projection without a binding.
            await driver.execute_query(
                "MERGE(s:Session {session_id:$sid}) SET s.user_id=$uid "
                "REMOVE s.ace_scope_bound,s.ace_project_id,s.ace_scope_binding_version",
                sid=session.session_id,
                uid=session.user_id,
                database_="neo4j",
            )
            proposals = tuple(
                session.model_copy(
                    update={
                        "metadata": {
                            **session.metadata,
                            "ace_project_id": scoped_id(tag, project),
                        }
                    }
                )
                for project in ("first", "second")
            )
            outcomes = await asyncio.gather(
                *(store.persist_session(proposal) for proposal in proposals),
                return_exceptions=True,
            )
            assert sum(value is None for value in outcomes) == 1
            assert sum(isinstance(value, GraphWriteError) for value in outcomes) == 1
            winner = proposals[outcomes.index(None)].metadata["ace_project_id"]
            rows, _, _ = await driver.execute_query(
                "MATCH(s:Session {session_id:$sid}) RETURN properties(s) AS props",
                sid=session.session_id,
                database_="neo4j",
            )
            assert rows[0]["props"]["ace_project_id"] == winner
            assert "ace_scope_binding_lock" not in rows[0]["props"]
    finally:
        await driver.execute_query(
            "MATCH(s:Session {session_id:$sid}) DETACH DELETE s",
            sid=session.session_id,
            database_="neo4j",
        )
        await driver.execute_query(
            "MATCH(n) WHERE n.user_id=$uid OR n.agent_id IN $agents DETACH DELETE n",
            uid=session.user_id,
            agents=list(session.agent_ids),
            database_="neo4j",
        )
        await driver.close()
