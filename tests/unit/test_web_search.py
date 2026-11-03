"""Search transport, bounded input/output, public links and safe failures."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import HttpUrl, SecretStr, ValidationError

from agent_context.search import (
    BRAVE_ENDPOINT,
    BraveSearch,
    SearchSettings,
    SearchResult,
    SearchNotConfigured,
    SearchAuthenticationError,
    SearchRateLimited,
    SearchUnavailable,
)


def settings(**changes: object) -> SearchSettings:
    return SearchSettings.model_validate(
        {"api_key": SecretStr("unit-search-key"), "_env_file": None, **changes}
    )


async def test_query_only_request_and_validated_sources() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(BRAVE_ENDPOINT + "?")
        assert request.url.params["q"] == "Python release notes"
        assert request.url.params["safesearch"] == "strict"
        assert request.headers["X-Subscription-Token"] == "unit-search-key"
        assert "unit-search-key" not in str(request.url)
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "<b>Python</b> &amp; notes",
                            "url": "https://www.python.org/downloads/",
                            "description": "<em>Official</em> releases.",
                        }
                    ]
                }
            },
        )

    async with BraveSearch(
        settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    ) as search:
        response = await search.search("  Python release notes  ")
    assert len(response.results) == 1 and not response.discarded_results
    result = response.results[0]
    assert result.title == "Python & notes" and result.snippet == "Official releases."
    assert (
        json.loads(result.as_document())["url"] == "https://www.python.org/downloads/"
    )
    assert "not a full page read" in result.as_document()


@pytest.mark.parametrize(
    "status,kind",
    [
        (401, SearchAuthenticationError),
        (403, SearchAuthenticationError),
        (429, SearchRateLimited),
        (500, SearchUnavailable),
        (302, SearchUnavailable),
    ],
)
async def test_provider_failure_is_sanitized_and_redirects_are_not_followed(
    status: int, kind: type[Exception]
) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            status,
            json={"private": "unit-search-key PRIVATE_PROVIDER_BODY"},
            headers={"Location": "https://evil.example.org/"},
        )

    async with BraveSearch(
        settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    ) as search:
        with pytest.raises(kind) as error:
            await search.search("private search query")
    assert len(calls) == 1
    assert all(
        secret not in str(error.value)
        for secret in (
            "unit-search-key",
            "PRIVATE_PROVIDER_BODY",
            "private search query",
        )
    )


async def test_missing_key_or_invalid_query_makes_no_network_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)

    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make a request")

    client = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    async with BraveSearch(
        SearchSettings.model_validate({"_env_file": None, "api_key": None}),
        client=client,
    ) as search:
        with pytest.raises(SearchNotConfigured):
            await search.search("query")
    async with BraveSearch(
        settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
    ) as search:
        for query in ("", " " * 4, "😀" * 251):
            with pytest.raises(ValueError):
                await search.search(query)


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "http://127.0.0.1/a",
        "http://10.0.0.1/a",
        "http://169.254.169.254/",
        "http://[::1]/",
        "https://localhost/",
        "https://host.internal/",
        "https://user:password@example.org/",
        "https://example.org/?access_token=private",
    ],
)
def test_unsafe_result_links_are_rejected(url: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        SearchResult(
            title="Title",
            url=HttpUrl(url),
            snippet="Snippet",
            retrieved_at=datetime.now(UTC),
        )


async def test_results_are_bounded_deduplicated_and_bad_urls_are_discarded() -> None:
    rows = [
        {"title": "private", "url": "http://127.0.0.1/"},
        {"title": "public", "url": "https://example.org/a", "description": "text"},
        {"title": "duplicate", "url": "https://example.org/a", "description": "text"},
        {"title": "outside count", "url": "https://example.org/b"},
    ]
    async with BraveSearch(
        settings(),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"web": {"results": rows}})
            )
        ),
    ) as search:
        response = await search.search("query")
    assert len(response.results) == 1 and response.discarded_results == 2


@pytest.mark.parametrize("payload", [[], {"web": []}, {"web": {"results": "invalid"}}])
async def test_malformed_response_is_not_reported_as_no_results(
    payload: object,
) -> None:
    async with BraveSearch(
        settings(),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
    ) as search:
        with pytest.raises(SearchUnavailable):
            await search.search("query")


async def test_large_response_and_transport_failure_are_bounded_and_sanitized() -> None:
    async with BraveSearch(
        settings(max_response_bytes=1024),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"x" * 2048)
            )
        ),
    ) as search:
        with pytest.raises(SearchUnavailable, match="size bound"):
            await search.search("query")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("PRIVATE_QUERY_AND_KEY", request=request)

    async with BraveSearch(
        settings(), client=httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    ) as search:
        with pytest.raises(SearchUnavailable) as error:
            await search.search("query")
    assert "PRIVATE" not in str(error.value)


async def test_empty_results_are_valid() -> None:
    async with BraveSearch(
        settings(),
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"query": {"q": "none"}})
            )
        ),
    ) as search:
        assert not (await search.search("none")).results


def test_source_id_is_a_digest_of_the_exact_recorded_snapshot() -> None:
    now = datetime.now(UTC)
    one = SearchResult(
        title="source",
        url=HttpUrl("https://example.org/a"),
        snippet="old",
        retrieved_at=now,
    )
    two = one.model_copy(update={"snippet": "changed"})
    assert one.document_id != two.document_id
    assert one.document_id == one.model_copy().document_id
