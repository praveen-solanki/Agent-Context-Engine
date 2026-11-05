"""Small async Python transport adapter with bounded idempotent retries."""

from __future__ import annotations

import asyncio

import httpx
from pydantic import BaseModel

from agent_context.assembly import (
    AssembleRequest,
    ContextBundle,
    SearchRequest,
    SearchResult,
)
from agent_context.contracts import EventInput, EventStatus, ProcessingState, Stream
from agent_context.handoff import HandoffArtifact, HandoffInput, ResumeResult
from agent_context.task_state import TaskUpdate, TaskState
from agent_context.navigation import (
    ProjectDirectory,
    SessionEntry,
    SessionPage,
    SessionTitle,
)
from agent_context.governance import RevocationInput


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
                    path,
                    json=payload.model_dump(
                        mode="json", exclude_none=True, exclude_defaults=True
                    ),
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

    async def projects(self) -> ProjectDirectory:
        response = await self.http.get("/v1/projects")
        response.raise_for_status()
        return ProjectDirectory.model_validate(response.json())

    async def sessions(
        self, project_id: str, *, cursor: str | None = None, limit: int = 30
    ) -> SessionPage:
        params: dict[str, str | int] = {"project_id": project_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        response = await self.http.get("/v1/sessions", params=params)
        response.raise_for_status()
        return SessionPage.model_validate(response.json())

    async def rename_session(self, session_id: str, title: str) -> SessionEntry:
        from urllib.parse import quote

        return await self._post(
            f"/v1/sessions/{quote(session_id, safe='')}/title",
            SessionTitle(title=title),
            SessionEntry,
        )

    async def revoke(self, request: RevocationInput) -> None:
        response = await self.http.post(
            "/v1/context/revocations", json=request.model_dump(mode="json")
        )
        response.raise_for_status()

    async def session(self, identifier: str) -> Stream:
        from urllib.parse import quote

        response = await self.http.get(f"/v1/sessions/{quote(identifier, safe='')}")
        response.raise_for_status()
        return Stream.model_validate(response.json())

    async def wait_available(
        self, event_id: str, *, timeout_seconds: float = 180
    ) -> EventStatus:
        async with asyncio.timeout(timeout_seconds):
            while True:
                response = await self.http.get(f"/v1/events/{event_id}/status")
                response.raise_for_status()
                status = EventStatus.model_validate(response.json())
                if status.state == ProcessingState.AVAILABLE:
                    return status
                if status.state == ProcessingState.DEAD:
                    raise RuntimeError("event requires dead-letter review/replay")
                await asyncio.sleep(0.25)

    async def assemble_context(self, request: AssembleRequest) -> ContextBundle:
        return await self._post("/v1/context/assemble", request, ContextBundle)

    async def search_context(self, request: SearchRequest) -> SearchResult:
        return await self._post("/v1/context/search", request, SearchResult)

    async def evidence(self, item_id: str) -> list[dict[str, object]]:
        # Item IDs come from typed search/bundle responses. Encode path data so
        # an ID cannot change the requested endpoint.
        from urllib.parse import quote

        response = await self.http.get(
            f"/v1/context/items/{quote(item_id, safe='')}/evidence"
        )
        response.raise_for_status()
        return response.json()

    async def prepare_handoff(self, request: HandoffInput) -> HandoffArtifact:
        return await self._post("/v1/handoffs", request, HandoffArtifact)

    async def update_task(self, request: TaskUpdate) -> TaskState:
        return await self._post("/v1/tasks/state", request, TaskState)

    async def current_task(self, project_id: str, task_id: str) -> TaskState:
        from urllib.parse import quote

        response = await self.http.get(
            f"/v1/tasks/{quote(task_id, safe='')}", params={"project_id": project_id}
        )
        response.raise_for_status()
        return TaskState.model_validate(response.json())

    async def resume_handoff(
        self, identifier: str, *, expected_version: int, request: AssembleRequest
    ) -> ResumeResult:
        from agent_context.api import ResumeInput

        return await self._post(
            f"/v1/handoffs/{identifier}/resume",
            ResumeInput(expected_version=expected_version, assembly=request),
            ResumeResult,
        )
