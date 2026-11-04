"""Presentation components for the research console; no service mutations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from agent_context.demo import MEMORY_SOURCE_PREFIX, ResearchTurn
from agent_context.search import SearchResult


@dataclass(frozen=True)
class ConversationTurn:
    message: str
    result: ResearchTurn
    sources: tuple[SearchResult, ...] = ()


def apply_style() -> None:
    # Static, repository-owned styles only. Model/user text never enters HTML.
    css = Path(__file__).with_name("context_engine.css").read_text()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def brand() -> None:
    st.markdown(
        '<div class="ace-brand"><div class="ace-monogram">AC</div>'
        '<div><div class="ace-brand-name">Context Engine</div>'
        '<div class="ace-brand-subtitle">Research workspace</div></div></div>',
        unsafe_allow_html=True,
    )


def header() -> None:
    st.markdown('<div class="ace-eyebrow">RESEARCH WORKSPACE</div>', unsafe_allow_html=True)
    st.title("Agent Context Engine")
    st.caption("Research with memory and evidence.")
    st.divider()


def welcome(*, with_web: bool = False) -> str | None:
    st.markdown(
        '<div class="ace-empty"><h2>Start with a question.</h2>'
        '<p>Compare the sample brief, share a preference, or continue previous work. '
        'Each answer includes its sources and relevant memory.</p></div>',
        unsafe_allow_html=True,
    )
    st.caption("TRY A REQUEST")
    left, right = st.columns(2)
    with left:
        compare = st.button(
            "Summarize selected sources" if with_web else "Compare the sample options",
            icon=":material/compare_arrows:", width="stretch",
        )
    with right:
        remember = st.button("Remember a report preference", icon=":material/bookmark_add:", width="stretch")
    if with_web:
        st.caption("The next answer will use your selected search-result snippets.")
    else:
        st.markdown(
            '<div class="ace-brief">The sample brief includes two options: '
            'A costs 10 units and works offline. B costs 20 units and needs a network.</div>',
            unsafe_allow_html=True,
        )
    if compare:
        if with_web:
            return "Summarize the selected web results and cite the sources you use."
        return "Read research-brief and recommend the cheapest option that works offline. Cite the document."
    if remember:
        return "Remember that I prefer concise research summaries in English."
    return None


def render_details(turn: ConversationTurn, turn_index: int) -> None:
    result = turn.result
    cited_memory = [
        item for item in result.bundle.items
        if MEMORY_SOURCE_PREFIX + item.item_id in result.citations
    ]
    with st.expander("Sources, memory and activity"):
        sources, memory, activity = st.tabs(["Sources", "Memory used", "Activity"])
        with sources:
            web_ids = {source.document_id for source in turn.sources}
            for index, source in enumerate(turn.sources, 1):
                if source.document_id in result.citations:
                    st.text(source.title)
                    st.link_button(f"Open cited source {index}", str(source.url),
                                   key=f"cited_source_{turn_index}_{index}")
            for citation in result.citations:
                if citation not in web_ids and not citation.startswith(MEMORY_SOURCE_PREFIX):
                    st.caption("Document")
                    st.text(citation)
            for item in cited_memory:
                st.caption("Cited memory")
                st.text(item.text)
                st.caption("Memory evidence: " + ", ".join(item.evidence_ids))
            if not result.citations:
                st.caption("No sources were cited in this answer.")
        with memory:
            if result.bundle.items:
                st.caption("Stored context selected for this answer.")
                for item in result.bundle.items:
                    st.text(item.text)
                    st.caption("Evidence: " + ", ".join(item.evidence_ids))
            else:
                st.caption("No stored memory was selected for this answer.")
        with activity:
            if result.completed:
                for action in result.completed:
                    st.text(action.description)
                    st.caption("Recorded outcome: " + action.result_event_id)
            else:
                st.caption("No document reads were needed for this answer.")
            if result.cached:
                st.caption("Recovered a recorded answer. The model and tools were not run again.")
        with st.expander("Technical details"):
            st.caption(f"Context size: {result.bundle.token_count} tokens (conservative upper bound)")
            st.json({
                "bundle_id": result.bundle.bundle_id,
                "excluded": result.bundle.excluded_counts,
                "reasons": [entry.model_dump() for entry in result.bundle.exclusions],
                "warnings": result.bundle.warnings,
                "model_calls": result.model_calls,
            })


def render_turn(turn: ConversationTurn, index: int) -> None:
    with st.chat_message("user", avatar=":material/person:"):
        st.caption("YOU")
        st.text(turn.message)
    with st.chat_message("assistant", avatar=":material/notes:"):
        st.caption("ASSISTANT")
        # Keep untrusted content plain text: no HTML or remote image rendering.
        st.text(turn.result.answer)
        memories = len(turn.result.bundle.items)
        reads = len(turn.result.completed)
        memory_label = "memory item" if memories == 1 else "memory items"
        read_label = "document read" if reads == 1 else "document reads"
        st.caption(
            f"{memories} {memory_label} selected · {reads} {read_label}"
        )
        with st.container(key=f"answer_details_{index}"):
            render_details(turn, index)
