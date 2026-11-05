"""The new directory participates in existing owner export and primary erasure."""

import json

from agent_context.contracts import Principal
from agent_context.governance import GovernanceService
from agent_context.navigation import ProjectCreate
from agent_context.project_store import ProjectStore
from tests.integration.test_ace_events import event_store as event_store
from tests.integration.test_ace_governance import governance as governance


async def test_project_directory_export_and_erasure_are_owner_scoped(
    governance: tuple[GovernanceService, Principal, str],
) -> None:
    service, owner, _ = governance
    store = ProjectStore(service.db.client, service.db.name)
    await store.ensure_indexes()
    body = ProjectCreate(
        title="Owned archive",
        source_text="Build Owned archive",
        name_quote="Owned archive",
        idempotency_key="one",
        expected_revision=0,
    )
    own = await store.create(owner, body)
    other = owner.model_copy(update={"user_id": "another", "actor_id": "another"})
    await store.create(other, body)
    owner = await store.authorize(owner)
    rows = [json.loads(line) async for line in service.export(owner)]
    projects = [row["data"] for row in rows if row["kind"] == "project"]
    assert len(projects) == 1 and projects[0]["project_id"] == own.project_id
    assert "creation_digest" not in projects[0] and "delegates" not in projects[0]
    await service.request_erasure(owner)
    assert (await service.purge(owner))["state"] == "primary_purged"
    assert await store.collection.find_one(store.key(owner)) is None
    assert await store.collection.find_one(store.key(other)) is not None
