"""Exclusive scratch-store lifecycle and the real API/outbox/ingestion path."""

from __future__ import annotations

import math
import secrets
from datetime import timedelta
from hashlib import sha256
from typing import Any, cast

import httpx
from neo4j import AsyncGraphDatabase, AsyncManagedTransaction
from pymongo import AsyncMongoClient

from agent_context.api import create_app
from agent_context.assembly import (
    AssembleRequest,
    AssemblySettings,
    ContextAssembler,
    TokenBudget,
)
from agent_context.benchmarks.models import (
    BenchmarkError,
    Case,
    ContextView,
    Experiment,
)
from agent_context.benchmarks.providers import Providers
from agent_context.benchmarks.storage import fingerprint
from agent_context.bridge import EventWorker, scoped_id
from agent_context.client import AgentContextClient
from agent_context.contracts import EventInput, EventKind, Permission, Principal, utcnow
from agent_context.event_store import MongoEventStore
from agent_context.governance import GovernanceService
from agent_context.handoff import ArtifactRef, CompletedAction, HandoffService
from agent_context.retrieval import Neo4jCandidateSource
from context_graph.config import Settings
from context_graph.graph.neo4j_store import Neo4jGraphStore
from context_graph.ledger.mongo import MongoLedger
from context_graph.pipeline.orchestrator import IngestionPipeline
from retrieval_tester.retrieval import Neo4jContextRetriever


class ScratchWorkspace:
    """Never adopt populated stores. Retain claims after an abrupt process kill.

    A reset is permitted only with matching exclusive claims in both stores.
    These are benchmark resources, not production erasure or distributed fencing.
    """

    def __init__(self, settings: Settings, run_id: str) -> None:
        if not settings.mongo.database.startswith("ace_benchmark_"):
            raise BenchmarkError(
                "benchmark Mongo database must start with ace_benchmark_"
            )
        self.settings, self.run_id = settings, run_id
        self.mongo: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(
            settings.mongo.uri, tz_aware=True, serverSelectionTimeoutMS=5000
        )
        self.db = self.mongo[settings.mongo.database]
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j.uri,
            auth=(settings.neo4j.user, settings.neo4j.password.get_secret_value()),
            notifications_min_severity="OFF",
        )
        self.claimed = False

    async def claim(self) -> None:
        inserted = False
        try:
            for name in await self.db.list_collection_names():
                if await self.db[name].find_one({}) is not None:
                    raise BenchmarkError(
                        "benchmark requires empty Mongo and graph stores"
                    )
            await self.db["ace_benchmark_workspace"].insert_one(
                {"_id": "exclusive", "run_id": self.run_id}
            )
            inserted = True
            await self.driver.execute_query(
                "CREATE CONSTRAINT ace_benchmark_workspace_unique IF NOT EXISTS FOR(w:ACEBenchmarkWorkspace) REQUIRE w.key IS UNIQUE",
                database_=self.settings.neo4j.database,
            )

            async def reserve(tx: AsyncManagedTransaction) -> None:
                result = await tx.run("MATCH(n) RETURN count(n) AS count")
                count = await result.single()
                if count is None or count["count"]:
                    raise BenchmarkError("benchmark refuses a populated graph")
                await tx.run(
                    "CREATE(w:ACEBenchmarkWorkspace {key:'exclusive',run_id:$run})",
                    run=self.run_id,
                )

            async with self.driver.session(
                database=self.settings.neo4j.database
            ) as session:
                await session.execute_write(reserve)
            self.claimed = True
        except BaseException:
            if inserted:
                await self.db["ace_benchmark_workspace"].delete_one(
                    {"_id": "exclusive", "run_id": self.run_id}
                )
            raise

    async def require_owner(self) -> None:
        mongo = await self.db["ace_benchmark_workspace"].find_one(
            {"_id": "exclusive", "run_id": self.run_id}
        )
        rows, _, _ = await self.driver.execute_query(
            "MATCH(w:ACEBenchmarkWorkspace {key:'exclusive',run_id:$run}) RETURN w.run_id AS owner",
            run=self.run_id,
            database_=self.settings.neo4j.database,
        )
        if mongo is None or len(rows) != 1:
            raise PermissionError("exclusive benchmark workspace claim is absent")

    async def reset(self) -> None:
        await self.require_owner()
        while True:
            rows, _, _ = await self.driver.execute_query(
                "MATCH(w:ACEBenchmarkWorkspace {key:'exclusive',run_id:$run}) MATCH(n) WHERE n<>w WITH n LIMIT 500 DETACH DELETE n RETURN count(*) AS removed",
                run=self.run_id,
                database_=self.settings.neo4j.database,
            )
            if not rows or rows[0]["removed"] == 0:
                break
        for name in await self.db.list_collection_names():
            if name != "ace_benchmark_workspace":
                await self.db[name].delete_many({})

    async def release(self) -> None:
        await self.reset()
        await self.driver.execute_query(
            "MATCH(w:ACEBenchmarkWorkspace {key:'exclusive',run_id:$run}) DELETE w",
            run=self.run_id,
            database_=self.settings.neo4j.database,
        )
        await self.db["ace_benchmark_workspace"].delete_one(
            {"_id": "exclusive", "run_id": self.run_id}
        )
        self.claimed = False

    async def close(self) -> None:
        await self.driver.close()
        await self.mongo.close()


def split_text(text: str, limit: int = 14000) -> list[str]:
    """Event limits are bytes. Preserve every character and split UTF-8 safely."""
    result: list[str] = []
    current: list[str] = []
    size = 0
    for character in text:
        length = len(character.encode())
        if size + length > limit:
            result.append("".join(current))
            current, size = [], 0
        current.append(character)
        size += length
    if current:
        result.append("".join(current))
    return result


class ACEBackend:
    """In-process authenticated HTTP and worker, same production components.

    Direct legacy retrieval is used only as the named baseline. Models and
    primary stores are real unless explicitly injected by a test.
    """

    def __init__(
        self, workspace: ScratchWorkspace, providers: Providers, experiment: Experiment
    ) -> None:
        self.workspace, self.providers, self.experiment = (
            workspace,
            providers,
            experiment,
        )
        self.clock = utcnow()
        self.user: AgentContextClient | None = None
        self.agent: AgentContextClient | None = None
        self.aliases: dict[str, str] = {}
        self.session_aliases: dict[str, str] = {}
        self.history_key: str | None = None

    async def close_case(self) -> None:
        if self.user:
            await self.user.aclose()
        if self.agent:
            await self.agent.aclose()
        self.user = self.agent = None

    async def ingest(self, case: Case) -> dict[str, object]:
        key = fingerprint(
            [
                case.subject_id,
                [session.model_dump(mode="json") for session in case.sessions],
            ]
        )
        if key == self.history_key and self.user is not None:
            self.clock = (
                (
                    case.question_time
                    or max(t.timestamp for s in case.sessions for t in s.turns)
                    + timedelta(microseconds=1)
                )
                if self.experiment.time_mode == "dataset"
                else utcnow()
            )
            return {"reused_identical_history": True, "clock": self.clock.isoformat()}
        self.history_key = None
        await self.close_case()
        await self.workspace.reset()
        tenant = "bench-" + fingerprint([self.workspace.run_id, case.id])[:24]
        principal = Principal(
            tenant_id=tenant,
            user_id="subject",
            actor_id="subject",
            projects=frozenset({"benchmark"}),
            permissions=frozenset(Permission),
        )
        agent = principal.model_copy(
            update={"actor_id": "benchmark-agent", "actor_kind": "agent"}
        )
        events = MongoEventStore(
            self.workspace.mongo, self.workspace.settings.mongo.database
        )
        await events.ensure_indexes()
        store = Neo4jGraphStore(
            self.workspace.settings.neo4j, driver=self.workspace.driver
        )
        ledger = MongoLedger(self.workspace.settings.mongo, client=self.workspace.mongo)
        pipeline = IngestionPipeline(
            settings=self.workspace.settings,
            store=store,
            ledger=ledger,
            llm=self.providers.llms["ingestion"],
            embeddings=self.providers.passages,
            run_id=self.workspace.run_id,
            clock=lambda: self.clock,
        )
        await pipeline.prepare()
        worker = EventWorker(
            events,
            pipeline.ingest,
            tenant_id=tenant,
            timeout_seconds=self.experiment.ingestion_timeout_seconds,
            lease_seconds=math.ceil(self.experiment.ingestion_timeout_seconds) + 30,
            max_attempts=1,
        )
        source = Neo4jCandidateSource(
            self.workspace.driver,
            database=self.workspace.settings.neo4j.database,
            tenant_id=tenant,
            privacy=events.privacy,
            embeddings=self.providers.queries,
            clock=lambda: self.clock,
        )
        assembler = ContextAssembler(
            source,
            clock=lambda: self.clock,
            settings=AssemblySettings(source_timeout_seconds=60),
        )
        gov = GovernanceService(
            self.workspace.mongo,
            self.workspace.settings.mongo.database,
            self.workspace.driver,
            graph_database=self.workspace.settings.neo4j.database,
        )

        async def deny_action(_: Principal, __: CompletedAction) -> bool:
            return False

        async def deny_artifact(_: Principal, __: ArtifactRef) -> bool:
            return False

        async def ready() -> bool:
            return True

        user_token, agent_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        app = create_app(
            events=events,
            assembler=assembler,
            handoffs=HandoffService(
                self.workspace.mongo,
                self.workspace.settings.mongo.database,
                verify_action=deny_action,
                verify_artifact=deny_artifact,
            ),
            auth_bindings={
                sha256(user_token.encode()).hexdigest(): principal,
                sha256(agent_token.encode()).hexdigest(): agent,
            },
            ready=ready,
            governance=gov,
        )
        self.user = AgentContextClient(
            base_url="http://benchmark",
            bearer_token=user_token,
            transport=httpx.ASGITransport(app=app),
            timeout_seconds=65,
        )
        self.agent = AgentContextClient(
            base_url="http://benchmark",
            bearer_token=agent_token,
            transport=httpx.ASGITransport(app=app),
            timeout_seconds=65,
        )
        self.principal = principal
        self.aliases, self.session_aliases = {}, {}
        streams = turns = 0
        for session in case.sessions:
            payloads = [
                (turn, part, pi)
                for turn in session.turns
                for pi, part in enumerate(split_text(turn.text))
            ]
            for offset in range(0, len(payloads), events.max_events - 1):
                external = "s-" + fingerprint([case.id, session.id, offset])[:32]
                self.session_aliases[scoped_id(tenant, external)] = session.id
                chunk = payloads[offset : offset + events.max_events - 1]
                for sequence, (turn, text, part) in enumerate(chunk, 1):
                    identifier = "e-" + fingerprint([case.id, turn.id, part])[:32]
                    self.aliases[scoped_id(tenant, identifier)] = turn.id
                    kind = {
                        "user": EventKind.USER_MESSAGE,
                        "assistant": EventKind.ASSISTANT_MESSAGE,
                        "tool": EventKind.TOOL_RESULT,
                    }[turn.role]
                    caller = self.user if turn.role == "user" else self.agent
                    await caller.record_events(
                        EventInput(
                            event_id=identifier,
                            session_id=external,
                            agent_id="benchmark-agent",
                            sequence=sequence,
                            event_time=turn.timestamp,
                            kind=kind,
                            text=text,
                            project_id="benchmark",
                        )
                    )
                    turns += 1
                self.clock = (
                    chunk[-1][0].timestamp
                    if self.experiment.time_mode == "dataset"
                    else utcnow()
                )
                last = "close-" + fingerprint([case.id, session.id, offset])[:32]
                await self.user.record_events(
                    EventInput(
                        event_id=last,
                        session_id=external,
                        agent_id="benchmark-agent",
                        sequence=len(chunk) + 1,
                        event_time=chunk[-1][0].timestamp,
                        kind=EventKind.SESSION_CLOSE,
                        project_id="benchmark",
                    )
                )
                if not await worker.run_once():
                    raise RuntimeError("benchmark event stream was not claimed")
                await self.user.wait_available(last, timeout_seconds=2)
                streams += 1
        self.clock = (
            (
                case.question_time
                or max(t.timestamp for s in case.sessions for t in s.turns)
                + timedelta(microseconds=1)
            )
            if self.experiment.time_mode == "dataset"
            else utcnow()
        )
        self.history_key = key
        return {
            "streams": streams,
            "message_events": turns,
            "clock": self.clock.isoformat(),
            "time_mode": self.experiment.time_mode,
        }

    async def ace(self, case: Case, budget: int) -> ContextView:
        if self.user is None:
            raise RuntimeError("case has not been ingested")
        bundle = await self.user.assemble_context(
            AssembleRequest(
                agent_id="benchmark-agent",
                session_id="question",
                project_id="benchmark",
                query=case.question,
                budget=TokenBudget(
                    model_context_tokens=budget + 1024, max_engine_tokens=budget
                ),
            )
        )
        turns: set[str] = set()
        sessions: set[str] = set()
        for item in bundle.items:
            for episode in await self.user.evidence(item.item_id):
                sid = self.session_aliases.get(str(episode["session_id"]))
                if sid:
                    sessions.add(sid)
                for span in cast(list[dict[str, Any]], episode["spans"]):
                    original = self.aliases.get(span["message_id"])
                    if original:
                        turns.add(original)
        return ContextView(
            text=bundle.rendered,
            source_turns=tuple(sorted(turns)),
            source_sessions=tuple(sorted(sessions)),
        )

    async def legacy(self, case: Case) -> str:
        retriever = Neo4jContextRetriever(
            self.workspace.settings.neo4j,
            embeddings=self.providers.queries,
            driver=self.workspace.driver,
            clock=lambda: self.clock,
        )
        result = await retriever.retrieve(
            scoped_id(self.principal.tenant_id, self.principal.user_id), case.question
        )
        return result.as_prompt_block()
