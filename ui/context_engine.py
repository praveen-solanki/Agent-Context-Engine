"""Developer console for the authenticated ACE SDK, research host and handoffs."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

from agent_context.client import AgentContextClient
from agent_context.demo import (
    DemoSettings,
    ResearchAssistant,
    ResearchTurn,
)
from agent_context.handoff import HandoffInput
from agent_context.search import (
    BraveSearch,
    SearchSettings,
    SearchResult,
    SearchResponse,
    SearchError,
)
from context_graph.config import Settings
from context_graph.providers.chat_backend import ChatLLMProvider
from ui.context_engine_view import (
    ConversationTurn,
    apply_style,
    brand,
    header,
    render_turn,
    welcome,
)

load_dotenv(override=False)
st.set_page_config(
    page_title="Agent Context Engine", page_icon=":material/notes:", layout="wide",
)
apply_style()

if "ace_session" not in st.session_state:
    st.session_state.ace_session = "console-" + uuid4().hex[:16]
    st.session_state.ace_sequence = 1
    st.session_state.ace_turn = 0
    st.session_state.ace_handoff = None
    st.session_state.ace_handoff_version = 0

st.session_state.setdefault("ace_conversation", [])


def client(variable: str) -> AgentContextClient:
    token = os.environ.get(variable)
    if not token:
        raise ValueError("configure the console's user and host credentials securely")
    return AgentContextClient(
        base_url=os.environ.get("ACE_API_URL", "http://127.0.0.1:8000"),
        bearer_token=token,
    )


async def send(
    message: str, documents: dict[str, str], require_sources: bool = False
) -> ResearchTurn:
    settings = Settings()
    user, host = client("ACE_DEMO_USER_TOKEN"), client("ACE_DEMO_AGENT_TOKEN")
    llm = ChatLLMProvider(backend=settings.chat, llm=settings.llm, retry=settings.retry)
    try:
        assistant = ResearchAssistant(
            user_client=user,
            host_client=host,
            llm=llm,
            documents=documents,
            settings=DemoSettings(require_sources=require_sources),
        )
        return await assistant.turn(
            session_id=st.session_state.ace_session,
            turn_id=f"turn-{st.session_state.ace_turn}",
            sequence=st.session_state.ace_sequence,
            message=message,
            handoff_id=st.session_state.ace_handoff,
            handoff_version=st.session_state.ace_handoff_version or 1,
        )
    finally:
        await user.aclose()
        await host.aclose()
        await llm.aclose()


async def search_web(query: str, settings: SearchSettings) -> SearchResponse:
    async with BraveSearch(settings) as provider:
        return await provider.search(query)


async def handoff(goal: str, pending: tuple[str, ...]) -> None:
    user = client("ACE_DEMO_USER_TOKEN")
    try:
        identifier = st.session_state.ace_handoff or "handoff-" + uuid4().hex[:16]
        turn: ResearchTurn = st.session_state.ace_result
        artifact = await user.prepare_handoff(
            HandoffInput(
                handoff_id=identifier,
                idempotency_key=f"{st.session_state.ace_session}-{st.session_state.ace_turn}",
                expected_version=st.session_state.ace_handoff_version,
                project_id="research-project",
                task_id="research-report",
                source_session_id=st.session_state.ace_session,
                goal=goal,
                completed=turn.completed,
                pending=pending,
            )
        )
        st.session_state.ace_handoff = identifier
        st.session_state.ace_handoff_version = artifact.version
    finally:
        await user.aclose()


def new_session() -> None:
    st.session_state.ace_session = "console-" + uuid4().hex[:16]
    st.session_state.ace_sequence = 1
    st.session_state.ace_turn = 0
    for key in ("ace_result", "ace_result_web_sources", "ace_web_results"):
        st.session_state.pop(key, None)
    st.session_state.ace_message = ""
    st.session_state.ace_search_query = ""
    st.session_state.ace_use_web = False
    st.session_state.ace_source_mode = "Sample brief"
    st.session_state.ace_conversation = []


def source_controls(settings: SearchSettings) -> tuple[tuple[SearchResult, ...], bool]:
    with st.expander("Sources", expanded=True):
        mode = st.radio("Research source", ["Sample brief", "Web search"],
                        key="ace_source_mode", label_visibility="collapsed")
        if mode == "Sample brief":
            st.caption("A short, built-in comparison. No search key needed.")
            return (), False
        if not settings.configured:
            st.caption("Web search is not connected.")
            with st.expander("Connect web search"):
                st.caption("Add BRAVE_SEARCH_API_KEY to your server environment or ignored .env file, then restart the UI.")
        query = st.text_input("Search query", placeholder="Search the web…", key="ace_search_query")
        if st.button("Search web", icon=":material/search:", width="stretch",
                     disabled=not settings.configured or not query.strip()):
            st.session_state.ace_web_results = ()
            st.session_state.ace_use_web = False
            try:
                with st.spinner("Searching…"):
                    response = asyncio.run(search_web(query, settings))
                st.session_state.ace_web_results = response.results
                st.session_state.ace_use_web = bool(response.results)
                if not response.results:
                    st.caption("No usable results. Try a different query.")
                if response.discarded_results:
                    st.caption("Some results could not be safely validated and were excluded.")
            except SearchError as error:
                st.error(str(error))
            except ValueError:
                st.error("Keep the search query within 1000 bytes.")
        results: tuple[SearchResult, ...] = st.session_state.get("ace_web_results", ())
        for index, source in enumerate(results, 1):
            with st.expander(f"Source {index}"):
                st.text(source.title)
                st.text(source.snippet)
                st.link_button("Open source", str(source.url), key=f"search_source_{index}")
        use_web = st.checkbox("Use these sources", disabled=not results, key="ace_use_web")
        st.caption("Only this query is sent to search. Results are snippets, not full pages.")
        return results, use_web


with st.sidebar:
    brand()
    st.button("New session", icon=":material/add:", width="stretch", on_click=new_session)
    st.caption("Start fresh here. Stored memory stays available.")
    st.divider()
    st.subheader("Continue your work")
    with st.expander("Project notes"):
        goal = st.text_input("Project goal", value="Compare the supplied research options", key="ace_goal")
        pending = st.text_area("Next steps", value="Deliver a cited recommendation", key="ace_pending")
        st.caption("These notes are included when you save progress.")
    if st.button("Save progress", icon=":material/bookmark:", width="stretch",
                 disabled="ace_result" not in st.session_state):
        try:
            asyncio.run(handoff(goal, tuple(line for line in pending.splitlines() if line.strip())))
            st.success("Progress saved for your next session.")
        except Exception:
            st.error("Progress could not be saved. Check service access and try again.")
    if st.session_state.ace_handoff:
        st.caption("Saved progress will carry into your next session.")
    else:
        st.caption("Save your goal and next steps after an answer.")
    st.divider()
    web_results, use_web = source_controls(SearchSettings())
    st.divider()
    with st.popover("How this works", icon=":material/help_outline:", width="stretch"):
        st.markdown(
            "1. **Ask or share a preference.** Useful context can be remembered.\n"
            "2. **Check an answer’s details.** See sources, memory and recorded work.\n"
            "3. **Start a new session.** Relevant memory stays available.\n"
            "4. **Save progress.** Carry your goal and next steps forward."
        )
        st.caption("Conversation history shown here belongs to this browser session. It is not a saved-session browser.")
    with st.expander("Session details"):
        st.caption("Current session")
        st.code(st.session_state.ace_session, language=None)
        if st.session_state.ace_handoff:
            st.caption(f"Saved progress revision {st.session_state.ace_handoff_version}")

header()
history: list[ConversationTurn] = st.session_state.ace_conversation
for index, turn in enumerate(history):
    render_turn(turn, index)

example = welcome(with_web=use_web) if not history else None
message = st.chat_input("Ask a question or share something to remember…", key="ace_message", max_chars=16000)
request = example or message
if request:
    with st.chat_message("user", avatar=":material/person:"):
        st.caption("YOU")
        st.text(request)
    try:
        documents = (
            {source.document_id: source.as_document() for source in web_results}
            if use_web and web_results else {
                "research-brief": "Option A costs 10 units and works offline. Option B costs 20 units and requires a network."
            }
        )
        with st.spinner("Finding relevant context and preparing your answer…"):
            result = asyncio.run(send(request, documents, require_sources=use_web))
        sources = web_results if use_web else ()
        history.append(ConversationTurn(request, result, sources))
        st.session_state.ace_result = result
        st.session_state.ace_result_web_sources = sources
        st.session_state.ace_sequence = result.next_sequence
        st.session_state.ace_turn += 1
        st.rerun()
    except Exception:
        st.error("This request could not complete. Try the same message again, or start a new session.")
