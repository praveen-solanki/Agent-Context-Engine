"""Presentation for the persistent workspace; service actions are returned to the page."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import streamlit as st

from agent_context.assembly import ContextItem
from agent_context.contracts import Permission
from agent_context.demo import MEMORY_SOURCE_PREFIX
from ui.workspace import ConversationTurn, WorkspaceSnapshot


@dataclass(frozen=True)
class InspectorAction:
    kind: Literal["evidence", "event", "correct", "remove", "suggestion"]
    item: ContextItem | None = None
    text: str = ""
    identifier: str = ""
    session_id: str = ""


def plain_label(value: str) -> str:
    """Widget labels support Markdown; keep untrusted titles as literal text."""
    return "".join(
        "\\" + char if char in "\\`*_{}[]()#+.!<>|~=-" else char for char in value
    )


def apply_style() -> None:
    css = Path(__file__).with_name("context_engine.css").read_text()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def brand() -> None:
    st.markdown(
        '<div class="ace-brand">Context Engine</div><div class="ace-brand-subtitle">Your project workspace</div>',
        unsafe_allow_html=True,
    )


def header(title: str) -> bool:
    main, toggle = st.columns([4, 1], vertical_alignment="center")
    with main:
        st.title(plain_label(title))
        st.caption("Conversation, memory and progress in one place.")
    with toggle:
        show = st.toggle("Context", value=True, key="ace_show_context")
    if show:
        st.markdown('<span class="ace-with-context"></span>', unsafe_allow_html=True)
    st.divider()
    return show


def welcome() -> str | None:
    st.markdown(
        '<div class="ace-empty"><h2>What are you working on?</h2><p>Describe a goal, share a change, or continue a project. Useful memory and task updates are saved as you talk.</p></div>',
        unsafe_allow_html=True,
    )
    if st.button("What do you remember about this project?", icon=":material/history:"):
        return "What do you remember about this project, and what work remains?"
    return None


def render_turn(turn: ConversationTurn, index: int) -> InspectorAction | None:
    with st.chat_message("user", avatar=":material/person:"):
        st.caption("YOU")
        st.text(turn.message)
    with st.chat_message("assistant", avatar=":material/notes:"):
        st.caption("CONTEXT ENGINE")
        st.text(turn.result.answer)
        with st.expander("Sources and activity"):
            if turn.recorded:
                st.caption(
                    "Recorded conversation. The original context selection is not retained here; the panel shows current project memory."
                )
            elif turn.result.bundle.items:
                st.caption(
                    f"{len(turn.result.bundle.items)} context items used for this answer."
                )
            sources = {source.document_id: source for source in turn.sources}
            memory = {item.item_id: item for item in turn.result.bundle.items}
            for citation in turn.result.citations:
                if citation.startswith(MEMORY_SOURCE_PREFIX):
                    identifier = citation.removeprefix(MEMORY_SOURCE_PREFIX)
                    if identifier in memory:
                        st.text(memory[identifier].text)
                    if st.button(
                        "View memory evidence", key=f"citation-{index}-{identifier}"
                    ):
                        return InspectorAction("evidence", identifier=identifier)
                elif citation in sources:
                    source = sources[citation]
                    st.link_button(
                        plain_label(source.title),
                        str(source.url),
                        key=f"cited-{index}-{citation}",
                    )
                else:
                    st.caption("Recorded source: " + citation)
            for action in turn.result.completed:
                st.text(action.description)
                if st.button(
                    "View recorded result", key=f"action-{index}-{action.action_id}"
                ):
                    return InspectorAction(
                        "event",
                        identifier=action.result_event_id,
                        session_id=action.source_session_id,
                    )
            if turn.result.task_context:
                st.caption(
                    f"Answered with project revision {turn.result.task_context.version}."
                )
            if not turn.result.citations and not turn.result.completed:
                st.caption(
                    "No source references or tool outcomes recorded for this answer."
                )
            if not turn.recorded:
                with st.expander("Selection details"):
                    st.json(
                        {
                            "bundle_id": turn.result.bundle.bundle_id,
                            "excluded": turn.result.bundle.excluded_counts,
                            "warnings": turn.result.bundle.warnings,
                            "model_calls": turn.result.model_calls,
                        }
                    )
    return None


def render_context(
    snapshot: WorkspaceSnapshot,
    suggestions: tuple[str, ...],
    *,
    allow_submit: bool = True,
) -> InspectorAction | None:
    st.subheader("Project context")
    task = snapshot.task
    if task:
        st.caption(f"Project revision {task.version} · saved automatically")
        if not task.source_available:
            st.info(
                "The latest task update is still processing. Refresh before continuing."
            )
        if task.warnings:
            st.warning("Some project evidence needs to be checked again.")
        st.markdown("**Goal**")
        st.text(task.content.goal)
        if task.content.requirements:
            with st.expander("Requirements"):
                for requirement in task.content.requirements:
                    st.text("• " + requirement)
        if st.button("Latest plan update", key="task-source"):
            return InspectorAction(
                "event",
                identifier=task.content.source_event_id or "",
                session_id=task.content.source_session_id,
            )
        st.divider()
        st.markdown("**Progress**")
        if task.content.completed:
            st.caption(
                "Verified tool outcomes"
                if "completed_action_no_longer_verifiable" not in task.warnings
                else "Recorded outcomes — evidence needs rechecking"
            )
            for index, action in enumerate(task.content.completed):
                st.text("✓ " + action.description)
                if st.button("Evidence", key=f"completed-{index}-{action.action_id}"):
                    return InspectorAction(
                        "event",
                        identifier=action.result_event_id,
                        session_id=action.source_session_id,
                    )
        if task.content.reported_completed:
            st.caption("Reported by you · not independently verified")
            for index, report in enumerate(task.content.reported_completed):
                st.text(report.description)
                if st.button("Original statement", key=f"reported-{index}"):
                    return InspectorAction(
                        "event",
                        identifier=report.source_event_id,
                        session_id=report.source_session_id,
                    )
        if not task.content.completed and not task.content.reported_completed:
            st.caption("No completed work recorded yet.")
        if task.content.blockers:
            st.markdown("**Blockers**")
            for blocker in task.content.blockers:
                st.text("• " + blocker)
        if task.content.unresolved_operations:
            st.warning(
                "An operation has an unknown outcome. Reconcile it before repeating work."
            )
        if task.content.pending:
            st.markdown("**Next planned step**")
            st.text(task.content.pending[0])
            if (
                task.content.blockers
                or task.content.dependencies
                or task.content.unresolved_operations
            ):
                st.caption(
                    "This is a planned step, not confirmation that its prerequisites are satisfied."
                )
            if task.content.reported_completed:
                st.caption(
                    "Some earlier progress is user-reported; check its evidence before relying on it."
                )
            with st.expander("Remaining plan"):
                for step in task.content.pending:
                    st.text("• " + step)
        elif task.content.status == "active":
            st.caption("The project is active; no next step has been agreed yet.")
        if task.content.dependencies:
            with st.expander("Dependencies"):
                for dependency in task.content.dependencies:
                    st.text(dependency)
        if task.content.cancelled:
            with st.expander("Cancelled steps"):
                for step in task.content.cancelled:
                    st.text(step)
    else:
        st.caption(
            "No task agreed yet. Describe your goal in the conversation; ordinary memory still saves automatically."
        )
    if suggestions:
        with st.expander("Suggested next steps"):
            st.caption(
                "Assistant suggestions, not approved work or proof of completion."
            )
            for index, step in enumerate(suggestions):
                st.text(step)
                if task and st.button(
                    "Add to plan", key=f"accept-step-{index}", disabled=not allow_submit
                ):
                    return InspectorAction(
                        "suggestion", text="Add this step to the plan: " + step
                    )
    st.divider()
    st.markdown("**Memory**")
    st.caption(
        "Current project and personal context. Corrections and removal affect memory, not recorded conversation text."
    )
    if not snapshot.memory.items:
        st.caption("No memory available in this context yet.")
    can_correct = Permission.CORRECT in snapshot.directory.permissions
    for item in snapshot.memory.items:
        with st.expander(plain_label(item.text[:70] or item.canonical_key)):
            st.text(item.text)
            st.caption(item.scope_type.value.capitalize() + " memory")
            if st.button("View evidence", key="memory-evidence-" + item.item_id):
                return InspectorAction("evidence", item=item, identifier=item.item_id)
            with st.form("memory-correction-" + item.item_id):
                value = st.text_area(
                    "Correct this memory",
                    key="correction-" + item.item_id,
                    max_chars=1000,
                )
                if st.form_submit_button(
                    "Apply correction",
                    disabled=not can_correct
                    or not item.fingerprint
                    or not allow_submit,
                ):
                    if value.strip():
                        return InspectorAction("correct", item=item, text=value.strip())
                    st.error("Enter the corrected memory first.")
            if st.button(
                "Remove from memory",
                key="remove-" + item.item_id,
                disabled=not can_correct or not item.fingerprint,
            ):
                return InspectorAction("remove", item=item)
    return None
