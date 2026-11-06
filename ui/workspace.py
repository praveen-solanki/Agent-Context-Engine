"""UI application adapter: server-backed navigation, history and memory controls."""

from __future__ import annotations

import json
import hashlib
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

import httpx

from agent_context.assembly import ContextBundle, ContextItem, SearchRequest
from agent_context.assembly import SearchResult as ContextSearch
from agent_context.client import AgentContextClient
from agent_context.continuity import (
    PROJECT_TASK_ID,
    WorkspaceAssistant,
    WorkspaceTurn,
    successful_actions,
)
from agent_context.contracts import Contract, EventInput, EventKind, Stream
from agent_context.demo import ResearchAssistant, ResearchTurn
from agent_context.governance import RevocationInput
from agent_context.navigation import (
    ProjectCreate,
    ProjectDirectory,
    ProjectEdit,
    ProjectEntry,
    SessionPage,
)
from agent_context.project_routing import ProjectResolver
from agent_context.search import SearchResult
from agent_context.task_state import TaskState
from context_graph.config import Settings
from context_graph.providers.chat_backend import ChatLLMProvider


@dataclass(frozen=True)
class ConversationTurn:
    message: str
    result: ResearchTurn
    sources: tuple[SearchResult, ...] = ()
    recorded: bool = False
    event_id: str | None = None


class PendingTurn(Contract):
    project_id: str
    session_id: str
    turn_id: str
    message: str
    sequence: int
    correction: bool = False
    correction_target: RevocationInput | None = None
    routed: bool = False
    manual: bool = False
    documents: dict[str, str] | None = None
    source_snapshots: tuple[SearchResult, ...] = ()
    require_sources: bool = False


@dataclass(frozen=True)
class WorkspaceSnapshot:
    directory: ProjectDirectory
    project_id: str
    session_id: str
    sessions: SessionPage
    stream: Stream | None
    history: tuple[ConversationTurn, ...]
    memory: ContextSearch
    task: TaskState | None
    pending: PendingTurn | None = None


@dataclass(frozen=True)
class PreparedTurn:
    snapshot: WorkspaceSnapshot
    pending: PendingTurn
    clarification: str | None = None
    candidates: tuple[ProjectEntry, ...] = ()


def client(variable: str = "ACE_DEMO_USER_TOKEN") -> AgentContextClient:
    token = os.environ.get(variable)
    if not token:
        raise ValueError("workspace credentials are not configured")
    return AgentContextClient(
        base_url=os.environ.get("ACE_API_URL", "http://127.0.0.1:8000"),
        bearer_token=token,
        timeout_seconds=35,
    )


def restore(stream: Stream) -> tuple[tuple[ConversationTurn, ...], PendingTurn | None]:
    """Use durable turns; never label today's memory as a historical selection."""
    users: dict[str, EventInput] = {}
    answered: set[str] = set()
    result: list[ConversationTurn] = []
    last_user: EventInput | None = None
    for record in stream.events:
        event = record.event
        if event.kind in (EventKind.USER_MESSAGE, EventKind.CORRECTION):
            users[event.event_id] = event
            last_user = event
        elif event.kind == EventKind.ASSISTANT_MESSAGE:
            # Explicit links must identify an earlier user turn. Falling back
            # would misattribute malformed/foreign links and hide pending work.
            source = users.get(event.causation_id) if event.causation_id else last_user
            if source is None:
                continue
            answered.add(source.event_id)
            receipts = successful_actions(stream, source.event_id)
            sources: list[SearchResult] = []
            for action in receipts:
                tool = next(
                    row.event
                    for row in stream.events
                    if row.event.event_id == action.result_event_id
                )
                try:
                    data = json.loads(tool.text)
                    source_snapshot = SearchResult.model_validate(
                        {
                            "title": data["title"],
                            "url": data["url"],
                            "snippet": data["search_excerpt"],
                            "retrieved_at": data["retrieved_at"],
                        }
                    )
                except (ValueError, KeyError, TypeError):
                    continue
                if source_snapshot.document_id == tool.correlation_id:
                    sources.append(source_snapshot)
            bundle = ContextBundle(
                bundle_id="recorded-" + event.event_id,
                tokenizer_version="utf8-byte-bound-v1",
                items=(),
                rendered="",
                token_count=0,
                exclusions=(),
                excluded_counts={},
            )
            result.append(
                ConversationTurn(
                    source.text,
                    ResearchTurn(
                        answer=event.text,
                        bundle=bundle,
                        completed=receipts,
                        next_sequence=len(stream.events) + 1,
                        cached=True,
                        citations=event.citations,
                        suggested_next_steps=event.suggested_next_steps,
                        task_context=event.task_context,
                    ),
                    tuple(sources),
                    True,
                    source.event_id,
                )
            )
    unfinished = [event for key, event in users.items() if key not in answered]
    pending = None
    if unfinished:
        source = unfinished[-1]
        if source.correlation_id and stream.project_id:
            pending = PendingTurn(
                project_id=stream.project_id,
                session_id=stream.session_id,
                turn_id=source.correlation_id,
                message=source.text,
                sequence=source.sequence,
                correction=source.kind == EventKind.CORRECTION,
                correction_target=source.correction_target,
                routed=True,
            )
    return tuple(result), pending


async def load(
    project_id: str | None = None, session_id: str | None = None
) -> WorkspaceSnapshot:
    user = client()
    try:
        directory = await user.projects()
        projects = {project.project_id for project in directory.projects}
        if not projects and project_id is None:
            await user.personal_project()
            directory = await user.projects()
            projects = {project.project_id for project in directory.projects}
        if not projects:
            raise PermissionError("no authorized workspace projects")
        selected = project_id or directory.projects[0].project_id
        if selected not in projects:
            raise PermissionError("project is not accessible")
        sessions = await user.sessions(selected)
        identifier = session_id or (
            sessions.sessions[0].session_id
            if sessions.sessions
            else "console-" + uuid4().hex[:16]
        )
        try:
            stream = await user.session(identifier)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            stream = None
        if stream and stream.project_id != selected:
            raise PermissionError("conversation belongs to another project")
        memory = await user.search_context(
            SearchRequest(
                agent_id="research-agent",
                session_id=identifier,
                project_id=selected,
                query="",
                limit=20,
            )
        )
        try:
            task = await user.current_task(selected, PROJECT_TASK_ID)
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
            task = None
        history, pending = restore(stream) if stream else ((), None)
        return WorkspaceSnapshot(
            directory,
            selected,
            identifier,
            sessions,
            stream,
            history,
            memory,
            task,
            pending,
        )
    finally:
        await user.aclose()


async def send(
    snapshot: WorkspaceSnapshot,
    pending: PendingTurn,
    documents: dict[str, str],
    *,
    require_sources: bool = False,
) -> WorkspaceTurn:
    if (pending.project_id, pending.session_id) != (
        snapshot.project_id,
        snapshot.session_id,
    ):
        raise PermissionError("request belongs to another conversation")
    if not pending.routed:
        raise ValueError("resolve the project before recording the request")
    async with AsyncExitStack() as resources:
        user = client()
        resources.push_async_callback(user.aclose)
        host = client("ACE_DEMO_AGENT_TOKEN")
        resources.push_async_callback(host.aclose)
        settings = Settings()
        llm = ChatLLMProvider(
            backend=settings.chat, llm=settings.llm, retry=settings.retry
        )
        resources.push_async_callback(llm.aclose)
        assistant = WorkspaceAssistant(
            user=user,
            host=host,
            llm=llm,
            project_id=snapshot.project_id,
            documents=pending.documents if pending.documents is not None else documents,
            require_sources=pending.require_sources
            if pending.documents is not None
            else require_sources,
            track_task=next(
                (
                    entry.kind != "personal"
                    for entry in snapshot.directory.projects
                    if entry.project_id == snapshot.project_id
                ),
                True,
            ),
        )
        return await assistant.turn(
            session_id=snapshot.session_id,
            turn_id=pending.turn_id,
            message=pending.message,
            sequence=pending.sequence,
            correction=pending.correction,
            correction_target=pending.correction_target,
        )


async def more_sessions(snapshot: WorkspaceSnapshot) -> SessionPage:
    user = client()
    try:
        return await user.sessions(
            snapshot.project_id, cursor=snapshot.sessions.next_cursor
        )
    finally:
        await user.aclose()


async def more_memory(snapshot: WorkspaceSnapshot) -> ContextSearch:
    user = client()
    try:
        return await user.search_context(
            SearchRequest(
                agent_id="research-agent",
                session_id=snapshot.session_id,
                project_id=snapshot.project_id,
                query="",
                limit=20,
                cursor=snapshot.memory.next_cursor,
            )
        )
    finally:
        await user.aclose()


async def rename(session_id: str, title: str) -> None:
    user = client()
    try:
        await user.rename_session(session_id, title)
    finally:
        await user.aclose()


async def remove(item: ContextItem) -> None:
    if not item.fingerprint:
        raise ValueError("memory does not have a revocable fingerprint")
    user = client()
    try:
        await user.revoke(
            RevocationInput(item_id=item.item_id, expected_fingerprint=item.fingerprint)
        )
    finally:
        await user.aclose()


async def evidence(item_id: str) -> list[dict[str, object]]:
    user = client()
    try:
        return await user.evidence(item_id)
    finally:
        await user.aclose()


async def source_event(
    session_id: str, event_id: str, project_id: str
) -> dict[str, Any]:
    user = client()
    try:
        stream = await user.session(session_id)
        if stream.project_id != project_id:
            raise PermissionError("evidence belongs to another project")
        record = next(
            (record for record in stream.events if record.event.event_id == event_id),
            None,
        )
        if record is None:
            raise LookupError("evidence no longer exists")
        return {
            "text": record.event.text,
            "actor_kind": record.actor_kind,
            "event_kind": record.event.kind.value,
            "recorded_at": record.event.event_time.isoformat(),
            "tool_succeeded": record.event.tool_succeeded,
            "event_id": event_id,
        }
    finally:
        await user.aclose()


async def prepare(
    snapshot: WorkspaceSnapshot,
    pending: PendingTurn,
    *,
    selected_project_id: str | None = None,
    new_project_name: str | None = None,
) -> PreparedTurn:
    """Resolve before persistence, and freeze the chosen scope for all retries."""
    if new_project_name is not None and (selected_project_id or pending.routed):
        raise ValueError("choose an existing project or confirm a new one, not both")
    if (pending.project_id, pending.session_id) != (
        snapshot.project_id,
        snapshot.session_id,
    ):
        raise PermissionError("request belongs to another conversation")
    if pending.routed:
        if selected_project_id and selected_project_id != pending.project_id:
            raise ValueError(
                "a routed request cannot be reassigned; start a new conversation"
            )
        return PreparedTurn(snapshot, pending)
    if snapshot.stream:
        identifier = ResearchAssistant.event_identifier(
            snapshot.session_id, pending.turn_id
        )
        recorded = next(
            (
                item.event
                for item in snapshot.stream.events
                if item.event.event_id == identifier
            ),
            None,
        )
        if recorded:
            if recorded.text != pending.message:
                raise ValueError("turn ID cannot be reused for a different message")
            return PreparedTurn(snapshot, pending.model_copy(update={"routed": True}))
    if pending.correction_target is not None:
        return PreparedTurn(
            snapshot, pending.model_copy(update={"routed": True, "manual": True})
        )
    async with AsyncExitStack() as resources:
        user = client()
        resources.push_async_callback(user.aclose)
        directory: ProjectDirectory | None = None
        if new_project_name is not None:
            directory = await user.projects()
            chosen = await user.create_project(
                ProjectCreate(
                    title=new_project_name.strip(),
                    name_quote=new_project_name.strip(),
                    source_text=pending.message,
                    idempotency_key=pending.turn_id,
                    expected_revision=directory.revision,
                )
            )
            directory = await user.projects()
        elif pending.manual or selected_project_id:
            directory = await user.projects()
            identifier = selected_project_id or snapshot.project_id
            chosen = next(
                (
                    entry
                    for entry in directory.projects
                    if entry.project_id == identifier
                ),
                None,
            )
            if chosen is None:
                raise PermissionError("selected project is not accessible")
        else:
            settings = Settings()
            llm = ChatLLMProvider(
                backend=settings.chat, llm=settings.llm, retry=settings.retry
            )
            resources.push_async_callback(llm.aclose)
            decision = await ProjectResolver(user, llm).resolve(
                message=pending.message,
                request_id=pending.turn_id,
                current_project_id=snapshot.project_id
                if snapshot.stream and snapshot.stream.events
                else None,
            )
            if decision.project is None:
                return PreparedTurn(
                    snapshot, pending, decision.clarification, decision.candidates
                )
            chosen = decision.project
        host = client("ACE_DEMO_AGENT_TOKEN")
        resources.push_async_callback(host.aclose)
        if chosen.project_id not in {
            entry.project_id for entry in (await host.projects()).projects
        }:
            raise PermissionError("configured host cannot access the selected project")
        if chosen.project_id == snapshot.project_id:
            current = replace(
                snapshot,
                directory=directory if directory is not None else await user.projects(),
            )
            return PreparedTurn(
                current,
                pending.model_copy(
                    update={
                        "routed": True,
                        "manual": pending.manual
                        or selected_project_id is not None
                        or new_project_name is not None,
                    }
                ),
            )
        session = (
            "auto-"
            + hashlib.sha256(
                (pending.turn_id + ":" + chosen.project_id).encode()
            ).hexdigest()[:32]
        )
        current = await load(chosen.project_id, session)
        bound = pending.model_copy(
            update={
                "project_id": chosen.project_id,
                "session_id": session,
                "sequence": len(current.stream.events) + 1 if current.stream else 1,
                "routed": True,
                "manual": pending.manual
                or selected_project_id is not None
                or new_project_name is not None,
            }
        )
        return PreparedTurn(current, bound)


async def edit_project(project_id: str, request: ProjectEdit) -> ProjectEntry:
    user = client()
    try:
        return await user.edit_project(project_id, request)
    finally:
        await user.aclose()
