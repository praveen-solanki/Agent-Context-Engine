"""Focused workspace interaction tests; all providers and API I/O are replaced."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import HttpUrl, SecretStr
from streamlit.testing.v1 import AppTest

from agent_context.assembly import ContextBundle
from agent_context.assembly import SearchResult as ContextSearch
from agent_context.continuity import WorkspaceTurn
from agent_context.contracts import Permission, Stream, utcnow
from agent_context.demo import ResearchAssistant, ResearchTurn
from agent_context.events import append_event
from agent_context.handoff import WorkState
from agent_context.navigation import (
    ProjectDirectory,
    ProjectEntry,
    SessionEntry,
    SessionPage,
)
from agent_context.search import BraveSearch, SearchResult, SearchSettings
from agent_context.task_state import TaskState
from tests.unit.test_assembly import item
from tests.unit.test_event_contracts import event, principal
from ui import workspace as service
from ui.workspace import ConversationTurn, PendingTurn, WorkspaceSnapshot

PAGE = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"


def result(answer: str = "A recorded answer") -> ResearchTurn:
    return ResearchTurn(
        answer=answer,
        bundle=ContextBundle(
            bundle_id="bundle",
            tokenizer_version="test",
            items=(),
            rendered="",
            token_count=0,
            exclusions=(),
            excluded_counts={},
        ),
        next_sequence=3,
    )


def snapshot(project: str = "p1", session: str = "s1") -> WorkspaceSnapshot:
    directory = ProjectDirectory(
        projects=(
            ProjectEntry(project_id="p1", title="Research project"),
            ProjectEntry(project_id="p2", title="Second project"),
        ),
        permissions=frozenset(Permission),
    )
    return WorkspaceSnapshot(
        directory,
        project,
        session,
        SessionPage(
            sessions=(
                SessionEntry(
                    session_id="s1" if project == "p1" else "s2",
                    project_id=project,
                    title="Research conversation",
                ),
            )
        ),
        None,
        (),
        ContextSearch(
            items=(),
            next_cursor=None,
            snapshot_id="test",
            candidate_window=20,
            window_full=False,
        ),
        TaskState(
            version=1,
            updated_at=utcnow(),
            source_available=True,
            content=WorkState(
                project_id=project,
                task_id="project-work",
                source_session_id=session,
                source_event_id="original",
                goal="Write the report",
                pending=("Review the paper",),
            ),
        ),
    )


@pytest.fixture(autouse=True)
def offline(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[tuple[str, str], WorkspaceSnapshot]:
    saved: dict[tuple[str, str], WorkspaceSnapshot] = {
        ("p1", "s1"): snapshot(),
        ("p2", "s2"): snapshot("p2", "s2"),
    }

    async def load(
        project_id: str | None = None, session_id: str | None = None
    ) -> WorkspaceSnapshot:
        project = project_id or "p1"
        session = session_id or ("s1" if project == "p1" else "s2")
        return saved.get(
            (project, session),
            replace(
                snapshot(project, session),
                sessions=SessionPage(
                    sessions=tuple(row for row in snapshot(project).sessions.sessions)
                ),
            ),
        )

    async def send(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        documents: dict[str, str],
        *,
        require_sources: bool = False,
    ) -> WorkspaceTurn:
        previous = saved.get((current.project_id, current.session_id), current)
        turn = ConversationTurn(
            pending.message,
            result("Answer to: " + pending.message),
            event_id=ResearchAssistant.event_identifier(
                current.session_id, pending.turn_id
            ),
        )
        stream = previous.stream or Stream(
            tenant_id="t1",
            user_id="u1",
            session_id=current.session_id,
            project_id=current.project_id,
        )
        stream = append_event(
            stream,
            principal(projects=[current.project_id]),
            event(
                len(stream.events) + 1,
                event_id=ResearchAssistant.event_identifier(
                    current.session_id, pending.turn_id
                ),
                session_id=current.session_id,
                project_id=current.project_id,
                text=pending.message,
            ),
            max_events=32,
        )
        saved[(current.project_id, current.session_id)] = replace(
            previous, stream=stream, history=(*previous.history, turn)
        )
        return WorkspaceTurn(result=turn.result, task=previous.task)

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        target = (
            await load(selected_project_id, None) if selected_project_id else current
        )
        return service.PreparedTurn(
            snapshot=target,
            pending=pending.model_copy(
                update={
                    "project_id": target.project_id,
                    "session_id": target.session_id,
                    "routed": True,
                }
            ),
            clarification=None,
            candidates=(),
        )

    monkeypatch.setattr(service, "load", load)
    monkeypatch.setattr(service, "send", send)
    monkeypatch.setattr(service, "prepare", prepare)
    return saved


def page() -> AppTest:
    return AppTest.from_file(str(PAGE), default_timeout=20).run()


def button(app: AppTest, label: str):
    return next(entry for entry in app.button if entry.label == label)


def test_workspace_initial_render_has_chat_navigation_and_automatic_context() -> None:
    app = page()
    assert not app.exception
    assert app.title[0].value == "Research project"
    assert not app.chat_input[0].disabled
    assert app.radio(key="ace_source_mode").value == "Project memory"
    assert button(app, "New conversation")
    assert not any(
        entry.label in ("Save progress", "Continue your work") for entry in app.button
    )
    assert any("saved automatically" in caption.value for caption in app.caption)
    assert any(text.value == "Review the paper" for text in app.text)


def test_chat_persists_each_turn_and_rerun_does_not_submit_again(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    app = page()
    app.chat_input[0].set_value("First question").run()
    assert not app.exception
    assert len(offline[("p1", "s1")].history) == 1
    app.chat_input[0].set_value("Second question").run()
    assert not app.exception
    assert len(offline[("p1", "s1")].history) == 2
    assert len(app.chat_message) == 4
    app.run()
    assert len(offline[("p1", "s1")].history) == 2
    fresh = AppTest.from_file(str(PAGE), default_timeout=20)
    fresh.query_params.update({"project": "p1", "session": "s1"})
    fresh.run()
    assert not fresh.exception
    assert any(text.value == "Answer to: First question" for text in fresh.text)


def test_new_conversation_clears_chat_but_keeps_project_context() -> None:
    app = page()
    app.chat_input[0].set_value("Remember my request").run()
    old = app.query_params["session"]
    button(app, "New conversation").click().run()
    assert not app.exception and app.query_params["session"] != old
    assert not app.chat_message
    assert any(text.value == "Write the report" for text in app.text)
    assert app.radio(key="ace_source_mode").value == "Project memory"


def test_project_switch_uses_authorized_project_and_its_history() -> None:
    app = page()
    app.selectbox(key="ace_project_picker").select("p2").run()
    assert not app.exception
    assert app.title[0].value == "Second project"
    assert app.query_params["project"] == ["p2"]
    assert app.query_params["session"] == ["s2"]
    assert app.session_state["ace_workspace"].project_id == "p2"


def test_failed_turn_retains_same_retry_identifier_without_revealing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fail(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *args: object,
        **kwargs: object,
    ) -> WorkspaceTurn:
        calls.append(pending.turn_id)
        raise RuntimeError("provider-private-secret")

    monkeypatch.setattr(service, "send", fail)
    app = page()
    app.chat_input[0].set_value("Please answer").run()
    assert not app.exception and app.chat_input[0].disabled
    assert len(calls) == 1 and "private-secret" not in str(app.error)
    button(app, "Retry saved request").click().run()
    assert calls == [calls[0], calls[0]]
    assert app.session_state["ace_pending"].message == "Please answer"
    button(app, "New conversation").click().run()
    assert not app.chat_input[0].disabled
    assert "ace_pending" not in app.session_state


def test_recorded_content_stays_plain_text_and_context_can_collapse(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    payload = '![tracking](https://example.org/pixel.png)<script>alert("x")</script>'
    current = offline[("p1", "s1")]
    offline[("p1", "s1")] = replace(
        current, history=(ConversationTurn(payload, result(payload), recorded=True),)
    )
    app = page()
    assert not app.exception
    assert sum(text.value == payload for text in app.text) == 2
    assert all("pixel.png" not in markdown.value for markdown in app.markdown)
    app.toggle(key="ace_show_context").set_value(False).run()
    assert not app.exception
    assert not any(sub.value == "Project context" for sub in app.subheader)


def test_memory_evidence_correction_and_removal_use_existing_services(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    memory = item(
        "m1", text="Preferred style: concise", value="concise", fingerprint="f1"
    )
    current = offline[("p1", "s1")]
    offline[("p1", "s1")] = replace(
        current,
        memory=ContextSearch(
            items=(memory,),
            next_cursor=None,
            snapshot_id="test",
            candidate_window=20,
            window_full=False,
        ),
    )
    corrections: list[PendingTurn] = []
    removals: list[str] = []

    async def evidence(identifier: str) -> list[dict[str, object]]:
        return [{"text": "Actual source statement", "actor_kind": "user"}]

    async def send(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *args: object,
        **kwargs: object,
    ) -> WorkspaceTurn:
        corrections.append(pending)
        return WorkspaceTurn(result=result("Correction recorded"), task=current.task)

    async def remove(value: object) -> None:
        removals.append(memory.item_id)

    monkeypatch.setattr(service, "evidence", evidence)
    monkeypatch.setattr(service, "send", send)
    monkeypatch.setattr(service, "remove", remove)
    app = page()
    button(app, "View evidence").click().run()
    assert not app.exception and any(
        text.value == "Actual source statement" for text in app.text
    )
    app.text_area(key="correction-m1").set_value("Detailed explanations")
    button(app, "Apply correction").click().run()
    assert not app.exception and len(corrections) == 1
    assert (
        corrections[0].correction_target
        and corrections[0].correction_target.expected_fingerprint == "f1"
    )
    assert "Detailed explanations" in corrections[0].message
    button(app, "Remove from memory").click().run()
    assert not app.exception and removals == ["m1"]


def test_renaming_persists_using_api_not_local_only(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    current = offline[("p1", "s1")]
    stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1")
    offline[("p1", "s1")] = replace(current, stream=stream)
    changes: list[tuple[str, str]] = []

    async def rename(session_id: str, title: str) -> None:
        changes.append((session_id, title))

    monkeypatch.setattr(service, "rename", rename)
    app = page()
    app.text_input(key="ace_conversation_title").set_value("My research")
    button(app, "Rename").click().run()
    assert not app.exception and changes == [("s1", "My research")]


def test_optional_web_search_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SearchSettings.model_validate({"api_key": None, "_env_file": None})
    monkeypatch.setattr("agent_context.search.SearchSettings", lambda: settings)
    app = page()
    app.radio(key="ace_source_mode").set_value("Web search").run()
    assert not app.exception and button(app, "Search web").disabled
    assert any("BRAVE_SEARCH_API_KEY" in caption.value for caption in app.caption)


def test_optional_search_uses_validated_sources_without_live_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SearchSettings.model_validate(
        {"api_key": SecretStr("test-key"), "_env_file": None}
    )
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["q"])
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Python information",
                            "url": "https://www.python.org/",
                            "description": "Official information.",
                        }
                    ]
                }
            },
        )

    def provider(value: SearchSettings) -> BraveSearch:
        return BraveSearch(
            value, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr("agent_context.search.SearchSettings", lambda: settings)
    monkeypatch.setattr("agent_context.search.BraveSearch", provider)
    app = page()
    app.radio(key="ace_source_mode").set_value("Web search").run()
    app.text_input(key="ace_search_query").set_value("Python docs").run()
    button(app, "Search web").click().run()
    assert not app.exception and calls == ["Python docs"]
    assert app.checkbox(key="ace_use_web").value
    assert any(
        "https://www.python.org/" in str(link.proto) for link in app.get("link_button")
    )


def test_same_web_source_can_appear_in_multiple_turns(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    source = SearchResult(
        title="Reference",
        url=HttpUrl("https://example.org/research"),
        snippet="Public evidence",
        retrieved_at=utcnow(),
    )
    answer = result().model_copy(update={"citations": (source.document_id,)})
    current = offline[("p1", "s1")]
    offline[("p1", "s1")] = replace(
        current,
        history=(
            ConversationTurn("First", answer, (source,)),
            ConversationTurn("Second", answer, (source,)),
        ),
    )
    app = page()
    assert not app.exception and len(app.get("link_button")) == 2


def test_pending_request_disables_other_actions_that_submit_turns(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    current = offline[("p1", "s1")]
    pending = PendingTurn(
        project_id="p1",
        session_id="s1",
        turn_id="pending",
        message="An interrupted request",
        sequence=1,
    )
    answer = result().model_copy(
        update={"suggested_next_steps": ("Review the budget",)}
    )
    offline[("p1", "s1")] = replace(
        current,
        pending=pending,
        memory=ContextSearch(
            items=(item("m1", fingerprint="f1"),),
            next_cursor=None,
            snapshot_id="test",
            candidate_window=20,
            window_full=False,
        ),
        history=(ConversationTurn("Previous question", answer),),
    )
    app = page()
    assert not app.exception and app.chat_input[0].disabled
    assert (
        button(app, "Add to plan").disabled and button(app, "Apply correction").disabled
    )
    assert not button(app, "View evidence").disabled
    assert app.session_state["ace_pending"].turn_id == "pending"


def test_answer_evidence_remains_accessible_with_context_panel_collapsed(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    current = offline[("p1", "s1")]
    answer = result().model_copy(update={"citations": ("memory:m1",)})
    offline[("p1", "s1")] = replace(
        current, history=(ConversationTurn("Recall", answer, recorded=True),)
    )

    async def evidence(identifier: str) -> list[dict[str, object]]:
        assert identifier == "m1"
        return [{"text": "The exact original statement"}]

    monkeypatch.setattr(service, "evidence", evidence)
    app = page()
    app.toggle(key="ace_show_context").set_value(False).run()
    button(app, "View memory evidence").click().run()
    assert not app.exception
    assert any(text.value == "The exact original statement" for text in app.text)


def test_pending_conversation_evidence_remains_accessible(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    from agent_context.contracts import EventReference

    reference = EventReference(session_id="previous", event_id="change")
    answer = result().model_copy(
        update={
            "citations": (reference.source_id,),
            "context_event_refs": (reference,),
        }
    )
    offline[("p1", "s1")] = replace(
        offline[("p1", "s1")],
        history=(ConversationTurn("Recall", answer, recorded=True),),
    )

    async def source(session_id: str, event_id: str, project_id: str):
        assert (session_id, event_id, project_id) == ("previous", "change", "p1")
        return {"text": "The recorded pending assertion"}

    monkeypatch.setattr(service, "source_event", source)
    app = page()
    button(app, "View conversation evidence").click().run()
    assert not app.exception
    assert any(text.value == "The recorded pending assertion" for text in app.text)


@pytest.mark.parametrize("failed", [False, True])
def test_background_refresh_never_blocks_chat(
    failed: bool,
    monkeypatch: pytest.MonkeyPatch,
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    current = offline[("p1", "s1")]
    stream = append_event(
        Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1"),
        principal(projects=["p1"]),
        event(project_id="p1", background_updates=True),
        max_events=32,
    )
    offline[("p1", "s1")] = replace(current, stream=stream)
    calls = 0

    async def changed(snapshot: WorkspaceSnapshot) -> bool:
        nonlocal calls
        calls += 1
        if failed:
            raise RuntimeError("service unavailable")
        offline[("p1", "s1")] = replace(
            current,
            stream=stream.model_copy(update={"available_sequence": 1}),
            task=current.task.model_copy(update={"version": 2})
            if current.task
            else None,
        )
        return True

    monkeypatch.setattr(service, "background_changed", changed)
    app = page()
    assert calls == 1 and not app.exception and not app.chat_input[0].disabled
    if failed:
        assert any("reconnects" in caption.value for caption in app.caption)
    else:
        assert any("revision 2" in caption.value.lower() for caption in app.caption)


def test_untrusted_navigation_and_memory_labels_do_not_enable_markdown_images(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    current = offline[("p1", "s1")]
    payload = "![tracking](https://example.org/pixel.png)"
    offline[("p1", "s1")] = replace(
        current,
        sessions=SessionPage(
            sessions=(SessionEntry(session_id="s1", project_id="p1", title=payload),)
        ),
        memory=ContextSearch(
            items=(item("m1", text=payload),),
            snapshot_id="test",
            candidate_window=20,
            window_full=False,
        ),
    )
    app = page()
    assert not app.exception
    session = next(value for value in app.button if value.key == "session-s1")
    assert session.label.startswith("\\!\\[")
    assert any(value.label.startswith("\\!\\[") for value in app.expander)
    assert any(value.value == payload for value in app.text)


def test_active_goal_with_no_agreed_steps_is_not_labelled_complete(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    current = offline[("p1", "s1")]
    assert current.task
    offline[("p1", "s1")] = replace(
        current,
        task=current.task.model_copy(
            update={"content": current.task.content.model_copy(update={"pending": ()})}
        ),
    )
    app = page()
    assert not app.exception
    assert any(
        "project is active; no next step has been agreed" in caption.value
        for caption in app.caption
    )
    assert any(text.value == "Write the report" for text in app.text)


def test_project_switch_rejects_a_stale_snapshot_from_the_previous_project(
    monkeypatch: pytest.MonkeyPatch,
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    alpha = offline[("p1", "s1")]
    offline[("p1", "s1")] = replace(
        alpha,
        history=(ConversationTurn("Alpha request", result("Alpha private answer")),),
    )
    app = page()
    assert any(text.value == "Alpha private answer" for text in app.text)

    async def stale(
        project_id: str | None = None, session_id: str | None = None
    ) -> WorkspaceSnapshot:
        return offline[("p1", "s1")]

    monkeypatch.setattr(service, "load", stale)
    app.selectbox(key="ace_project_picker").select("p2").run()
    assert not app.exception
    assert not any(text.value == "Alpha private answer" for text in app.text)
    assert not any(title.value == "Research project" for title in app.title)
    assert "ace_workspace" not in app.session_state
    assert app.chat_input[0].disabled


def test_navigation_changed_during_load_does_not_commit_the_obsolete_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import streamlit as st

    app = page()

    async def superseded(
        project_id: str | None = None, session_id: str | None = None
    ) -> WorkspaceSnapshot:
        st.query_params["project"] = "p1"
        return snapshot("p2", "s2")

    monkeypatch.setattr(service, "load", superseded)
    app.selectbox(key="ace_project_picker").select("p2").run()
    assert not app.exception
    assert app.query_params["project"] == ["p1"]
    assert not any(title.value == "Second project" for title in app.title)
    assert "ace_workspace" not in app.session_state
    assert app.chat_input[0].disabled


def test_automatic_routing_prepares_once_before_sending_and_keeps_choice_on_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared: list[PendingTurn] = []
    attempts: list[PendingTurn] = []

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        assert not pending.manual
        prepared.append(pending)
        return service.PreparedTurn(
            snapshot=current,
            pending=pending.model_copy(update={"routed": True}),
            clarification=None,
            candidates=(),
        )

    async def fail(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *args: object,
        **kwargs: object,
    ) -> WorkspaceTurn:
        attempts.append(pending)
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(service, "prepare", prepare)
    monkeypatch.setattr(service, "send", fail)
    app = page()
    assert app.radio(key="ace_routing_mode").value == "Automatic"
    app.chat_input[0].set_value("Continue the archive project").run()
    assert not app.exception and len(prepared) == 1 and len(attempts) == 1
    assert attempts[0].routed and app.session_state["ace_pending"].routed
    button(app, "Retry saved request").click().run()
    assert not app.exception and len(prepared) == 1 and len(attempts) == 2
    assert attempts[0].turn_id == attempts[1].turn_id


def test_automatic_route_switches_scope_before_the_message_is_recorded(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    old = offline[("p1", "s1")]
    offline[("p1", "s1")] = replace(
        old,
        history=(
            ConversationTurn("Old project question", result("Alpha private answer")),
        ),
    )

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        target = offline[("p2", "s2")]
        return service.PreparedTurn(
            snapshot=target,
            pending=pending.model_copy(
                update={"project_id": "p2", "session_id": "s2", "routed": True}
            ),
            clarification=None,
            candidates=(),
        )

    monkeypatch.setattr(service, "prepare", prepare)
    app = page()
    app.session_state["ace_evidence"] = [{"text": "Alpha evidence"}]
    app.chat_input[0].set_value("Continue the second project").run()
    assert not app.exception
    assert app.query_params["project"] == ["p2"] and app.query_params["session"] == [
        "s2"
    ]
    assert (
        len(offline[("p1", "s1")].history) == 1
        and len(offline[("p2", "s2")].history) == 1
    )
    assert any(
        text.value == "Answer to: Continue the second project" for text in app.text
    )
    assert not any(
        text.value in ("Alpha private answer", "Alpha evidence") for text in app.text
    )


def test_ambiguous_project_waits_for_an_explicit_choice_without_sending(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    decisions: list[str | None] = []

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        decisions.append(selected_project_id)
        if selected_project_id:
            target = offline[
                (selected_project_id, "s2" if selected_project_id == "p2" else "s1")
            ]
            return service.PreparedTurn(
                snapshot=target,
                pending=pending.model_copy(
                    update={
                        "project_id": target.project_id,
                        "session_id": target.session_id,
                        "routed": True,
                        "manual": True,
                    }
                ),
                clarification=None,
                candidates=(),
            )
        return service.PreparedTurn(
            snapshot=current,
            pending=pending,
            clarification="Which project do you mean?",
            candidates=current.directory.projects,
        )

    monkeypatch.setattr(service, "prepare", prepare)
    app = page()
    app.chat_input[0].set_value("Continue the project").run()
    assert not app.exception and decisions == [None]
    assert not offline[("p1", "s1")].history and not offline[("p2", "s2")].history
    assert app.chat_input[0].disabled
    app.selectbox(key="ace_route_project").select("p2").run()
    button(app, "Use selected project").click().run()
    assert not app.exception and decisions == [None, "p2"]
    assert len(offline[("p2", "s2")].history) == 1 and not offline[("p1", "s1")].history


def test_cancel_ambiguous_request_discards_only_the_unsent_message(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        return service.PreparedTurn(
            snapshot=current,
            pending=pending,
            clarification="Please identify the project.",
            candidates=(),
        )

    monkeypatch.setattr(service, "prepare", prepare)
    app = page()
    app.chat_input[0].set_value("Continue").run()
    assert not app.exception and app.chat_input[0].disabled
    button(app, "Cancel unsent request").click().run()
    assert not app.exception and not app.chat_input[0].disabled
    assert "ace_pending" not in app.session_state and not offline[("p1", "s1")].history


def test_rephrased_routing_request_keeps_the_revised_text_and_gets_a_new_identity(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    proposals: list[PendingTurn] = []

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        proposals.append(pending)
        if "archive" in pending.message:
            return service.PreparedTurn(
                snapshot=current,
                pending=pending.model_copy(update={"routed": True}),
                clarification=None,
                candidates=(),
            )
        return service.PreparedTurn(
            snapshot=current,
            pending=pending,
            clarification="Which project?",
            candidates=(),
        )

    monkeypatch.setattr(service, "prepare", prepare)
    app = page()
    app.chat_input[0].set_value("Continue").run()
    app.text_area(key="ace_route_rephrase").set_value("Continue the archive project")
    button(app, "Try revised request").click().run()
    assert not app.exception and len(proposals) == 2
    assert proposals[0].turn_id != proposals[1].turn_id
    assert offline[("p1", "s1")].history[0].message == "Continue the archive project"


def test_project_picker_is_a_manual_override_until_automatic_is_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manual: list[bool] = []

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        manual.append(pending.manual)
        return service.PreparedTurn(
            snapshot=current,
            pending=pending.model_copy(update={"routed": True}),
            clarification=None,
            candidates=(),
        )

    monkeypatch.setattr(service, "prepare", prepare)
    app = page()
    app.selectbox(key="ace_project_picker").select("p2").run()
    assert app.radio(key="ace_routing_mode").value == "Selected project"
    app.chat_input[0].set_value("A selected-project message").run()
    app.radio(key="ace_routing_mode").set_value("Automatic").run()
    button(app, "New conversation").click().run()
    app.chat_input[0].set_value("An automatic message").run()
    assert not app.exception and manual == [True, False]


def test_routing_provider_failure_keeps_unsent_text_and_allows_manual_choice(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    calls: list[str | None] = []

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        calls.append(selected_project_id)
        if selected_project_id is None:
            raise RuntimeError("provider details must stay private")
        return service.PreparedTurn(
            current, pending.model_copy(update={"routed": True, "manual": True})
        )

    monkeypatch.setattr(service, "prepare", prepare)
    app = page()
    app.chat_input[0].set_value("Continue my existing work").run()
    assert not app.exception and not offline[("p1", "s1")].history
    assert app.session_state["ace_pending"].message == "Continue my existing work"
    assert any("selection could not complete" in info.value for info in app.info)
    button(app, "Use selected project").click().run()
    assert not app.exception and calls == [None, "p1"]
    assert len(offline[("p1", "s1")].history) == 1


def test_project_alias_edit_keeps_the_same_identity(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    from agent_context.navigation import ProjectEdit

    current = offline[("p1", "s1")]
    directory = current.directory.model_copy(
        update={
            "projects": tuple(
                entry.model_copy(update={"managed": True})
                if entry.project_id == "p1"
                else entry
                for entry in current.directory.projects
            )
        }
    )
    offline[("p1", "s1")] = replace(current, directory=directory)
    edits: list[tuple[str, ProjectEdit]] = []

    async def edit(identifier: str, request: ProjectEdit) -> ProjectEntry:
        edits.append((identifier, request))
        return ProjectEntry(
            project_id=identifier,
            title=request.title,
            aliases=request.aliases or (),
            managed=True,
            version=2,
        )

    monkeypatch.setattr(service, "edit_project", edit)
    app = page()
    next(value for value in app.text_input if value.label == "Project name").set_value(
        "Town archive"
    )
    next(
        value for value in app.text_area if value.label.startswith("Aliases")
    ).set_value("Local history\nArchives")
    button(app, "Update project").click().run()
    assert not app.exception and edits[0][0] == "p1"
    assert edits[0][1].aliases == ("Local history", "Archives")
    assert app.query_params["project"] == ["p1"]


def test_explicit_sources_survive_automatic_scope_change_for_the_pending_request(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
    ) -> service.PreparedTurn:
        return service.PreparedTurn(
            offline[("p2", "s2")],
            pending.model_copy(
                update={"project_id": "p2", "session_id": "s2", "routed": True}
            ),
        )

    captured: list[dict[str, str]] = []
    original = service.send

    async def send(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        documents: dict[str, str],
        *,
        require_sources: bool = False,
    ) -> WorkspaceTurn:
        captured.append(documents)
        return await original(
            current, pending, documents, require_sources=require_sources
        )

    monkeypatch.setattr(service, "prepare", prepare)
    monkeypatch.setattr(service, "send", send)
    app = page()
    app.radio(key="ace_source_mode").set_value("Sample brief").run()
    app.chat_input[0].set_value("Use the brief for my second project").run()
    assert not app.exception and "research-brief" in captured[0]
    assert app.radio(key="ace_source_mode").value == "Project memory"


def test_owned_project_titles_remain_literal_text_in_heading_and_scope_caption(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    current = offline[("p1", "s1")]
    payload = "![tracking](https://example.org/pixel.png)"
    directory = current.directory.model_copy(
        update={
            "projects": tuple(
                entry.model_copy(update={"title": payload, "managed": True})
                if entry.project_id == "p1"
                else entry
                for entry in current.directory.projects
            )
        }
    )
    offline[("p1", "s1")] = replace(current, directory=directory)
    app = page()
    assert not app.exception and app.title[0].value.startswith("\\!\\[")
    assert any("\\!\\[" in caption.value for caption in app.caption)
    assert all("![tracking]" not in markdown.value for markdown in app.markdown)


def test_uncertain_new_project_can_be_explicitly_confirmed_without_using_an_existing_one(
    monkeypatch: pytest.MonkeyPatch, offline: dict[tuple[str, str], WorkspaceSnapshot]
) -> None:
    confirmations: list[str] = []

    async def prepare(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *,
        selected_project_id: str | None = None,
        new_project_name: str | None = None,
    ) -> service.PreparedTurn:
        if new_project_name is None:
            return service.PreparedTurn(
                current, pending, "Confirm the project", current.directory.projects
            )
        confirmations.append(new_project_name)
        return service.PreparedTurn(
            offline[("p2", "s2")],
            pending.model_copy(
                update={
                    "project_id": "p2",
                    "session_id": "s2",
                    "routed": True,
                    "manual": True,
                }
            ),
        )

    monkeypatch.setattr(service, "prepare", prepare)
    app = page()
    app.chat_input[0].set_value("I am organizing Cedar Clay workshop").run()
    app.text_input(key="ace_new_project_name").set_value("Cedar Clay")
    button(app, "Create and use project").click().run()
    assert not app.exception and confirmations == ["Cedar Clay"]
    assert len(offline[("p2", "s2")].history) == 1 and not offline[("p1", "s1")].history
