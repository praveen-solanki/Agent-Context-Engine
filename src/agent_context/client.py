"""Small async Python transport adapter with bounded idempotent retries."""

from __future__ import annotations

import asyncio

import httpx
from pydantic import BaseModel

from agent_context.assembly import AssembleRequest, ContextBundle
from agent_context.contracts import EventInput, EventStatus
from agent_context.handoff import HandoffArtifact, HandoffInput, ResumeResult


class AgentContextClient:
    """Callers own the client lifetime; secret headers are never included in logs."""

    def __init__(
        self,
        *,
        base_url: str,
        bearer_token: str,
        timeout_seconds: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if len(bearer_token) < 32:
            raise ValueError(
                "use a high-entropy bearer token of at least 32 characters"
            )
        self.http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_seconds,
            headers={"Authorization": f"Bearer {bearer_token}"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _post[M: BaseModel](
        self, path: str, payload: BaseModel, schema: type[M]
    ) -> M:
        for attempt in range(3):
            try:
                response = await self.http.post(
                    path, json=payload.model_dump(mode="json")
                )
            except httpx.TransportError:
                if attempt == 2:
                    raise
            else:
                if response.status_code not in (429, 502, 503, 504) or attempt == 2:
                    response.raise_for_status()
                    return schema.model_validate(response.json())
            await asyncio.sleep(0.1 * 2**attempt)
        raise RuntimeError("unreachable retry state")

    async def record_events(self, event: EventInput) -> EventStatus:
        return await self._post("/v1/events", event, EventStatus)

    async def assemble_context(self, request: AssembleRequest) -> ContextBundle:
        return await self._post("/v1/context/assemble", request, ContextBundle)

    async def prepare_handoff(self, request: HandoffInput) -> HandoffArtifact:
        return await self._post("/v1/handoffs", request, HandoffArtifact)

    async def resume_handoff(
        self, identifier: str, *, expected_version: int, request: AssembleRequest
    ) -> ResumeResult:
        from agent_context.api import ResumeInput

        return await self._post(
            f"/v1/handoffs/{identifier}/resume",
            ResumeInput(expected_version=expected_version, assembly=request),
            ResumeResult,
        )
