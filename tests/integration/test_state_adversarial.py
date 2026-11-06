"""Quarantine interleavings against real Mongo, without model or graph calls."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pymongo.asynchronous.collection import AsyncCollection

from agent_context.artifacts import ArtifactInput, ArtifactStore
from agent_context.contracts import Permission, Principal
from agent_context.event_store import MongoEventStore
from agent_context.handoff import (
    ArtifactRef,
    CompletedAction,
    HandoffInput,
    HandoffService,
)
from tests.integration.test_ace_events import event_store as event_store
from tests.unit.test_event_contracts import event, principal


async def allow_action(_: Principal, __: CompletedAction) -> bool:
    return True


async def allow_artifact(_: Principal, __: ArtifactRef) -> bool:
    return True


def request() -> HandoffInput:
    return HandoffInput(
        project_id="p1",
        task_id="work",
        source_session_id="s1",
        goal="Keep private",
        handoff_id="handoff",
        idempotency_key="create",
        expected_version=0,
    )


@pytest.mark.parametrize("kind", ["events", "artifacts", "handoffs"])
async def test_quarantine_during_read_never_returns_private_content(
    event_store: MongoEventStore,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    actor = principal(projects=["p1"], permissions=list(Permission))
    client, database = (
        event_store.collection.database.client,
        event_store.collection.database.name,
    )
    store: Any
    read: Callable[[], Awaitable[object]]
    if kind == "events":
        store = event_store
        await store.record(actor, event(project_id="p1"))
        read = lambda: store.get(actor, "s1")
    elif kind == "artifacts":
        store = ArtifactStore(client, database)
        await store.ensure_indexes()
        await store.publish(
            actor,
            ArtifactInput(
                artifact_id="report",
                project_id="p1",
                expected_version=0,
                content="private bytes",
            ),
        )
        read = lambda: store.get(actor, "p1", "report")
    else:
        store = HandoffService(
            client, database, verify_action=allow_action, verify_artifact=allow_artifact
        )
        await store.ensure_indexes()
        await store.prepare(actor, request())
        read = lambda: store.latest(actor, "handoff")
    original = AsyncCollection.find_one
    fired = False

    async def intercept(
        collection: AsyncCollection[Any], *args: Any, **kwargs: Any
    ) -> Any:
        nonlocal fired
        result = await original(collection, *args, **kwargs)
        if collection.name == store.collection.name and not fired:
            fired = True
            await store.privacy.quarantine(actor)
        return result

    monkeypatch.setattr(AsyncCollection, "find_one", intercept)
    with pytest.raises(PermissionError, match="quarantined"):
        await read()
    assert fired


@pytest.mark.parametrize("kind", ["events", "artifacts", "handoffs"])
async def test_quarantine_and_purge_before_insert_cannot_resurrect_primary_data(
    event_store: MongoEventStore,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    actor = principal(projects=["p1"], permissions=list(Permission))
    client, database = (
        event_store.collection.database.client,
        event_store.collection.database.name,
    )
    store: Any
    write: Callable[[], Awaitable[object]]
    if kind == "events":
        store = event_store
        write = lambda: store.record(actor, event(project_id="p1"))
    elif kind == "artifacts":
        store = ArtifactStore(client, database)
        await store.ensure_indexes()
        write = lambda: store.publish(
            actor,
            ArtifactInput(
                artifact_id="report",
                project_id="p1",
                expected_version=0,
                content="private bytes",
            ),
        )
    else:
        store = HandoffService(
            client, database, verify_action=allow_action, verify_artifact=allow_artifact
        )
        await store.ensure_indexes()
        write = lambda: store.prepare(actor, request())
    # Cleanup must not erase another user or tenant in the same collection.
    for tenant, user in ((actor.tenant_id, "foreign"), ("other-tenant", actor.user_id)):
        owner = {"tenant_id": tenant, "user_id": user}
        if kind == "events":
            owner = {"tenant_id": tenant, "data": {"user_id": user}}
        await store.collection.insert_one(owner)
    original = AsyncCollection.insert_one
    fired = False

    async def intercept(
        collection: AsyncCollection[Any], *args: Any, **kwargs: Any
    ) -> Any:
        nonlocal fired
        if collection.name == store.collection.name and not fired:
            fired = True
            await store.privacy.quarantine(actor)
            # Models primary purge having completed before the delayed insert.
            owner_query = {"tenant_id": actor.tenant_id, "user_id": actor.user_id}
            if kind == "events":
                owner_query = {
                    "tenant_id": actor.tenant_id,
                    "data.user_id": actor.user_id,
                }
            await store.collection.delete_many(owner_query)
        return await original(collection, *args, **kwargs)

    monkeypatch.setattr(AsyncCollection, "insert_one", intercept)
    with pytest.raises(PermissionError, match="quarantined"):
        await write()
    assert fired
    assert await store.collection.count_documents({}) == 2


async def test_worker_telemetry_correlates_failure_without_source_or_provider_text(
    event_store: MongoEventStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import json
    import logging

    from agent_context.bridge import EventWorker, scoped_id
    from context_graph.observability import get_logger
    from context_graph.pipeline.orchestrator import IngestionReport

    await event_store.record(principal(), event(text="private source contents"))

    async def failed(_: object) -> IngestionReport:
        return IngestionReport(
            run_id="test",
            session_id="s1",
            batches_failed=1,
            errors=("private provider diagnostic",),
        )

    logger = get_logger("worker")
    old_level = logger.level
    logger.addHandler(caplog.handler)
    logger.setLevel(logging.INFO)
    try:
        assert await EventWorker(event_store, failed, tenant_id="t1").run_once()
    finally:
        logger.removeHandler(caplog.handler)
        logger.setLevel(old_level)
    records = {
        record.getMessage(): getattr(record, "context", {}) for record in caplog.records
    }
    result = records["worker.ingestion_result"]
    assert result["success"] is False
    assert result["batches_failed"] == 1 and result["error_count"] == 1
    assert result["stream_id"] == scoped_id("t1", "s1")
    assert records["worker.ingestion"]["duration_seconds"] >= 0
    assert "private source contents" not in json.dumps(records)
    assert "private provider diagnostic" not in json.dumps(records)
