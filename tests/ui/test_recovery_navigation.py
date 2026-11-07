"""Real Streamlit reruns for recovery navigation and widget ownership."""

import pytest

from agent_context.continuity import WorkspaceTurn
from ui import workspace as service
from ui.workspace import PendingTurn, WorkspaceSnapshot
from tests.ui.test_ace_console import button, offline as offline, page


@pytest.mark.parametrize(
    "source_mode", ["Project memory", "Sample brief", "Web search"]
)
def test_failed_send_can_open_another_conversation_after_source_widgets_render(
    source_mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[PendingTurn] = []

    async def fail(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *args: object,
        **kwargs: object,
    ) -> WorkspaceTurn:
        calls.append(pending)
        raise RuntimeError("provider failure")

    monkeypatch.setattr(service, "send", fail)
    app = page()
    app.radio(key="ace_source_mode").set_value(source_mode).run()
    if source_mode == "Web search":
        app.text_input(key="ace_search_query").set_value("old project query").run()
    app.chat_input[0].set_value("Please answer this request").run()
    old = app.query_params["session"]
    assert not app.exception and len(calls) == 1
    assert app.session_state["ace_pending"].routed
    button(app, "Open another conversation").click().run()
    assert not app.exception
    assert app.query_params["session"] != old
    assert app.radio(key="ace_source_mode").value == "Project memory"
    assert "ace_pending" not in app.session_state
    assert not app.chat_message and not app.chat_input[0].disabled
    assert "ace_search_query" not in app.session_state
    assert any(text.value == "Write the report" for text in app.text)
    assert len(calls) == 1


def test_retry_keeps_frozen_sources_and_recovery_clears_only_view_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    async def fail(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        documents: dict[str, str],
        **kwargs: object,
    ) -> WorkspaceTurn:
        calls.append((pending.turn_id, documents))
        raise RuntimeError("provider failure")

    monkeypatch.setattr(service, "send", fail)
    app = page()
    app.radio(key="ace_source_mode").set_value("Sample brief").run()
    app.chat_input[0].set_value("Compare the options").run()
    app.radio(key="ace_source_mode").set_value("Project memory").run()
    button(app, "Retry saved request").click().run()
    assert not app.exception and len(calls) == 2
    assert calls[0] == calls[1] and "research-brief" in calls[0][1]
    button(app, "Open another conversation").click().run()
    assert not app.exception and "ace_pending" not in app.session_state
    assert len(calls) == 2


def test_query_navigation_resets_source_widgets_before_new_project_render(
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    app = page()
    app.radio(key="ace_source_mode").set_value("Web search").run()
    app.text_input(key="ace_search_query").set_value("private old query").run()
    app.query_params["project"] = "p2"
    app.query_params["session"] = "s2"
    app.run()
    assert not app.exception and app.title[0].value == "Second project"
    assert app.radio(key="ace_source_mode").value == "Project memory"
    assert "ace_search_query" not in app.session_state
    assert app.session_state["ace_workspace"].project_id == "p2"


def test_cancelling_ambiguous_request_resets_routing_widgets_without_losing_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def clarify(
        current: WorkspaceSnapshot, pending: PendingTurn, **kwargs: object
    ) -> service.PreparedTurn:
        return service.PreparedTurn(
            current, pending, "Which project?", current.directory.projects
        )

    monkeypatch.setattr(service, "prepare", clarify)
    app = page()
    app.radio(key="ace_source_mode").set_value("Sample brief").run()
    app.chat_input[0].set_value("Continue this project").run()
    app.text_area(key="ace_route_rephrase").set_value("Discard this draft").run()
    button(app, "Cancel unsent request").click().run()
    assert not app.exception and "ace_pending" not in app.session_state
    assert app.radio(key="ace_source_mode").value == "Sample brief"
    assert "ace_route_rephrase" not in app.session_state
    assert not app.chat_input[0].disabled


def test_recovery_preserves_recorded_old_conversation_and_opens_clean_view(
    monkeypatch: pytest.MonkeyPatch,
    offline: dict[tuple[str, str], WorkspaceSnapshot],
) -> None:
    app = page()
    app.chat_input[0].set_value("Previously saved conversation").run()
    original = offline[("p1", "s1")]
    assert len(original.history) == 1

    async def fail(
        current: WorkspaceSnapshot,
        pending: PendingTurn,
        *args: object,
        **kwargs: object,
    ) -> WorkspaceTurn:
        raise RuntimeError("failed second answer")

    monkeypatch.setattr(service, "send", fail)
    app.radio(key="ace_source_mode").set_value("Sample brief").run()
    app.chat_input[0].set_value("A second request fails").run()
    button(app, "Open another conversation").click().run()
    assert not app.exception and not app.chat_message
    assert offline[("p1", "s1")] == original
    assert app.query_params["session"] != ["s1"]
    assert app.radio(key="ace_source_mode").value == "Project memory"
