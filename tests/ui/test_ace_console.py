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

    monkeypatch.setattr(service, "load", load)
    monkeypatch.setattr(service, "send", send)
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
