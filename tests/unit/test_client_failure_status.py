"""Terminal worker status remains distinguishable from a transient chat failure."""

import httpx
import pytest

from agent_context.client import AgentContextClient


async def test_dead_letter_status_has_a_distinct_runtime_error() -> None:
    def status(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "session_id": "s1",
                "recorded_sequence": 1,
                "available_sequence": 0,
                "state": "dead_letter",
                "attempts": 3,
            },
        )

    client = AgentContextClient(
        base_url="http://test",
        bearer_token="t" * 40,
        transport=httpx.MockTransport(status),
    )
    try:
        with pytest.raises(RuntimeError) as raised:
            await client.wait_available("e1")
        assert type(raised.value).__name__ == "EventProcessingStopped"
    finally:
        await client.aclose()
