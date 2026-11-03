"""Developer console for the authenticated ACE SDK, research host and handoffs."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import streamlit as st
from dotenv import load_dotenv

from agent_context.client import AgentContextClient
from agent_context.demo import ResearchAssistant, ResearchTurn
from agent_context.handoff import HandoffInput
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


async def send(message: str) -> ResearchTurn:
    settings = Settings()
    user, host = client("ACE_DEMO_USER_TOKEN"), client("ACE_DEMO_AGENT_TOKEN")
    llm = ChatLLMProvider(backend=settings.chat, llm=settings.llm, retry=settings.retry)
    try:
        assistant = ResearchAssistant(
            user_client=user,
            host_client=host,
            llm=llm,
            documents={
                "research-brief": "Option A costs 10 units and works offline. Option B costs 20 units and requires a network."
            },
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


with st.sidebar:
    st.header("Project continuity")
    st.caption(st.session_state.ace_session)
    if st.button("New session"):
        st.session_state.ace_session = "console-" + uuid4().hex[:16]
        st.session_state.ace_sequence = 1
        st.session_state.ace_turn = 0
        st.rerun()
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

message = st.text_area(
    "Message",
    placeholder="Ask for a cited comparison, or change a preference and continue in a new session.",
)
if st.button("Send", type="primary", disabled=not message.strip()):
    try:
        with st.spinner(
            "Recording the turn, gathering current context and researching…"
        ):
            result = asyncio.run(send(message))
        st.session_state.ace_result = result
        st.session_state.ace_sequence = result.next_sequence
        st.session_state.ace_turn += 1
    except Exception:
        st.error(
            "This turn could not complete. Retry the same message or start a new session."
        )

if "ace_result" in st.session_state:
    result: ResearchTurn = st.session_state.ace_result
    st.markdown(result.answer)
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
