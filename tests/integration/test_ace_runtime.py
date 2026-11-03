"""The deployable API factory starts, checks real services and closes resources."""

from __future__ import annotations

import json
from hashlib import sha256
from uuid import uuid4

import httpx
import pytest
from pymongo import AsyncMongoClient

from agent_context.runtime import RuntimeSettings, application
from tests.unit.test_event_contracts import event, principal


async def test_api_runtime_factory_with_real_database_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = "ace_test_" + uuid4().hex
    token = "test-token-" + "a" * 40
    monkeypatch.setenv("ACE_TENANT_ID", "t1")
    monkeypatch.setenv("ACE_USER_ID", "u1")
    monkeypatch.setenv(
        "ACE_AUTH_BINDINGS",
        json.dumps(
            {sha256(token.encode()).hexdigest(): principal().model_dump(mode="json")}
        ),
    )
    monkeypatch.setenv("CG_MONGO__URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("CG_MONGO__DATABASE", database)
    monkeypatch.setenv("CG_NEO4J__URI", "bolt://127.0.0.1:7690")
    app = application()
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                assert (await client.get("/health/ready")).status_code == 200
                assert (
                    await client.post(
                        "/v1/events", json=event().model_dump(mode="json")
                    )
                ).status_code == 202
                assembled = await client.post(
                    "/v1/context/assemble",
                    json={
                        "agent_id": "agent",
                        "session_id": "s1",
                        "budget": {"model_context_tokens": 10000},
                    },
                )
                assert assembled.status_code == 200 and assembled.json()["items"] == []
    finally:
        async with AsyncMongoClient[dict[str, object]](
            "mongodb://127.0.0.1:27017"
        ) as mongo:
            await mongo.drop_database(database)


def test_runtime_refuses_bindings_that_mix_trust_partitions() -> None:
    with pytest.raises(ValueError, match="trust partition"):
        RuntimeSettings(
            tenant_id="t1",
            user_id="u1",
            auth_bindings={"a" * 64: principal(user_id="foreign")},
        )
