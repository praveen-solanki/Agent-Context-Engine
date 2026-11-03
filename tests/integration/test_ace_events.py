"""Real Mongo atomicity, lease recovery and event-to-existing-pipeline feedback."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from agent_context.bridge import EventWorker, to_session
from agent_context.contracts import Permission, Principal, ProcessingState, utcnow
from agent_context.event_store import MongoEventStore
from agent_context.events import EventConflict
from context_graph.pipeline.orchestrator import IngestionReport
from tests.e2e.test_ingestion import Harness, envelope, episode_ids, signal
from tests.unit.test_event_contracts import event, principal


@pytest.fixture
async def event_store() -> AsyncIterator[MongoEventStore]:
    client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        "mongodb://127.0.0.1:27017", tz_aware=True, serverSelectionTimeoutMS=3000
    )
    database = "ace_test_" + uuid4().hex
    store = MongoEventStore(client, database)
    await store.ensure_indexes()
    try:
        yield store
    finally:
        await client.drop_database(database)
        await client.close()


async def test_concurrent_duplicate_intake_has_one_durable_event(
    event_store: MongoEventStore,
) -> None:
    await asyncio.gather(*(event_store.record(principal(), event()) for _ in range(12)))
    stream = await event_store.get(principal(), "s1")
    assert len(stream.events) == 1
    assert stream.available_sequence == 0
    with pytest.raises(EventConflict):
        await event_store.record(principal(), event(text="mutated"))
    with pytest.raises(EventConflict):
        await event_store.record(principal(), event(session_id="s2"))


async def test_session_cannot_be_hijacked_and_foreign_tenant_cannot_read(
    event_store: MongoEventStore,
) -> None:
    await event_store.record(principal(), event())
    with pytest.raises(PermissionError):
        await event_store.record(principal(user_id="foreign"), event(2))
    with pytest.raises(LookupError):
        await event_store.get(principal(user_id="foreign"), "s1")
    with pytest.raises(LookupError):
        await event_store.get(principal(tenant_id="foreign"), "s1")
    other = principal(tenant_id="foreign")
    await event_store.record(other, event())
    assert (await event_store.get(other, "s1")).tenant_id == "foreign"


async def test_lease_excludes_other_workers_and_fences_stale_completion(
    event_store: MongoEventStore,
) -> None:
    await event_store.record(principal(), event())
    first = await event_store.claim("t1")
    assert first is not None
    assert await event_store.claim("t1") is None
    await event_store.collection.update_one(
        {"session_id": "s1"}, {"$set": {"lease_until": utcnow()}}
    )
    second = await event_store.claim("t1")
    assert second is not None and first[1] != second[1]
    assert not await event_store.finish(*first, success=True)
    assert await event_store.finish(*second, success=True)
    assert (await event_store.get(principal(), "s1")).available_sequence == 1


async def test_append_during_processing_survives_completion(
    event_store: MongoEventStore,
) -> None:
    await event_store.record(principal(), event())
    claim = await event_store.claim("t1")
    assert claim is not None
    await event_store.record(principal(), event(2))
    assert await event_store.finish(*claim, success=True)
    stream = await event_store.get(principal(), "s1")
    assert len(stream.events) == 2 and stream.available_sequence == 1
    assert stream.status().state == ProcessingState.RECORDED
    assert await event_store.claim("t1") is not None


async def test_failed_batches_do_not_advance_and_dead_letters_are_replayable(
    event_store: MongoEventStore,
) -> None:
    await event_store.record(principal(), event())

    async def failed(_: object) -> IngestionReport:
        return IngestionReport(run_id="test", session_id="s1", batches_failed=1)

    worker = EventWorker(event_store, failed, tenant_id="t1", max_attempts=2)
    assert await worker.run_once()
    assert (await event_store.get(principal(), "s1")).state == ProcessingState.FAILED
    assert await worker.run_once()
    stream = await event_store.get(principal(), "s1")
    assert stream.state == ProcessingState.DEAD and stream.available_sequence == 0
    assert not await worker.run_once()
    with pytest.raises(PermissionError):
        await event_store.replay(principal(), "s1")
    admin = Principal.model_validate(
        {**principal().model_dump(), "permissions": [Permission.ADMIN, Permission.VIEW]}
    )
    await event_store.replay(admin, "s1")
    assert (await event_store.get(principal(), "s1")).state == ProcessingState.RECORDED


async def test_real_outbox_drives_existing_pipeline_and_correction_without_manual_cli(
    event_store: MongoEventStore,
) -> None:
    first = await event_store.record(principal(), event())
    session_a = to_session(first)
    harness = Harness(
        [
            envelope(
                signal(
                    "response_detail",
                    "concise",
                    episode_ids=tuple(episode_ids(session_a)),
                    durability_cue=True,
                )
            )
        ]
    )
    worker = EventWorker(event_store, harness.ingest, tenant_id="t1")
    assert await worker.run_once()
    assert (await event_store.get(principal(), "s1")).available_sequence == 1
    correcting = principal(
        permissions=[Permission.ASSERT, Permission.CORRECT, Permission.VIEW]
    )
    second = await event_store.record(
        correcting,
        event(2, kind="correction", text="Actually always give detailed answers."),
    )
    harness.llm.enqueue(
        envelope(
            signal(
                "response_detail",
                "detailed",
                episode_ids=(episode_ids(to_session(second))[1],),
                durability_cue=True,
            )
        )
    )
    assert await worker.run_once()
    assert {c.value: c.status.value for c in harness.store.contexts.values()} == {
        "concise": "superseded",
        "detailed": "active",
    }
    await event_store.record(
        correcting,
        event(2, kind="correction", text="Actually always give detailed answers."),
    )
    assert not await worker.run_once()
    assert len(harness.store.contexts) == 2 and len(harness.store.episodes) == 2
