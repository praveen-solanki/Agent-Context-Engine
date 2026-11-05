"""Project-origin USER facts must be filtered before ranking and inspection."""

from uuid import uuid4

from neo4j import AsyncGraphDatabase

from agent_context.assembly import AssembleRequest, SearchRequest, TokenBudget
from agent_context.bridge import scoped_id
from agent_context.contracts import Principal
from agent_context.retrieval import Neo4jCandidateSource
from tests.factories import context_node


async def test_project_origin_user_facts_are_not_other_projects_personal_memory() -> (
    None
):
    tag = uuid4().hex
    actor = Principal(
        tenant_id=tag,
        user_id="owner",
        actor_id="owner",
        projects=frozenset({"alpha", "beta"}),
    )
    uid = scoped_id(tag, "owner")
    driver = AsyncGraphDatabase.driver("bolt://127.0.0.1:7690", auth=None)
    rows = []
    cases = [
        ("alpha_fact", "alpha", "Fact", None),
        ("beta_fact", "beta", "Fact", None),
        ("personal_preference", "beta", "Preference", True),
        ("legacy_project_preference", "beta", "Preference", None),
        ("personal_constraint", "beta", "Constraint", True),
        ("project_preference", "beta", "Preference", False),
        ("unbound_fact", None, "Fact", None),
    ]
    try:
        for name, project, kind, personal in cases:
            sid = scoped_id(tag, name)
            await driver.execute_query(
                "CREATE(s:Session {session_id:$sid,user_id:$uid,ace_scope_bound:true,ace_project_id:$project,ace_test:$tag})",
                sid=sid,
                uid=uid,
                project=scoped_id(tag, project) if project else None,
                tag=tag,
                database_="neo4j",
            )
            rows.append(
                {
                    **context_node(tag + "_" + name, value="budget event details"),
                    "subject_user_id": uid,
                    "scope_id": uid,
                    "source_session_id": sid,
                    "context_type": kind,
                    "personal_scope": personal,
                    "ace_test": tag,
                }
            )
        await driver.execute_query(
            "UNWIND $rows AS props CREATE(c:Context) SET c=props",
            rows=rows,
            database_="neo4j",
        )
        source = Neo4jCandidateSource(driver, database="neo4j", tenant_id=tag)
        request = SearchRequest(
            agent_id="agent", session_id="new-session", project_id="alpha", query=""
        )
        actual = await source.fetch(actor, request, limit=32)
        ids = {entry.item_id for entry in actual}
        expected = {
            f"ctx_{tag}_{name}"
            for name in (
                "alpha_fact",
                "personal_preference",
                "personal_constraint",
                "unbound_fact",
            )
        }
        assert ids == expected
        bound = next(entry for entry in actual if entry.item_id.endswith("_alpha_fact"))
        assert bound.project_id == "alpha"
        global_personal = next(
            entry for entry in actual if entry.item_id.endswith("_personal_constraint")
        )
        assert global_personal.project_id is None
        # The same boundary is used for empty-query inspection and answering.
        assembled = await source.fetch(
            actor,
            AssembleRequest(
                agent_id="agent",
                session_id="new-session",
                project_id="alpha",
                query="budget",
                budget=TokenBudget(model_context_tokens=10000),
            ),
            limit=32,
        )
        assert {entry.item_id for entry in assembled} == expected
        unbound = await source.fetch(
            actor, request.model_copy(update={"project_id": None}), limit=32
        )
        assert {entry.item_id for entry in unbound} == {
            f"ctx_{tag}_{name}"
            for name in ("personal_preference", "personal_constraint", "unbound_fact")
        }
    finally:
        await driver.execute_query(
            "MATCH(n {ace_test:$tag}) DETACH DELETE n", tag=tag, database_="neo4j"
        )
        await driver.close()
