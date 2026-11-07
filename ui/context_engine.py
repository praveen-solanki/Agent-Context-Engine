"""Persistent conversational workspace over the existing authenticated ACE APIs."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from uuid import uuid4

import httpx
import streamlit as st
from dotenv import load_dotenv

from agent_context.client import EventProcessingStopped
from agent_context.continuity import WorkspaceTurn
from agent_context.contracts import EventKind, Permission
from agent_context.demo import ResearchAssistant
from agent_context.events import EventConflict
from agent_context.governance import RevocationInput
from agent_context.navigation import ProjectEdit
from agent_context.search import (
    BraveSearch,
    SearchError,
    SearchResponse,
    SearchResult,
    SearchSettings,
)
from context_graph.errors import (
    ExtractionValidationError,
    ProviderError,
    TransientError,
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

ROUTING_WIDGET_KEYS = (
    "ace_route_project",
    "ace_route_rephrase",
    "ace_new_project_name",
)
SCOPE_WIDGET_KEYS = (
    "ace_conversation_title",
    "ace_search_query",
    "ace_use_web",
    *ROUTING_WIDGET_KEYS,
)


def reset_pending_widgets() -> None:
    """Apply deferred resets only before any affected widget is constructed."""
    scope = st.session_state.pop("ace_reset_scope_widgets", False)
    routing = st.session_state.pop("ace_reset_route_widgets", False)
    for key in SCOPE_WIDGET_KEYS if scope else ROUTING_WIDGET_KEYS if routing else ():
        st.session_state.pop(key, None)
    if scope:
        st.session_state.ace_source_mode = "Project memory"


reset_pending_widgets()


def clear_view() -> None:
    for key in (
        "ace_workspace",
        "ace_pending",
        "ace_process_pending",
        "ace_evidence",
        "ace_live_turns",
        "ace_needs_refresh",
        "ace_notice",
        "ace_web_results",
        "ace_route_question",
        "ace_route_candidates",
    ):
        st.session_state.pop(key, None)
    # Navigation can run from a callback or below already-created source
    # controls. Reset widget-owned keys at the next safe render boundary.
    st.session_state.ace_reset_scope_widgets = True


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
    st.session_state.ace_routing_mode = "Selected project"
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
    if isinstance(error, EventProcessingStopped):
        return "Your message was recorded, but background memory processing stopped after repeated failures. Chat retry cannot restart it. Open another conversation or ask the operator to review and replay the failed work."
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "The request timed out. Recorded work may still be processing. Check that the API and worker are healthy, then retry the same saved request."
    if isinstance(error, httpx.TransportError):
        return "Cannot reach the workspace service. Check that the API, worker and databases are running, then retry the saved request."
    if isinstance(error, ExtractionValidationError):
        return "The model response could not be validated. Your recorded message is retained. Retry the saved request; repeated failures need a model or configuration check."
    if isinstance(error, (ProviderError, TransientError)):
        return "The model service could not complete this request. Check model availability, credentials and rate limits, then retry the saved request."
    if isinstance(error, EventConflict):
        return "The project plan changed after this request was recorded. Open another conversation and restate the request using the current plan."
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code == 429:
            return "The workspace service reached a rate limit. Wait before retrying the same saved request."
        if error.response.status_code >= 500:
            return "The workspace service could not complete this request. Check API, worker and database health; recorded work is retained. Retry after the service recovers."
        if error.response.status_code == 404:
            return "The workspace API needs updating, or this record is no longer available. Restart the updated app with ./run.sh --skip-demo."
        if error.response.status_code in (401, 403):
            return "This workspace is not accessible with the current credentials or project permissions."
        if error.response.status_code == 409:
            return "Project state changed. Refresh the context before retrying."
        if error.response.status_code == 413:
            return "This conversation or project has reached its storage limit. Start a new conversation or review the project state."
    return "This request could not complete. Recorded conversation is retained; unsent requests can be retried or cancelled."


def load_snapshot() -> WorkspaceSnapshot:
    project = st.query_params.get("project")
    session = st.query_params.get("session")
    cached: WorkspaceSnapshot | None = st.session_state.get("ace_workspace")
    if cached and (project, session) == (cached.project_id, cached.session_id):
        return cached
    if cached is not None:
        clear_view()
    value = asyncio.run(service.load(project, session))
    if (st.query_params.get("project"), st.query_params.get("session")) != (
        project,
        session,
    ):
        raise RuntimeError("workspace navigation changed while loading")
    if (project is not None and value.project_id != project) or (
        session is not None and value.session_id != session
    ):
        raise PermissionError("loaded workspace does not match the requested scope")
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
    message: str,
    snapshot: WorkspaceSnapshot,
    target: RevocationInput | None = None,
    *,
    manual: bool = False,
    request_documents: dict[str, str] | None = None,
    request_sources: tuple[SearchResult, ...] = (),
    request_requires_sources: bool = False,
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
        manual=manual
        or target is not None
        or st.session_state.get("ace_routing_mode", "Automatic") == "Selected project",
        documents=request_documents,
        source_snapshots=request_sources,
        require_sources=request_requires_sources,
    )
    st.session_state.ace_process_pending = True


def stage_prepared(value: service.PreparedTurn) -> None:
    """Commit a routing decision before sending, preserving it across retries."""
    if not value.clarification and not value.pending.routed:
        raise ValueError("project routing did not produce a choice or a clarification")
    current: WorkspaceSnapshot | None = st.session_state.get("ace_workspace")
    if current and (current.project_id, current.session_id) != (
        value.snapshot.project_id,
        value.snapshot.session_id,
    ):
        # Source widgets already exist in this run. Reset them before widgets
        # are instantiated on the next run, then send with the new scope only.
        st.session_state.ace_reset_scope_widgets = True
        for scope_key in (
            "ace_live_turns",
            "ace_evidence",
            "ace_web_results",
            "ace_needs_refresh",
            "ace_notice",
        ):
            st.session_state.pop(scope_key, None)
    save_snapshot(value.snapshot)
    # save_snapshot clears a pending request from another scope. Install the
    # prepared request afterwards, with the same turn ID and the new binding.
    st.session_state.ace_pending = value.pending
    if value.clarification:
        st.session_state.ace_route_question = value.clarification
        st.session_state.ace_route_candidates = value.candidates
        st.session_state.pop("ace_process_pending", None)
    else:
        st.session_state.pop("ace_route_question", None)
        st.session_state.pop("ace_route_candidates", None)
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

# Query-parameter navigation can invalidate a cache during load_snapshot(),
# after the initial reset boundary but still before any workspace widgets.
reset_pending_widgets()

with st.sidebar:
    brand()
    st.radio(
        "Project routing",
        ["Automatic", "Selected project"],
        key="ace_routing_mode",
        disabled=bool(st.session_state.get("ace_pending")),
    )
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
        disabled=bool(st.session_state.get("ace_pending")),
    )
    active_project = next(
        entry for entry in entries if entry.project_id == snapshot.project_id
    )
    if active_project.kind == "project":
        with st.expander("Project name and aliases"):
            with st.form(
                "project-metadata-"
                + active_project.project_id
                + str(active_project.version)
            ):
                title = st.text_input(
                    "Project name", value=active_project.title, max_chars=120
                )
                aliases = st.text_area(
                    "Aliases (one per line)",
                    value="\n".join(active_project.aliases),
                    max_chars=1000,
                )
                if st.form_submit_button(
                    "Update project",
                    disabled=Permission.CORRECT not in snapshot.directory.permissions
                    or bool(st.session_state.get("ace_pending")),
                ):
                    try:
                        asyncio.run(
                            service.edit_project(
                                active_project.project_id,
                                ProjectEdit(
                                    title=title.strip(),
                                    aliases=tuple(
                                        value.strip()
                                        for value in aliases.splitlines()
                                        if value.strip()
                                    ),
                                    expected_version=active_project.version,
                                ),
                            )
                        )
                        st.session_state.pop("ace_workspace", None)
                        st.session_state.ace_notice = "Project details updated. Its identity and recorded context are unchanged."
                        st.rerun()
                    except Exception:  # noqa: BLE001 — do not expose backend details.
                        st.error(
                            "Project details could not be updated. Refresh, check the name/aliases are distinct and within the eight-alias limit, then retry."
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
if st.session_state.ace_routing_mode == "Selected project":
    st.caption(
        "Using: " + plain_label(labels[snapshot.project_id]) + " · selected by you"
    )
elif snapshot.stream:
    st.caption(
        "Using: "
        + plain_label(labels[snapshot.project_id])
        + " · automatic project matching"
    )
else:
    st.caption(
        "Viewing: "
        + plain_label(labels[snapshot.project_id])
        + " · your next message will be matched to a project before saving"
    )
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
            queue(action.text, snapshot, manual=True)
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
    queue(
        starter or message or "",
        snapshot,
        request_documents=documents,
        request_sources=selected_sources,
        request_requires_sources=require_sources,
    )
    st.session_state.ace_process_pending = True
    st.rerun()
if pending:
    with st.chat_message("user", avatar=":material/person:"):
        st.text(pending.message)
    process = st.session_state.pop("ace_process_pending", False)
    question: str | None = st.session_state.get("ace_route_question")
    if not pending.routed and question:
        st.info(question)
        candidates = st.session_state.get("ace_route_candidates", ())
        names = {entry.project_id: entry.title for entry in candidates}
        if names:
            chosen = st.selectbox(
                "Choose the intended project",
                list(names),
                format_func=lambda identifier: names[identifier],
                key="ace_route_project",
            )
            if st.button("Use selected project", key="route-use-project"):
                try:
                    stage_prepared(
                        asyncio.run(
                            service.prepare(
                                snapshot, pending, selected_project_id=chosen
                            )
                        )
                    )
                    st.rerun()
                except Exception as error:  # noqa: BLE001 — UI boundary must not expose provider details.
                    st.error(friendly_error(error))
            with st.form("confirm-new-project"):
                new_name = st.text_input(
                    "New project name (copy from your message)",
                    max_chars=120,
                    key="ace_new_project_name",
                )
                if st.form_submit_button("Create and use project"):
                    try:
                        stage_prepared(
                            asyncio.run(
                                service.prepare(
                                    snapshot, pending, new_project_name=new_name
                                )
                            )
                        )
                        st.rerun()
                    except Exception:  # noqa: BLE001 — keep backend/source details private.
                        st.error(
                            "Use an exact name from your message that is not already taken. Refresh the project list if it changed."
                        )
        st.caption(
            "To create a different project, rephrase with a distinct name and goal. Nothing from this request has been saved as conversation or memory yet."
        )
        with st.form("rephrase-routing-request"):
            revised = st.text_area(
                "Rephrase the unsent request",
                value=pending.message,
                max_chars=4000,
                key="ace_route_rephrase",
            )
            if st.form_submit_button("Try revised request"):
                if revised.strip():
                    st.session_state.ace_pending = pending.model_copy(
                        update={
                            "message": revised.strip(),
                            "turn_id": "ui-" + uuid4().hex,
                            "documents": documents,
                            "source_snapshots": selected_sources,
                            "require_sources": require_sources,
                        }
                    )
                    st.session_state.pop("ace_route_question", None)
                    st.session_state.pop("ace_route_candidates", None)
                    st.session_state.ace_process_pending = True
                    st.rerun()
                st.error("Enter the revised request first.")
    retry = (
        False
        if question and not pending.routed
        else st.button("Retry saved request", key="retry-pending")
    )
    if (process or retry) and not pending.routed:
        try:
            with st.spinner("Finding the right project…"):
                stage_prepared(asyncio.run(service.prepare(snapshot, pending)))
            st.rerun()
        except Exception:  # noqa: BLE001 — UI boundary must not expose provider details.
            st.session_state.ace_route_question = "Automatic project selection could not complete. Choose an authorized project explicitly, retry with a revised message, or cancel. No conversation or memory was recorded from this request."
            st.session_state.ace_route_candidates = snapshot.directory.projects
            st.rerun()
    elif (process or retry) and pending.routed:
        try:
            with st.spinner("Updating memory and preparing your answer…"):
                outcome: WorkspaceTurn = asyncio.run(
                    service.send(
                        snapshot,
                        pending,
                        pending.documents
                        if pending.documents is not None
                        else documents,
                        require_sources=pending.require_sources
                        if pending.documents is not None
                        else require_sources,
                    )
                )
            identifier = ResearchAssistant.event_identifier(
                snapshot.session_id, pending.turn_id
            )
            live[identifier] = ConversationTurn(
                pending.message,
                outcome.result,
                pending.source_snapshots
                if pending.documents is not None
                else selected_sources,
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
    if not pending.routed and st.button(
        "Cancel unsent request", key="cancel-routing-request"
    ):
        for key in (
            "ace_pending",
            "ace_process_pending",
            "ace_route_question",
            "ace_route_candidates",
        ):
            st.session_state.pop(key, None)
        st.session_state.ace_reset_route_widgets = True
        st.rerun()
    if st.button("Open another conversation", key="leave-pending"):
        new_conversation(snapshot.project_id)
        st.rerun()
