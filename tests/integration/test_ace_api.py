"""Authenticated HTTP+SDK over a real durable outbox and handoff store."""

from __future__ import annotations

from hashlib import sha256

import httpx

from agent_context.api import create_app
from agent_context.assembly import ContextAssembler
from agent_context.client import AgentContextClient
from agent_context.contracts import Principal
from agent_context.event_store import MongoEventStore
from agent_context.handoff import ArtifactRef, CompletedAction, HandoffService
from tests.integration.test_ace_events import event_store as event_store
from tests.unit.test_assembly import Source, item, request
from tests.unit.test_event_contracts import event, principal

TOKEN = "a" * 40


async def test_api_sdk_identity_and_durable_lifecycle(
    event_store: MongoEventStore,
) -> None:
    async def deny_action(_: Principal, __: CompletedAction) -> bool:
        return False

    async def deny_artifact(_: Principal, __: ArtifactRef) -> bool:
        return False

    async def ready() -> bool:
        return True

    handoffs = HandoffService(
        event_store.collection.database.client,
        event_store.collection.database.name,
        verify_action=deny_action,
        verify_artifact=deny_artifact,
    )
    await handoffs.ensure_indexes()
    app = create_app(
        events=event_store,
        assembler=ContextAssembler(Source(item())),
        handoffs=handoffs,
        auth_bindings={sha256(TOKEN.encode()).hexdigest(): principal()},
        ready=ready,
        watermark_timeout_seconds=0.05,
    )
    transport = httpx.ASGITransport(app=app)
    client = AgentContextClient(
        base_url="http://test", bearer_token=TOKEN, transport=transport
    )
    try:
        assert (await client.record_events(event())).available_sequence == 0
        assert (await client.record_events(event())).recorded_sequence == 1
        bundle = await client.assemble_context(request())
        assert len(bundle.items) == 1
        search = request().model_dump(mode="json", exclude={"budget"})
        response = await client.http.post("/v1/context/search", json={**search, "limit": 1})
        assert response.status_code == 200
        assert len(response.json()["items"]) == 1
        assert "rendered" not in response.json()
        response = await client.http.get("/v1/events/e1/status")
        assert response.status_code == 200 and response.json()["state"] == "recorded"
        assert response.headers.get("x-request-id")
        forged = {**event(2).model_dump(mode="json"), "user_id": "someone-else"}
        response = await client.http.post("/v1/events", json=forged)
        assert response.status_code == 422
        assert "someone-else" not in response.text
        unauthorized = await client.http.post(
            "/v1/context/assemble",
            json=request(project_id="not-granted").model_dump(mode="json"),
        )
        assert unauthorized.status_code == 403
        response = await client.http.post(
            "/v1/context/assemble",
            json=request(minimum_sequence=1).model_dump(mode="json"),
        )
        assert response.status_code == 503
        response = await client.http.post("/v1/events", content=b"x" * 140000)
        assert response.status_code == 413
        assert (await client.http.get("/openapi.json")).json()["info"][
            "title"
        ] == "Agent Context Engine"
        assert (await client.http.get("/health/ready")).status_code == 200
    finally:
        await client.aclose()
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as anonymous:
        assert (await anonymous.get("/health/live")).status_code == 200
        assert (
            await anonymous.post("/v1/events", json=event().model_dump(mode="json"))
        ).status_code == 401


async def test_dependency_failure_is_typed_and_private_errors_are_not_returned(
    event_store: MongoEventStore,
) -> None:
    async def deny_action(_: Principal, __: CompletedAction) -> bool:
        return False

    async def deny_artifact(_: Principal, __: ArtifactRef) -> bool:
        return False

    async def not_ready() -> bool:
        raise ConnectionError("private connection details")

    handoffs = HandoffService(
        event_store.collection.database.client,
        event_store.collection.database.name,
        verify_action=deny_action,
        verify_artifact=deny_artifact,
    )
    app = create_app(
        events=event_store,
        assembler=ContextAssembler(Source(broken=True)),
        handoffs=handoffs,
        auth_bindings={sha256(TOKEN.encode()).hexdigest(): principal()},
        ready=not_ready,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {TOKEN}"},
    ) as client:
        result = await client.post(
            "/v1/context/assemble", json=request().model_dump(mode="json")
        )
        assert result.status_code == 503 and "private" not in result.text
        result = await client.get("/health/ready")
        assert result.status_code == 503 and "private" not in result.text
