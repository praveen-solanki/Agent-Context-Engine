"""Explicit single-trust-partition API and worker processes with bounded lifetimes."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

import uvicorn
from fastapi import FastAPI
from neo4j import AsyncGraphDatabase
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from pymongo import AsyncMongoClient
from typing_extensions import Self

from agent_context.api import create_app
from agent_context.artifacts import ArtifactStore
from agent_context.assembly import AssemblySettings, ContextAssembler
from agent_context.bridge import EventWorker, scoped_id
from agent_context.contracts import Identifier, Permission, Principal
from agent_context.event_store import MongoEventStore
from agent_context.governance import GovernanceService
from agent_context.handoff import HandoffService
from agent_context.maintenance import ProjectMaintenance
from agent_context.outcomes import EventOutcomeVerifier
from agent_context.project_store import ProjectStore
from agent_context.retrieval import Neo4jCandidateSource
from agent_context.task_state import TaskCandidateSource, TaskStateService
from context_graph.config import Settings
from context_graph.observability import configure_logging
from context_graph.providers.chat_backend import ChatLLMProvider, EmbeddingProviderImpl
from context_graph.tool import ContextGraphIngestion


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ACE_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    tenant_id: Identifier = ""
    user_id: Identifier = ""
    auth_bindings: Annotated[dict[str, Principal], NoDecode] = Field(
        default_factory=dict
    )
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    run_version: str = "v1"
    poll_seconds: float = Field(default=0.5, gt=0, le=30)
    semantic_retrieval: bool = True
    source_timeout_seconds: float = Field(default=30, gt=0, le=60)

    @field_validator("auth_bindings", mode="before")
    @classmethod
    def parse_bindings(cls, value: object) -> object:
        # Select one complete highest-priority registry. Deep merging .env and
        # process JSON can retain obsolete identities from another partition.
        return json.loads(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_partition(self) -> Self:
        # The legacy concept resolver is not tenant/user-partitioned. Until it
        # is migrated, each deployment must have an isolated Neo4j database and
        # Mongo database for one user/trust partition. No silent multi-tenancy.
        for principal in self.auth_bindings.values():
            if (principal.tenant_id, principal.user_id) != (
                self.tenant_id,
                self.user_id,
            ):
                raise ValueError(
                    "auth bindings must belong to the deployment trust partition"
                )
        return self


def application() -> FastAPI:
    """Uvicorn factory; secrets remain in inherited environment/ignored .env."""
    runtime, settings = RuntimeSettings(), Settings()
    configure_logging(settings.log_level, settings.log_file)
    mongo: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        settings.mongo.uri, tz_aware=True, serverSelectionTimeoutMS=3000
    )
    driver = AsyncGraphDatabase.driver(
        settings.neo4j.uri,
        auth=(settings.neo4j.user, settings.neo4j.password.get_secret_value()),
    )
    events = MongoEventStore(mongo, settings.mongo.database)
    projects = ProjectStore(mongo, settings.mongo.database)

    artifacts = ArtifactStore(mongo, settings.mongo.database)
    governance = GovernanceService(
        mongo, settings.mongo.database, driver, graph_database=settings.neo4j.database
    )

    handoffs = HandoffService(
        mongo,
        settings.mongo.database,
        verify_action=EventOutcomeVerifier(events),
        verify_artifact=artifacts.verify,
    )
    tasks = TaskStateService(handoffs, events)
    embeddings = (
        EmbeddingProviderImpl(
            embedding=settings.embedding, retry=settings.retry, for_query=True
        )
        if runtime.semantic_retrieval
        else None
    )
    source = Neo4jCandidateSource(
        driver,
        database=settings.neo4j.database,
        tenant_id=runtime.tenant_id,
        privacy=events.privacy,
        embeddings=embeddings,
    )

    async def ready() -> bool:
        await mongo.admin.command("ping")
        records, _, _ = await driver.execute_query(
            "RETURN 1 AS ok", database_=settings.neo4j.database
        )
        return records[0]["ok"] == 1

    app = create_app(
        events=events,
        assembler=ContextAssembler(
            source,
            required_sources=(TaskCandidateSource(tasks),),
            settings=AssemblySettings(
                source_timeout_seconds=runtime.source_timeout_seconds,
            ),
        ),
        handoffs=handoffs,
        auth_bindings=runtime.auth_bindings,
        ready=ready,
        artifacts=artifacts,
        governance=governance,
        tasks=tasks,
        project_store=projects,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
        async def maintenance() -> None:
            actor = Principal(
                tenant_id=runtime.tenant_id,
                user_id=runtime.user_id,
                actor_id="ace-maintenance",
                permissions=frozenset({Permission.DELETE}),
            )
            while True:
                try:
                    status = await governance.erasure_status(actor)
                    if status["state"] == "quarantined":
                        await governance.purge(actor)
                except LookupError:
                    pass
                except Exception as error:
                    logging.getLogger(__name__).error(
                        "erasure_maintenance_failed",
                        extra={"error_type": type(error).__name__},
                    )
                await asyncio.sleep(runtime.poll_seconds)

        task: asyncio.Task[None] | None = None
        try:
            await events.ensure_indexes()
            await projects.ensure_indexes()
            await handoffs.ensure_indexes()
            await artifacts.ensure_indexes()
            await governance.ensure_indexes()
            task = asyncio.create_task(maintenance())
            yield
        finally:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await driver.close()
            await mongo.close()
            if embeddings:
                await embeddings.aclose()

    app.router.lifespan_context = lifespan
    return app


def api_main() -> None:
    runtime = RuntimeSettings()
    uvicorn.run(
        "agent_context.runtime:application",
        factory=True,
        host=runtime.host,
        port=runtime.port,
        log_level="info",
        access_log=False,
    )


async def run_worker() -> None:
    runtime, settings = RuntimeSettings(), Settings()
    if settings.chat.api_key.get_secret_value() in ("", "local-dev", "change-me"):
        raise ValueError(
            "configure a model credential securely before starting the worker"
        )
    settings = settings.model_copy(
        update={
            "run_id": scoped_id(
                runtime.tenant_id, f"{runtime.user_id}:events:{runtime.run_version}"
            )
        }
    )
    async with AsyncMongoClient[dict[str, object]](
        settings.mongo.uri, tz_aware=True
    ) as mongo:
        events = MongoEventStore(mongo, settings.mongo.database)
        await events.ensure_indexes()
        async with ContextGraphIngestion.from_settings(settings) as ingestion:
            # Reuse the public API, including its resource ownership and retry caches.
            from context_graph.domain.conversation import SessionInput
            from context_graph.pipeline.orchestrator import IngestionReport
            from context_graph.tool import IngestionRequest

            async def ingest_session(session: SessionInput) -> IngestionReport:
                return await ingestion.ingest_conversation(
                    IngestionRequest(session=session)
                )

            artifacts = ArtifactStore(mongo, settings.mongo.database)
            handoffs = HandoffService(
                mongo,
                settings.mongo.database,
                verify_action=EventOutcomeVerifier(events),
                verify_artifact=artifacts.verify,
            )
            await handoffs.ensure_indexes()
            projects = ProjectStore(mongo, settings.mongo.database)
            await projects.ensure_indexes()
            tasks = TaskStateService(handoffs, events)
            planner = ChatLLMProvider(
                backend=settings.chat, llm=settings.llm, retry=settings.retry
            )
            try:
                maintenance = ProjectMaintenance(
                    tasks, projects, runtime.auth_bindings, planner
                )
                worker = EventWorker(
                    events,
                    ingest_session,
                    tenant_id=runtime.tenant_id,
                    maintain=maintenance,
                )
                await _worker_loop(worker, runtime.poll_seconds)
            finally:
                await planner.aclose()


async def _worker_loop(worker: EventWorker, poll_seconds: float) -> None:
    while True:
        try:
            did_work = await worker.run_once()
        except Exception as error:
            logging.getLogger(__name__).error(
                "worker_dependency_failure",
                extra={"error_type": type(error).__name__},
            )
            did_work = False
        if not did_work:
            await asyncio.sleep(poll_seconds)


def worker_main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass
