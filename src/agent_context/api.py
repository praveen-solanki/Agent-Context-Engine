"""Authenticated transport over application services; identity never comes from JSON."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agent_context.assembly import (
    AssembleRequest,
    ContextAssembler,
    ContextBundle,
    MandatoryContextTooLarge,
)
from agent_context.contracts import (
    EventInput,
    EventStatus,
    Permission,
    Principal,
    ProcessingState,
)
from agent_context.event_store import MongoEventStore
from agent_context.events import CapacityExceeded, EventConflict
from agent_context.handoff import (
    HandoffArtifact,
    HandoffInput,
    HandoffService,
    ResumeResult,
)


class HTTPBoundary:
    """Cap streamed bodies before parsing; attach a server-generated request ID."""

    def __init__(self, app: ASGIApp, max_body_bytes: int = 131072) -> None:
        self.app, self.maximum = app, max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex.encode()

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []),
                    (b"x-request-id", request_id),
                ]
            await send(message)

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.maximum:
                await JSONResponse({"error": "request_too_large"}, status_code=413)(
                    scope, receive, send_with_id
                )
                return
            if not message.get("more_body", False):
                break
        consumed = False

        async def bounded_receive() -> Message:
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send_with_id)


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    assembly: AssembleRequest


def create_app(
    *,
    events: MongoEventStore,
    assembler: ContextAssembler,
    handoffs: HandoffService,
    auth_bindings: dict[str, Principal],
    ready: Callable[[], Awaitable[bool]],
    watermark_timeout_seconds: float = 5,
) -> FastAPI:
    """Bindings map SHA256(high-entropy bearer token) to server-owned identities."""
    if not auth_bindings or any(len(key) != 64 for key in auth_bindings):
        raise ValueError("explicit SHA-256 authentication bindings are required")
    app = FastAPI(title="Agent Context Engine", version="0.1.0")
    app.add_middleware(HTTPBoundary)

    async def authenticate(request: Request) -> Principal:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or len(token) < 32:
            raise HTTPException(
                401, "authentication required", headers={"WWW-Authenticate": "Bearer"}
            )
        principal = auth_bindings.get(hashlib.sha256(token.encode()).hexdigest())
        if principal is None:
            raise HTTPException(
                401, "invalid authentication", headers={"WWW-Authenticate": "Bearer"}
            )
        return principal

    @app.exception_handler(PermissionError)
    async def forbidden(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    @app.exception_handler(LookupError)
    async def missing(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"error": "not_found"}, status_code=404)

    @app.exception_handler(EventConflict)
    async def conflict(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"error": "precondition_failed"}, status_code=409)

    @app.exception_handler(CapacityExceeded)
    async def capacity(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"error": "capacity_exceeded"}, status_code=413)

    @app.exception_handler(ValueError)
    async def invalid(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"error": "invalid_input"}, status_code=422)

    @app.exception_handler(MandatoryContextTooLarge)
    async def budget(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(
            {"error": "mandatory_context_exceeds_budget"}, status_code=422
        )

    @app.exception_handler(RuntimeError)
    async def unavailable(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"error": "dependency_unavailable"}, status_code=503)

    app.add_exception_handler(TimeoutError, unavailable)

    @app.exception_handler(RequestValidationError)
    async def invalid_contract(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse({"error": "invalid_request_contract"}, status_code=422)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        try:
            healthy = await asyncio.wait_for(ready(), timeout=3)
        except Exception:
            healthy = False
        return JSONResponse(
            {"status": "ready" if healthy else "unavailable"},
            status_code=200 if healthy else 503,
        )

    @app.post("/v1/events", status_code=202)
    async def record(
        body: EventInput, actor: Principal = Depends(authenticate)
    ) -> EventStatus:
        return (await events.record(actor, body)).status()

    @app.get("/v1/events/{event_id}/status")
    async def event_status(
        event_id: str, actor: Principal = Depends(authenticate)
    ) -> EventStatus:
        actor.require(Permission.VIEW)
        metadata = await events.collection.find_one(
            {
                "tenant_id": actor.tenant_id,
                "data.user_id": actor.user_id,
                "event_ids": event_id,
            },
            {"session_id": 1},
        )
        if metadata is None:
            raise LookupError("event not found")
        stream = await events.get(actor, metadata["session_id"])
        status = stream.status()
        if any(
            e.event.event_id == event_id
            and e.event.sequence <= stream.available_sequence
            for e in stream.events
        ):
            status = status.model_copy(update={"state": ProcessingState.AVAILABLE})
        return status

    @app.post("/v1/context/assemble")
    async def assemble(
        body: AssembleRequest, actor: Principal = Depends(authenticate)
    ) -> ContextBundle:
        actor.require(Permission.VIEW, body.project_id)
        if body.minimum_sequence:
            async with asyncio.timeout(watermark_timeout_seconds):
                while (
                    await events.get(actor, body.session_id)
                ).available_sequence < body.minimum_sequence:
                    await asyncio.sleep(0.05)
        return await assembler.assemble(actor, body)

    @app.post("/v1/handoffs")
    async def prepare(
        body: HandoffInput, actor: Principal = Depends(authenticate)
    ) -> HandoffArtifact:
        return await handoffs.prepare(actor, body)

    @app.post("/v1/handoffs/{handoff_id}/resume")
    async def resume(
        handoff_id: str, body: ResumeInput, actor: Principal = Depends(authenticate)
    ) -> ResumeResult:
        return await handoffs.resume(
            actor,
            handoff_id,
            expected_version=body.expected_version,
            request=body.assembly,
            assembler=assembler,
        )

    return app
