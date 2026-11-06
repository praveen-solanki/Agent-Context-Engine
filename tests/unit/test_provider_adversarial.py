"""Provider boundary regressions; all HTTP responses and delays are local doubles."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from context_graph.config import (
    ChatBackendSettings,
    EmbeddingSettings,
    LLMSettings,
    RetrySettings,
)
from context_graph.errors import ProviderError, TransientError
from context_graph.providers.chat_backend import (
    ChatLLMProvider,
    ChatTransport,
    EmbeddingProviderImpl,
)
from context_graph.retry import retry_async


@pytest.mark.parametrize(
    "data",
    [
        [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 0, "embedding": [0.0, 1.0]}],
        [{"index": -1, "embedding": [1.0, 0.0]}, {"index": 1, "embedding": [0.0, 1.0]}],
        [{"index": 0, "embedding": [1.0, 0.0]}, {"index": 2, "embedding": [0.0, 1.0]}],
        [
            {"index": False, "embedding": [1.0, 0.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ],
        [
            {"index": "0", "embedding": [1.0, 0.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ],
        [
            {"index": 0.5, "embedding": [1.0, 0.0]},
            {"index": 1, "embedding": [0.0, 1.0]},
        ],
        ["not-a-vector", {"index": 1, "embedding": [0.0, 1.0]}],
    ],
)
async def test_embedding_indices_form_an_exact_input_permutation(
    data: list[Any],
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"data": data})
        )
    ) as client:
        provider = EmbeddingProviderImpl(
            embedding=EmbeddingSettings(
                base_url="https://example.test/v1", dimension=2, batch_size=8
            ),
            client=client,
        )
        with pytest.raises(ProviderError):
            await provider.embed(["first", "second"])


@pytest.mark.parametrize(
    "vector",
    [
        [1.0],
        [float("nan"), 1.0],
        [float("inf"), 1.0],
        ["1", 0],
        [True, 0],
        [0, 0],
        {"x": 1, "y": 0},
    ],
)
async def test_embedding_vectors_are_finite_nonzero_numeric_and_dimensioned(
    vector: Any,
) -> None:
    # httpx's JSON encoder refuses NaN; use serialized bytes to model a bad upstream.
    import json

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, content=json.dumps({"data": [{"index": 0, "embedding": vector}]})
            )
        )
    ) as client:
        provider = EmbeddingProviderImpl(
            embedding=EmbeddingSettings(
                base_url="https://example.test/v1", dimension=2
            ),
            client=client,
        )
        with pytest.raises(ProviderError):
            await provider.embed(["first"])


@pytest.mark.parametrize("payload", ["not JSON", "[]", "null"])
async def test_non_object_success_responses_fail_as_provider_errors(
    payload: str,
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=payload))
    ) as client:
        transport = ChatTransport(
            ChatBackendSettings(
                api_key=SecretStr("test"), base_url="https://example.test/v1"
            ),
            retry=RetrySettings(max_attempts=1),
            client=client,
        )
        with pytest.raises(ProviderError):
            await transport.post("chat/completions", {}, "fixture")


class Reply(BaseModel):
    text: str


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{"message": {"content": {"text": "not-a-string"}}}]},
    ],
)
async def test_malformed_chat_envelopes_fail_with_a_typed_error(
    body: dict[str, Any],
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    ) as client:
        settings = ChatBackendSettings(
            api_key=SecretStr("test"), base_url="https://example.test/v1"
        )
        provider = ChatLLMProvider(
            backend=settings,
            llm=LLMSettings(),
            transport=ChatTransport(
                settings, retry=RetrySettings(max_attempts=1), client=client
            ),
        )
        with pytest.raises(ProviderError):
            await provider.structured(
                system="s", user="u", schema=Reply, max_output_tokens=20
            )


@pytest.mark.parametrize("embeddings", [False, True])
async def test_retry_after_is_respected_without_jittering_below_it(
    monkeypatch: pytest.MonkeyPatch, embeddings: bool
) -> None:
    waits: list[float] = []
    attempts = 0

    async def sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr("context_graph.retry.random.random", lambda: 0.0)

    def response(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={})
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]}
            if embeddings
            else {"ok": True},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        policy = RetrySettings(
            max_attempts=2, base_backoff_seconds=1, max_backoff_seconds=10
        )
        if embeddings:
            await EmbeddingProviderImpl(
                embedding=EmbeddingSettings(
                    base_url="https://example.test/v1", dimension=2
                ),
                retry=policy,
                client=client,
            ).embed(["x"])
        else:
            await ChatTransport(
                ChatBackendSettings(
                    api_key=SecretStr("test"), base_url="https://example.test/v1"
                ),
                retry=policy,
                client=client,
            ).post("chat/completions", {}, "fixture")
    assert attempts == 2 and waits == [7.0]


async def test_retry_jitter_never_exceeds_the_configured_backoff_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        waits.append(delay)

    async def fail() -> None:
        raise TransientError("temporary")

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr("context_graph.retry.random.random", lambda: 1.0)
    with pytest.raises(TransientError):
        await retry_async(
            fail,
            settings=RetrySettings(
                max_attempts=2, base_backoff_seconds=10, max_backoff_seconds=10
            ),
            description="test",
        )
    assert waits == [10.0]


async def test_in_house_duplicate_ids_are_rejected() -> None:
    from context_graph.config import EmbeddingBackend

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "0", "embedding": [1.0, 0.0]},
                        {"id": "0", "embedding": [0.0, 1.0]},
                    ]
                },
            )
        )
    ) as client:
        provider = EmbeddingProviderImpl(
            embedding=EmbeddingSettings(
                backend=EmbeddingBackend.IN_HOUSE,
                base_url="https://example.test/v1",
                dimension=2,
                batch_size=8,
            ),
            client=client,
        )
        with pytest.raises(ProviderError):
            await provider.embed(["a", "b"])


async def test_huge_integer_vector_fails_at_the_provider_boundary() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [10**1000, 1]}]}
            )
        )
    ) as client:
        provider = EmbeddingProviderImpl(
            embedding=EmbeddingSettings(
                base_url="https://example.test/v1", dimension=2
            ),
            client=client,
        )
        with pytest.raises(ProviderError):
            await provider.embed(["a"])


async def test_retry_after_above_policy_ceiling_does_not_retry_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []
    attempts = 0

    async def sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    def response(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(429, headers={"Retry-After": "120"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        transport = ChatTransport(
            ChatBackendSettings(
                api_key=SecretStr("test"), base_url="https://example.test/v1"
            ),
            retry=RetrySettings(max_attempts=3, max_backoff_seconds=10),
            client=client,
        )
        with pytest.raises(TransientError) as raised:
            await transport.post("chat/completions", {}, "fixture")
    assert raised.value.retry_after_seconds == 120
    assert attempts == 1 and waits == []


async def test_retry_after_accepts_http_dates(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    attempts = 0

    async def sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)

    def response(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                503,
                headers={
                    "Retry-After": format_datetime(
                        datetime.now(UTC) + timedelta(seconds=30), usegmt=True
                    )
                },
            )
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        transport = ChatTransport(
            ChatBackendSettings(
                api_key=SecretStr("test"), base_url="https://example.test/v1"
            ),
            retry=RetrySettings(max_attempts=2, max_backoff_seconds=60),
            client=client,
        )
        await transport.post("chat/completions", {}, "fixture")
    assert len(waits) == 1 and 28 <= waits[0] <= 30


@pytest.mark.parametrize("hint", ["NaN", "Infinity", "not-a-date"])
async def test_invalid_retry_hint_uses_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch, hint: str
) -> None:
    waits: list[float] = []
    attempts = 0

    async def sleep(delay: float) -> None:
        waits.append(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr("context_graph.retry.random.random", lambda: 0.5)

    def response(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return (
            httpx.Response(429, headers={"Retry-After": hint})
            if attempts == 1
            else httpx.Response(200, json={})
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        transport = ChatTransport(
            ChatBackendSettings(
                api_key=SecretStr("test"), base_url="https://example.test/v1"
            ),
            retry=RetrySettings(
                max_attempts=2, base_backoff_seconds=2, max_backoff_seconds=10
            ),
            client=client,
        )
        await transport.post("chat/completions", {}, "fixture")
    assert attempts == 2 and waits == [2.0]


async def test_cancellation_is_not_retried() -> None:
    attempts = 0

    async def cancel() -> None:
        nonlocal attempts
        attempts += 1
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await retry_async(
            cancel, settings=RetrySettings(max_attempts=3), description="cancelled"
        )
    assert attempts == 1


async def test_provider_error_does_not_echo_private_upstream_content() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                400, text="private source text and credential value"
            )
        )
    ) as client:
        transport = ChatTransport(
            ChatBackendSettings(
                api_key=SecretStr("test"), base_url="https://example.test/v1"
            ),
            retry=RetrySettings(max_attempts=1),
            client=client,
        )
        with pytest.raises(ProviderError) as raised:
            await transport.post("chat/completions", {}, "fixture")
    assert "private source" not in str(raised.value)


async def test_nvidia_request_shape_depends_on_actual_hostname() -> None:
    import json

    def response(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["dimensions"] == 2 and "input_type" not in payload
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        provider = EmbeddingProviderImpl(
            embedding=EmbeddingSettings(
                base_url="https://api.nvidia.com.example.test/v1", dimension=2
            ),
            client=client,
        )
        assert await provider.embed(["a"]) == [[1.0, 0.0]]


async def test_structured_repair_includes_the_response_being_repaired() -> None:
    import json

    requests: list[dict[str, Any]] = []

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            content = '{"wrong_field":"original response"}'
        else:
            assert requests[-1]["messages"][-2] == {
                "role": "assistant",
                "content": '{"wrong_field":"original response"}',
            }
            content = '{"text":"repaired"}'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        settings = ChatBackendSettings(
            api_key=SecretStr("test"), base_url="https://example.test/v1"
        )
        provider = ChatLLMProvider(
            backend=settings,
            llm=LLMSettings(),
            transport=ChatTransport(
                settings, retry=RetrySettings(max_attempts=1), client=client
            ),
        )
        assert await provider.structured(
            system="s", user="u", schema=Reply, max_output_tokens=30
        ) == Reply(text="repaired")
