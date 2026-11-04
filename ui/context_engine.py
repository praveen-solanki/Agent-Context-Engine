"""Developer console for the authenticated ACE SDK, research host and handoffs."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

from agent_context.client import AgentContextClient
from agent_context.demo import (
    MEMORY_SOURCE_PREFIX,
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

load_dotenv(override=False)
st.set_page_config(page_title="Agent Context Engine", layout="wide")
st.title("Agent Context Engine")
st.caption(
    "Research across sessions with current preferences, cited evidence and explicit handoffs."
)

if "ace_session" not in st.session_state:
    st.session_state.ace_session = "console-" + uuid4().hex[:16]
    st.session_state.ace_sequence = 1
    st.session_state.ace_turn = 0
    st.session_state.ace_handoff = None
    st.session_state.ace_handoff_version = 0


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


with st.sidebar:
    st.header("Project continuity")
    st.caption(st.session_state.ace_session)
    st.button("New session", on_click=new_session)
    goal = st.text_input("Project goal", value="Compare the supplied research options")
    pending = st.text_area("Next steps", value="Deliver a cited recommendation")
    if st.button("Save handoff", disabled="ace_result" not in st.session_state):
        try:
            asyncio.run(
                handoff(
                    goal, tuple(line for line in pending.splitlines() if line.strip())
                )
            )
            st.success("Handoff saved. A new session can continue from this state.")
        except Exception:
            st.error("The handoff could not be saved. Check service access and retry.")
    if st.session_state.ace_handoff:
        st.caption(f"Handoff revision {st.session_state.ace_handoff_version}")

search_settings = SearchSettings()
with st.expander("Web search (optional)", expanded=search_settings.configured):
    st.caption(
        "Only the search query below is sent to Brave Search. Personal memory and chat history are not sent as search queries."
    )
    if not search_settings.configured:
        st.info(
            "Web search is not configured. Add BRAVE_SEARCH_API_KEY to the server environment or ignored .env file to enable it. The sample-document demo remains available."
        )
    search_query = st.text_input(
        "Web search query",
        placeholder="What would you like to research?",
        key="ace_search_query",
    )
    if st.button(
        "Search web",
        disabled=not search_settings.configured or not search_query.strip(),
    ):
        st.session_state.ace_web_results = ()
        st.session_state.ace_use_web = False
        try:
            with st.spinner("Searching the web…"):
                response = asyncio.run(search_web(search_query, search_settings))
            st.session_state.ace_web_results = response.results
            st.session_state.ace_use_web = bool(response.results)
            if not response.results:
                st.info("No usable web results were returned. Try another query.")
            if response.discarded_results:
                st.caption(
                    "Some results were excluded because they could not be safely validated."
                )
        except SearchError as error:
            st.error(str(error))
        except ValueError:
            st.error("Use a search query of at most 1000 bytes.")
    web_results: tuple[SearchResult, ...] = st.session_state.get("ace_web_results", ())
    for index, source in enumerate(web_results, 1):
        st.text(source.title)
        st.text(source.snippet)
        st.link_button(f"Open search result {index}", str(source.url))
    use_web = st.checkbox(
        "Use these web results for the next answer",
        disabled=not web_results,
        key="ace_use_web",
    )
    if web_results:
        st.caption(
            "These are search-result snippets. The app does not fetch full web pages."
        )

message = st.text_area(
    "Message",
    key="ace_message",
    placeholder="Ask for a cited comparison, or change a preference and continue in a new session.",
)
if st.button("Send", type="primary", disabled=not message.strip()):
    try:
        documents = (
            {source.document_id: source.as_document() for source in web_results}
            if use_web and web_results
            else {
                "research-brief": "Option A costs 10 units and works offline. Option B costs 20 units and requires a network."
            }
        )
        with st.spinner(
            "Recording the turn, gathering current context and researching…"
        ):
            result = asyncio.run(send(message, documents, require_sources=use_web))
        st.session_state.ace_result = result
        st.session_state.ace_result_web_sources = web_results if use_web else ()
        st.session_state.ace_sequence = result.next_sequence
        st.session_state.ace_turn += 1
    except Exception:
        st.error(
            "This turn could not complete. Retry the same message or start a new session."
        )

if "ace_result" in st.session_state:
    result: ResearchTurn = st.session_state.ace_result
    # Plain text prevents untrusted snippets/model output from embedding remote
    # images or executable HTML. Citation links come only from validated sources.
    st.text(result.answer)
    for item in result.bundle.items:
        if MEMORY_SOURCE_PREFIX + item.item_id in result.citations:
            st.text("Cited memory: " + item.text)
            st.caption("Memory evidence: " + ", ".join(item.evidence_ids))
    cited_sources: tuple[SearchResult, ...] = st.session_state.get(
        "ace_result_web_sources", ()
    )
    for index, source in enumerate(
        (source for source in cited_sources if source.document_id in result.citations),
        1,
    ):
        st.text(source.title)
        st.link_button(f"Cited web source {index}", str(source.url))
    context, trace, work = st.tabs(
        ["Current context", "Selection trace", "Verified work"]
    )
    with context:
        st.caption(f"{result.bundle.token_count} tokens (conservative upper bound)")
        for item in result.bundle.items:
            st.write(item.text)
            st.caption("Evidence: " + ", ".join(item.evidence_ids))
    with trace:
        st.json(
            {
                "bundle_id": result.bundle.bundle_id,
                "excluded": result.bundle.excluded_counts,
                "reasons": [x.model_dump() for x in result.bundle.exclusions],
                "warnings": result.bundle.warnings,
            }
        )
    with work:
        for action in result.completed:
            st.write(action.description)
            st.caption(f"Tool outcome: {action.result_event_id}")
        if result.cached:
            st.info(
                "Recovered the previously recorded answer without repeating the model or reads."
            )
else:
    st.info(
        "Send a research request to see the answer, selected context, evidence and continuation state."
    )
