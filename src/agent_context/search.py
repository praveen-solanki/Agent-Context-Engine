"""Bounded web search through a fixed provider endpoint; no arbitrary URL fetches."""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
from datetime import datetime
from typing import Self
from urllib.parse import parse_qsl

import httpx
from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    SecretStr,
    ValidationError,
    field_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_context.contracts import Contract, utcnow

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class SearchError(RuntimeError):
    """Sanitized errors: never include a provider response, query, or API key."""


class SearchNotConfigured(SearchError):
    pass


class SearchAuthenticationError(SearchError):
    pass


class SearchRateLimited(SearchError):
    pass


class SearchUnavailable(SearchError):
    pass


class SearchSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ACE_SEARCH_",
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    api_key: SecretStr | None = Field(
        default=None, validation_alias="BRAVE_SEARCH_API_KEY"
    )
    result_count: int = Field(default=3, ge=1, le=5)
    timeout_seconds: float = Field(default=15, gt=0, le=60)
    max_response_bytes: int = Field(default=262144, ge=1024, le=1048576)
    max_snippet_chars: int = Field(default=800, ge=100, le=2000)

    @property
    def configured(self) -> bool:
        return bool(
            self.api_key
            and self.api_key.get_secret_value().strip()
            and self.api_key.get_secret_value() not in ("change-me", "your-key-here")
        )


def plain_text(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value)).split())


class SearchResult(Contract):
    title: str = Field(min_length=1, max_length=256)
    url: HttpUrl = Field(max_length=2048)
    snippet: str = Field(max_length=2000)
    retrieved_at: datetime

    @field_validator("url")
    @classmethod
    def public_url(cls, url: HttpUrl) -> HttpUrl:
        host = (url.host or "").rstrip(".").lower()
        if url.username is not None or url.password is not None or not host:
            raise ValueError("search result URL must not contain credentials")
        try:
            address = ipaddress.ip_address(host.strip("[]"))
        except ValueError:
            if "." not in host or host.endswith(
                (".localhost", ".local", ".internal", ".test", ".invalid")
            ):
                raise ValueError("search result must identify a public host") from None
        else:
            if not address.is_global:
                raise ValueError(
                    "private and reserved result addresses are not allowed"
                )
        private_parameters = {
            "token",
            "key",
            "api_key",
            "api-key",
            "apikey",
            "access_token",
            "client_secret",
            "secret",
            "authorization",
            "awsaccesskeyid",
            "x-amz-credential",
            "x-amz-security-token",
            "x-amz-signature",
            "x-goog-credential",
            "x-goog-signature",
            "sig",
            "password",
            "signature",
        }
        if any(
            key.casefold() in private_parameters
            for section in (url.query, url.fragment)
            for key, _ in parse_qsl(section or "")
        ):
            raise ValueError("credential-bearing result URLs are not allowed")
        return url

    @property
    def document_id(self) -> str:
        return "web-" + hashlib.sha256(self.as_document().encode()).hexdigest()

    def as_document(self) -> str:
        return json.dumps(
            {
                "title": self.title,
                "url": str(self.url),
                "search_excerpt": self.snippet,
                "retrieved_at": self.retrieved_at.isoformat(),
                "evidence_kind": "search snippet, not a full page read",
            },
            ensure_ascii=False,
        )


class SearchResponse(Contract):
    results: tuple[SearchResult, ...]
    discarded_results: int = 0


class _BraveHit(BaseModel):
    title: str
    url: str
    description: str | None = ""


class BraveSearch:
    def __init__(
        self,
        settings: SearchSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or SearchSettings()
        self.client = client or httpx.AsyncClient(
            timeout=self.settings.timeout_seconds, follow_redirects=False
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    async def search(self, query: str) -> SearchResponse:
        if not self.settings.configured or self.settings.api_key is None:
            raise SearchNotConfigured(
                "Web search needs a configured Brave Search credential."
            )
        query = query.strip()
        if not query or len(query.encode()) > 1000:
            raise ValueError("search query must contain 1–1000 UTF-8 bytes")
        try:
            async with self.client.stream(
                "GET",
                BRAVE_ENDPOINT,
                params={
                    "q": query,
                    "count": self.settings.result_count,
                    "safesearch": "strict",
                    "text_decorations": "false",
                },
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self.settings.api_key.get_secret_value(),
                },
                follow_redirects=False,
                timeout=self.settings.timeout_seconds,
            ) as response:
                if response.status_code in (401, 403):
                    raise SearchAuthenticationError(
                        "The search provider rejected the configured credential."
                    )
                if response.status_code == 429:
                    raise SearchRateLimited(
                        "The search provider rate limit was reached. Try again later."
                    )
                if response.status_code != 200:
                    raise SearchUnavailable(
                        "The search provider could not complete this request."
                    )
                content = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    content.extend(chunk)
                    if len(content) > self.settings.max_response_bytes:
                        raise SearchUnavailable(
                            "Search response exceeded the configured size bound."
                        )
        except httpx.HTTPError:
            raise SearchUnavailable(
                "The search provider could not be reached."
            ) from None
        try:
            payload = json.loads(content)
            if not isinstance(payload, dict):
                raise ValueError
            web = payload.get("web")
            if web is None:
                web = {}
            if not isinstance(web, dict) or not isinstance(
                web.get("results", []), list
            ):
                raise ValueError
        except (ValueError, TypeError):
            raise SearchUnavailable(
                "The search provider returned an invalid response."
            ) from None
        results: list[SearchResult] = []
        seen: set[str] = set()
        discarded = 0
        for raw in web.get("results", [])[: self.settings.result_count]:
            try:
                hit = _BraveHit.model_validate(raw)
                result = SearchResult(
                    title=plain_text(hit.title)[:256],
                    url=HttpUrl(hit.url),
                    snippet=plain_text(hit.description or "")[
                        : self.settings.max_snippet_chars
                    ],
                    retrieved_at=utcnow(),
                )
            except (ValidationError, ValueError):
                discarded += 1
                continue
            if str(result.url) in seen:
                discarded += 1
                continue
            seen.add(str(result.url))
            results.append(result)
        return SearchResponse(results=tuple(results), discarded_results=discarded)
