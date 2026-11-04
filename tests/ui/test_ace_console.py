"""The new console renders without exposing credentials or making model calls."""

from pathlib import Path
import httpx
import pytest
from pydantic import SecretStr
from streamlit.testing.v1 import AppTest
from agent_context.search import BraveSearch, SearchSettings
from agent_context.assembly import ContextBundle
from agent_context.demo import ResearchTurn
from tests.unit.test_assembly import item


def test_context_console_initial_render() -> None:
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Agent Context Engine"
    assert any(button.label == "Send" and button.disabled for button in app.button)
    assert any(
        button.label == "Save handoff" and button.disabled for button in app.button
    )
    assert any("selected context" in info.value for info in app.info)


def test_web_search_is_optional_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SearchSettings.model_validate({"api_key": None, "_env_file": None})
    monkeypatch.setattr("agent_context.search.SearchSettings", lambda: settings)
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    assert not app.exception
    assert any(
        button.label == "Search web" and button.disabled for button in app.button
    )
    assert any("BRAVE_SEARCH_API_KEY" in info.value for info in app.info)
    assert any(input.label == "Message" for input in app.text_area)


def test_search_button_populates_validated_sources_without_live_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SearchSettings.model_validate(
        {"api_key": SecretStr("unit-search-key"), "_env_file": None}
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.params["q"])
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Public source",
                            "url": "https://www.python.org/",
                            "description": "Official Python information.",
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
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    app.text_input(key="ace_search_query").set_value("Python documentation").run()
    next(button for button in app.button if button.label == "Search web").click().run()
    assert not app.exception
    assert requests == ["Python documentation"]
    assert any(text.value == "Public source" for text in app.text)
    assert app.checkbox(key="ace_use_web").value
    assert any(
        "https://www.python.org/" in str(link.proto) for link in app.get("link_button")
    )


def test_new_session_clears_previous_input_answer_context_and_sources() -> None:
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    previous_session = app.session_state["ace_session"]
    bundle = ContextBundle(bundle_id="old-bundle", tokenizer_version="test", items=(
        item("old-memory", text="Old answer context", evidence_ids=("old-episode",)),
    ), rendered="[]", token_count=1, exclusions=(), excluded_counts={})
    app.session_state["ace_result"] = ResearchTurn(
        answer="Previous session answer", bundle=bundle, next_sequence=3,
        citations=("memory:old-memory",),
    )
    app.session_state["ace_handoff"] = "saved-handoff"
    app.session_state["ace_handoff_version"] = 2
    app.text_area(key="ace_message").set_value("Previous message").run()
    app.text_input(key="ace_search_query").set_value("Previous query").run()
    assert any("Previous session answer" in text.value for text in app.text)
    assert any("Memory evidence: old-episode" in caption.value for caption in app.caption)
    next(button for button in app.button if button.label == "New session").click().run()
    assert not app.exception
    assert app.session_state["ace_session"] != previous_session
    assert app.session_state["ace_handoff"] == "saved-handoff"
    assert app.session_state["ace_handoff_version"] == 2
    assert not app.text_area(key="ace_message").value
    assert not app.text_input(key="ace_search_query").value
    assert not any("Previous session answer" in text.value for text in app.text)
    assert not any("Old answer context" in text.value for text in app.text)
    assert any(button.label == "Save handoff" and button.disabled for button in app.button)
