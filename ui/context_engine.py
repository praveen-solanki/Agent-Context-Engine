"""Persistent conversational workspace over the existing authenticated ACE APIs."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

import httpx
import streamlit as st
from dotenv import load_dotenv

from agent_context.continuity import WorkspaceTurn
from agent_context.contracts import EventKind, Permission
from agent_context.demo import ResearchAssistant
from agent_context.events import EventConflict
from agent_context.governance import RevocationInput
from agent_context.search import (
    BraveSearch,
    SearchError,
    SearchResponse,
    SearchResult,
    SearchSettings,
)
from ui import workspace as service
from ui.context_engine_view import (
    InspectorAction,
    apply_style,
    brand,
    header,
    plain_label,
    render_context,
    render_turn,
    welcome,
)
from ui.workspace import ConversationTurn, PendingTurn, WorkspaceSnapshot

load_dotenv(override=False)
st.set_page_config(
    page_title="Context Engine", page_icon=":material/notes:", layout="wide"
)
apply_style()


def clear_view() -> None:
    for key in (
        "ace_workspace",
        "ace_pending",
        "ace_process_pending",
        "ace_conversation_title",
        "ace_evidence",
        "ace_live_turns",
        "ace_needs_refresh",
        "ace_notice",
        "ace_web_results",
        "ace_search_query",
        "ace_use_web",
    ):
        st.session_state.pop(key, None)
    st.session_state.ace_source_mode = "Project memory"


def navigate(project_id: str, session_id: str | None = None) -> None:
    clear_view()
    st.query_params["project"] = project_id
    if session_id:
        st.query_params["session"] = session_id
    elif "session" in st.query_params:
        del st.query_params["session"]


def new_conversation(project_id: str) -> None:
    navigate(project_id, "console-" + uuid4().hex[:16])


def choose_project() -> None:
    navigate(st.session_state.ace_project_picker)


def save_snapshot(value: WorkspaceSnapshot) -> None:
    pending: PendingTurn | None = st.session_state.get("ace_pending")
    if pending and (pending.project_id, pending.session_id) != (
        value.project_id,
        value.session_id,
    ):
        st.session_state.pop("ace_pending", None)
        st.session_state.pop("ace_process_pending", None)
    st.session_state.ace_workspace = value
    st.query_params["project"] = value.project_id
    st.query_params["session"] = value.session_id
    if value.pending and "ace_pending" not in st.session_state:
        st.session_state.ace_pending = value.pending


def friendly_error(error: Exception) -> str:
    if isinstance(error, EventConflict):
        return "The project plan changed after this request was recorded. Open another conversation and restate the request using the current plan."
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code == 404:
            return "The workspace API needs updating, or this record is no longer available. Restart the updated app with ./run.sh --skip-demo."
        if error.response.status_code in (401, 403):
            return "This workspace is not accessible with the current credentials or project permissions."
        if error.response.status_code == 409:
            return "Project state changed. Refresh the context before retrying."
        if error.response.status_code == 413:
            return "This conversation or project has reached its storage limit. Start a new conversation or review the project state."
    return "This request could not complete. Your recorded conversation is retained; retry or refresh the workspace."


def load_snapshot() -> WorkspaceSnapshot:
    project = st.query_params.get("project")
    session = st.query_params.get("session")
    cached: WorkspaceSnapshot | None = st.session_state.get("ace_workspace")
    if (
        cached
        and (project is None or project == cached.project_id)
        and (session is None or session == cached.session_id)
    ):
        return cached
    if cached is not None:
        clear_view()
    value = asyncio.run(service.load(project, session))
    save_snapshot(value)
    return value


def source_controls() -> tuple[dict[str, str], bool, tuple[SearchResult, ...]]:
    with st.expander("Sources"):
        mode = st.radio(
            "Research source",
            ["Project memory", "Sample brief", "Web search"],
            key="ace_source_mode",
            label_visibility="collapsed",
        )
        if mode == "Project memory":
            st.caption("Use your message and relevant saved project context.")
            return {}, False, ()
        if mode == "Sample brief":
            st.caption("Optional built-in example for comparing two options.")
            return (
                {
                    "research-brief": "Option A costs 10 units and works offline. Option B costs 20 units and requires a network."
                },
                False,
                (),
            )
        settings = SearchSettings()
        if not settings.configured:
            st.caption(
                "Add BRAVE_SEARCH_API_KEY to the server environment or ignored .env file to enable optional web search."
            )
        query = st.text_input("Search query", key="ace_search_query", max_chars=1000)
        if st.button(
            "Search web",
            disabled=not settings.configured or not query.strip(),
            width="stretch",
        ):
            st.session_state.ace_web_results = ()
            st.session_state.ace_use_web = False

            async def search() -> SearchResponse:
                async with BraveSearch(settings) as provider:
                    return await provider.search(query)

            try:
                with st.spinner("Searching…"):
                    response = asyncio.run(search())
                st.session_state.ace_web_results = response.results
                st.session_state.ace_use_web = bool(response.results)
                if not response.results:
                    st.caption("No usable results found.")
            except (SearchError, ValueError):
                st.error(
                    "Search could not complete. Check the key or try another query."
                )
        results: tuple[SearchResult, ...] = st.session_state.get("ace_web_results", ())
        for index, source in enumerate(results):
            st.link_button(
                plain_label(source.title), str(source.url), key=f"web-source-{index}"
            )
        use = st.checkbox("Use these sources", key="ace_use_web", disabled=not results)
        st.caption(
            "Only the search query is sent to search. Results are snippets, not full-page reads."
        )
        chosen = results if use else ()
        return (
            {source.document_id: source.as_document() for source in chosen},
            bool(chosen),
            chosen,
        )


def show_evidence() -> None:
    rows: list[dict[str, object]] = st.session_state.get("ace_evidence", [])
    if not rows:
        return
    with st.expander("Evidence", expanded=True):
        for row in rows:
            if row.get("usable_as_current_context") is False:
                st.warning(
                    "This source is not current. It is shown for inspection only."
                )
            st.text(str(row.get("text", "")))
            role = row.get("actor_kind") or row.get("role") or row.get("source_trust")
            if role:
                st.caption("Source: " + str(role))
            if row.get("observed_at") or row.get("recorded_at"):
                st.caption(str(row.get("observed_at") or row.get("recorded_at")))
            if row.get("truncated"):
                st.caption(
                    "Excerpt is bounded; the full conversation remains in history."
                )
            spans = row.get("spans")
            if spans:
                with st.expander("Exact source spans"):
                    st.json(spans)
        if st.button("Close evidence", key="close-evidence"):
            st.session_state.pop("ace_evidence", None)
            st.rerun()


def queue(
    message: str, snapshot: WorkspaceSnapshot, target: RevocationInput | None = None
) -> None:
    sequence = len(snapshot.stream.events) + 1 if snapshot.stream else 1
    st.session_state.ace_pending = PendingTurn(
        project_id=snapshot.project_id,
        session_id=snapshot.session_id,
        turn_id="ui-" + uuid4().hex,
        message=message,
        sequence=sequence,
        correction=target is not None,
        correction_target=target,
    )
    st.session_state.ace_process_pending = True


try:
    snapshot = load_snapshot()
except Exception as error:  # noqa: BLE001 — UI boundary must not expose provider details.
    brand()
    st.title("Your project workspace")
    st.error(friendly_error(error))
    st.caption(
        "Configure the existing user/host credentials and start the matching API and worker. No conversation is stored only in this page."
    )
    if st.button("Reload workspace"):
        clear_view()
        st.query_params.clear()
        st.rerun()
    st.chat_input("Connect your workspace to start…", disabled=True)
    st.stop()

with st.sidebar:
    brand()
    entries = snapshot.directory.projects
    ids = [entry.project_id for entry in entries]
    labels = {entry.project_id: entry.title for entry in entries}
    st.session_state.ace_project_picker = snapshot.project_id
    st.selectbox(
        "Project",
        ids,
        format_func=lambda value: labels[value],
        key="ace_project_picker",
        on_change=choose_project,
    )
    st.button(
        "New conversation",
        icon=":material/add:",
        width="stretch",
        on_click=new_conversation,
        args=(snapshot.project_id,),
    )
    st.divider()
    st.caption("CONVERSATIONS")
    for entry in snapshot.sessions.sessions:
        st.button(
            plain_label(entry.title),
            key="session-" + entry.session_id,
            width="stretch",
            type="primary" if entry.session_id == snapshot.session_id else "secondary",
            on_click=navigate,
            args=(snapshot.project_id, entry.session_id),
        )
    if snapshot.sessions.next_cursor and st.button("More conversations"):
        try:
            page = asyncio.run(service.more_sessions(snapshot))
            snapshot = replace(
                snapshot,
                sessions=page.model_copy(
                    update={"sessions": (*snapshot.sessions.sessions, *page.sessions)}
                ),
            )
            save_snapshot(snapshot)
            st.rerun()
        except Exception as error:  # noqa: BLE001 — UI boundary must not expose provider details.
            st.error(friendly_error(error))
    if snapshot.stream:
        with st.expander("Rename conversation"):
            with st.form("rename-conversation"):
                name = st.text_input(
                    "Title",
                    value=next(
                        (
                            e.title
                            for e in snapshot.sessions.sessions
                            if e.session_id == snapshot.session_id
                        ),
                        "Conversation",
                    ),
                    max_chars=120,
                    key="ace_conversation_title",
                )
                if st.form_submit_button("Rename", disabled=not name.strip()):
                    try:
                        asyncio.run(service.rename(snapshot.session_id, name))
                        st.session_state.pop("ace_workspace", None)
                        st.rerun()
                    except Exception as error:  # noqa: BLE001 — UI boundary must not expose provider details.
                        st.error(friendly_error(error))
    st.divider()
    documents, require_sources, selected_sources = source_controls()
    with st.popover("Workspace info", icon=":material/info:"):
        st.caption(
            "Memory and task changes save as you talk. Starting a new conversation keeps project context."
        )
        st.caption(
            "Only authenticated tool outcomes are verified completion. Statements and suggestions are labelled separately."
        )
        st.code(snapshot.session_id)

show_context = header(labels[snapshot.project_id])
if st.session_state.get("ace_notice"):
    st.info(st.session_state.ace_notice)
if st.session_state.get("ace_needs_refresh"):
    st.warning(
        "The reply was saved, but current context could not be refreshed. Refresh before sending another message."
    )
if st.button("Refresh context", icon=":material/refresh:", key="refresh-workspace"):
    st.session_state.pop("ace_workspace", None)
    st.session_state.pop("ace_needs_refresh", None)
    st.rerun()

live: dict[str, ConversationTurn] = st.session_state.get("ace_live_turns", {})
history = [live.get(turn.event_id or "", turn) for turn in snapshot.history]
extra = [
    turn
    for identifier, turn in live.items()
    if not any(saved.event_id == identifier for saved in history)
]
history.extend(extra)
action: InspectorAction | None = None
starter: str | None = None
if show_context:
    chat_column, context_column = st.columns([2.5, 1], gap="large")
else:
    chat_column, context_column = st.container(), None
with chat_column:
    if not history:
        starter = welcome()
    for index, turn in enumerate(history):
        action = render_turn(turn, index) or action
with context_column if context_column is not None else st.container():
    if show_context:
        with st.container(key="context_inspector"):
            action = (
                render_context(
                    snapshot,
                    history[-1].result.suggested_next_steps if history else (),
                    allow_submit=not bool(st.session_state.get("ace_pending")),
                )
                or action
            )
            if snapshot.memory.next_cursor and st.button("More memory"):
                try:
                    page = asyncio.run(service.more_memory(snapshot))
                    snapshot = replace(
                        snapshot,
                        memory=page.model_copy(
                            update={"items": (*snapshot.memory.items, *page.items)}
                        ),
                    )
                    save_snapshot(snapshot)
                    st.rerun()
                except Exception as error:  # noqa: BLE001 — UI boundary must not expose provider details.
                    st.error(friendly_error(error))
            show_evidence()

if not show_context:
    show_evidence()

if action:
    try:
        if action.kind == "evidence":
            st.session_state.ace_evidence = asyncio.run(
                service.evidence(action.identifier)
            )
        elif action.kind == "event":
            st.session_state.ace_evidence = [
                asyncio.run(
                    service.source_event(
                        action.session_id, action.identifier, snapshot.project_id
                    )
                )
            ]
        elif action.kind == "remove" and action.item is not None:
            asyncio.run(service.remove(action.item))
            st.session_state.pop("ace_workspace", None)
            st.session_state.ace_notice = (
                "Removed from memory. Original conversation text is retained."
            )
        elif action.kind == "correct" and action.item is not None:
            if not action.item.fingerprint:
                raise ValueError("Memory does not have a revocable fingerprint")
            queue(
                f"Correction to remembered {action.item.canonical_key}: {action.text}",
                snapshot,
                RevocationInput(
                    item_id=action.item.item_id,
                    expected_fingerprint=action.item.fingerprint,
                ),
            )
        elif action.kind == "suggestion":
            queue(action.text, snapshot)
        st.rerun()
    except Exception as error:  # noqa: BLE001 — UI boundary must not expose provider details.
        st.error(friendly_error(error))

pending: PendingTurn | None = st.session_state.get("ace_pending")
closed = bool(
    snapshot.stream
    and snapshot.stream.events
    and snapshot.stream.events[-1].event.kind == EventKind.SESSION_CLOSE
)
disabled = (
    closed
    or bool(pending)
    or bool(st.session_state.get("ace_needs_refresh"))
    or Permission.ASSERT not in snapshot.directory.permissions
)
message = st.chat_input(
    "Message your project…", key="ace_message", max_chars=4000, disabled=disabled
)
if closed:
    st.caption(
        "This conversation is closed. Start a new one to continue with the same project context."
    )
st.caption(
    "Useful context and verified progress save automatically. No manual progress save is required."
)
if starter or message:
    queue(starter or message or "", snapshot)
    st.session_state.ace_process_pending = True
    st.rerun()
if pending:
    with st.chat_message("user", avatar=":material/person:"):
        st.text(pending.message)
    retry = st.button("Retry saved request", key="retry-pending")
    if st.session_state.pop("ace_process_pending", False) or retry:
        try:
            with st.spinner("Updating memory and preparing your answer…"):
                outcome: WorkspaceTurn = asyncio.run(
                    service.send(
                        snapshot, pending, documents, require_sources=require_sources
                    )
                )
            identifier = ResearchAssistant.event_identifier(
                snapshot.session_id, pending.turn_id
            )
            live[identifier] = ConversationTurn(
                pending.message,
                outcome.result,
                selected_sources,
                outcome.result.cached,
                identifier,
            )
            st.session_state.ace_live_turns = live
            st.session_state.pop("ace_pending", None)
            st.session_state.ace_notice = outcome.warning or ""
            try:
                save_snapshot(
                    asyncio.run(service.load(snapshot.project_id, snapshot.session_id))
                )
            except Exception:  # noqa: BLE001 — retain the saved answer if refresh fails.
                st.session_state.ace_needs_refresh = True
            st.rerun()
        except Exception as error:  # noqa: BLE001 — UI boundary must not expose provider details.
            st.error(friendly_error(error))
    if st.button("Open another conversation", key="leave-pending"):
        new_conversation(snapshot.project_id)
        st.rerun()
