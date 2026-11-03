"""Disposable, attributed data for the credentialed legacy UI integration test."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from neo4j import AsyncGraphDatabase

from context_graph.config import get_settings
from tests.factories import context_node


@pytest.fixture
def live_ui_graph() -> Iterator[None]:
    tag = "ace-ui-" + uuid4().hex

    async def seed(remove: bool = False) -> None:
        settings = get_settings().neo4j
        async with AsyncGraphDatabase.driver(
            settings.uri, auth=(settings.user, settings.password.get_secret_value())
        ) as driver:
            if remove:
                await driver.execute_query(
                    "MATCH (n {ace_ui_fixture: $tag}) DETACH DELETE n",
                    tag=tag,
                    database_=settings.database,
                )
                return
            rows, _, _ = await driver.execute_query(
                "MATCH (u:User {user_id:'ACE-UI-Synthetic-User'}) RETURN count(u) AS count",
                database_=settings.database,
            )
            if rows[0]["count"]:
                raise RuntimeError(
                    "live UI fixture requires a disposable graph without ACE-UI-Synthetic-User"
                )
            await driver.execute_query(
                "CREATE (u:User {user_id:'ACE-UI-Synthetic-User',name:'ACE Synthetic User',ace_ui_fixture:$tag}) "
                "CREATE (t:Team {team_id:'ace-ui-synthetic-team',name:'Synthetic Research Team',ace_ui_fixture:$tag}) CREATE (u)-[:MEMBER_OF]->(t)",
                tag=tag,
                database_=settings.database,
            )
            for kind, value, scope, scope_id, subject in (
                (
                    "summary_style",
                    "concise summaries",
                    "USER",
                    "ACE-UI-Synthetic-User",
                    "ACE-UI-Synthetic-User",
                ),
                (
                    "deployment_day",
                    "The Synthetic Research Team team decided to deploy on Thursdays",
                    "TEAM",
                    "ace-ui-synthetic-team",
                    "",
                ),
            ):
                props = {
                    **context_node(
                        concept=f"ace_ui_{kind}",
                        value=value,
                        scope_type=scope,
                        scope_id=scope_id,
                    ),
                    "subject_user_id": subject,
                    "source_actor": "ACE-UI-Synthetic-User",
                    "ace_ui_fixture": tag,
                    "context_type": "Decision" if scope == "TEAM" else "Preference",
                }
                label = "Team" if scope == "TEAM" else "User"
                # The two query shapes are static allowlisted ontology labels.
                query = (
                    "MATCH (target:Team {team_id:$scope_id}) "
                    if label == "Team"
                    else "MATCH (target:User {user_id:$scope_id}) "
                )
                query += (
                    "CREATE (c:Context) SET c=$props CREATE (c)-[:APPLIES_TO]->(target)"
                )
                await driver.execute_query(
                    query, scope_id=scope_id, props=props, database_=settings.database
                )  # pyright: ignore[reportArgumentType]

    get_settings.cache_clear()
    asyncio.run(seed())
    try:
        yield
    finally:
        asyncio.run(seed(remove=True))
        get_settings.cache_clear()
