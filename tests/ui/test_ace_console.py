"""The new console renders without exposing credentials or making model calls."""

from pathlib import Path
import httpx
import pytest
from pydantic import HttpUrl, SecretStr
from streamlit.testing.v1 import AppTest
from agent_context.search import BraveSearch, SearchSettings
from agent_context.assembly import ContextBundle
from agent_context.demo import ResearchTurn
from agent_context.demo import ResearchAssistant
from agent_context.client import AgentContextClient
from agent_context.contracts import utcnow
from agent_context.handoff import HandoffArtifact, HandoffInput
from agent_context.search import SearchResult
from tests.unit.test_assembly import item
from ui.context_engine_view import ConversationTurn


def test_context_console_initial_render() -> None:
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Agent Context Engine"
    assert len(app.chat_input) == 1 and not app.chat_input[0].disabled
    assert any(
        button.label == "Save progress" and button.disabled for button in app.button
    )
    assert not app.json
    assert any(button.label == "Compare the sample options" for button in app.button)
    assert any(expander.label == "Project notes" for expander in app.expander)


def test_web_search_is_optional_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SearchSettings.model_validate({"api_key": None, "_env_file": None})
    monkeypatch.setattr("agent_context.search.SearchSettings", lambda: settings)
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    app.radio(key="ace_source_mode").set_value("Web search").run()
    assert not app.exception
    assert any(
        button.label == "Search web" and button.disabled for button in app.button
    )
    assert any("BRAVE_SEARCH_API_KEY" in caption.value for caption in app.caption)
    assert len(app.chat_input) == 1


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
    app.radio(key="ace_source_mode").set_value("Web search").run()
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
    app.session_state["ace_conversation"] = [ConversationTurn(
        "Previous message", app.session_state["ace_result"],
    )]
    app.session_state["ace_handoff"] = "saved-handoff"
    app.session_state["ace_handoff_version"] = 2
    app.radio(key="ace_source_mode").set_value("Web search").run()
    app.text_input(key="ace_search_query").set_value("Previous query").run()
    assert any("Previous session answer" in text.value for text in app.text)
    assert any("Memory evidence: old-episode" in caption.value for caption in app.caption)
    next(button for button in app.button if button.label == "New session").click().run()
    assert not app.exception
    assert app.session_state["ace_session"] != previous_session
    assert app.session_state["ace_handoff"] == "saved-handoff"
    assert app.session_state["ace_handoff_version"] == 2
    assert not app.chat_input[0].value
    assert app.radio(key="ace_source_mode").value == "Sample brief"
    assert not app.session_state["ace_search_query"]
    assert not app.session_state["ace_conversation"]
    assert not any("Previous session answer" in text.value for text in app.text)
    assert not any("Old answer context" in text.value for text in app.text)
    assert any(button.label == "Save progress" and button.disabled for button in app.button)


def result(answer: str = "A recorded answer") -> ResearchTurn:
    return ResearchTurn(
        answer=answer,
        bundle=ContextBundle(bundle_id="bundle", tokenizer_version="test", items=(),
                             rendered="", token_count=0, exclusions=(), excluded_counts={}),
        next_sequence=4,
    )


def test_conversation_keeps_each_answer_and_only_submits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACE_DEMO_USER_TOKEN", "u" * 40)
    monkeypatch.setenv("ACE_DEMO_AGENT_TOKEN", "h" * 40)
    requests: list[dict[str, object]] = []

    async def respond(self: ResearchAssistant, **values: object) -> ResearchTurn:
        requests.append(values)
        return result("Answer to: " + str(values["message"]))

    monkeypatch.setattr(ResearchAssistant, "turn", respond)
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    app.chat_input[0].set_value("First question").run()
    assert not app.exception
    assert len(requests) == 1
    assert any(button.label == "Save progress" and not button.disabled for button in app.button)
    app.chat_input[0].set_value("Second question").run()
    assert not app.exception
    assert len(requests) == 2
    assert requests[0]["turn_id"] == "turn-0" and requests[1]["turn_id"] == "turn-1"
    assert requests[1]["sequence"] == 4
    assert len(app.chat_message) == 4
    assert any(text.value == "Answer to: First question" for text in app.text)
    assert any(text.value == "Answer to: Second question" for text in app.text)
    app.run()
    assert len(requests) == 2
    next(button for button in app.button if button.label == "New session").click().run()
    assert not app.chat_message


def test_starter_sends_a_visible_request_through_the_existing_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACE_DEMO_USER_TOKEN", "u" * 40)
    monkeypatch.setenv("ACE_DEMO_AGENT_TOKEN", "h" * 40)
    requests: list[str] = []

    async def respond(self: ResearchAssistant, **values: object) -> ResearchTurn:
        requests.append(str(values["message"]))
        return result()

    monkeypatch.setattr(ResearchAssistant, "turn", respond)
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    next(button for button in app.button if button.label == "Compare the sample options").click().run()
    assert not app.exception and len(requests) == 1
    assert "research-brief" in requests[0]
    assert any(text.value == requests[0] for text in app.text)
    assert any(text.value == "A recorded answer" for text in app.text)


def test_failed_request_preserves_history_and_does_not_advance_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACE_DEMO_USER_TOKEN", "u" * 40)
    monkeypatch.setenv("ACE_DEMO_AGENT_TOKEN", "h" * 40)

    async def fail(self: ResearchAssistant, **values: object) -> ResearchTurn:
        raise RuntimeError("private-provider-error-must-not-appear")

    monkeypatch.setattr(ResearchAssistant, "turn", fail)
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    app.chat_input[0].set_value("Please answer").run()
    assert not app.exception
    assert app.error and "could not complete" in app.error[0].value
    assert "private-provider-error" not in app.error[0].value
    assert app.session_state["ace_sequence"] == 1
    assert app.session_state["ace_turn"] == 0
    assert not app.session_state["ace_conversation"]


def test_same_web_source_can_be_shown_in_multiple_conversation_turns() -> None:
    source = SearchResult(title="A source", url=HttpUrl("https://example.org/research"),
                          snippet="Public evidence.", retrieved_at=utcnow())
    answer = result().model_copy(update={"citations": (source.document_id,)})
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    app.session_state["ace_conversation"] = [
        ConversationTurn("First question", answer, (source,)),
        ConversationTurn("Second question", answer, (source,)),
    ]
    app.run()
    assert not app.exception
    assert len(app.get("link_button")) == 2


def test_progress_controls_send_the_same_handoff_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACE_DEMO_USER_TOKEN", "u" * 40)
    requests: list[HandoffInput] = []

    async def save(self: AgentContextClient, request: HandoffInput) -> HandoffArtifact:
        requests.append(request)
        return HandoffArtifact(version=1, content=request)

    monkeypatch.setattr(AgentContextClient, "prepare_handoff", save)
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    app.session_state["ace_result"] = result()
    app.session_state["ace_conversation"] = [ConversationTurn("A request", result())]
    app.text_input(key="ace_goal").set_value("Compare the options").run()
    app.text_area(key="ace_pending").set_value("Confirm the budget\nWrite a summary").run()
    next(button for button in app.button if button.label == "Save progress").click().run()
    assert not app.exception and len(requests) == 1
    assert requests[0].goal == "Compare the options"
    assert requests[0].pending == ("Confirm the budget", "Write a summary")
    assert requests[0].source_session_id == app.session_state["ace_session"]
    assert app.session_state["ace_handoff"] == requests[0].handoff_id
    next(button for button in app.button if button.label == "New session").click().run()
    assert app.session_state["ace_handoff"] == requests[0].handoff_id
    assert not app.session_state["ace_conversation"]


def test_untrusted_conversation_content_stays_plain_text() -> None:
    payload = '![tracking](https://example.org/pixel.png)<script>alert("x")</script>'
    page = Path(__file__).resolve().parents[2] / "ui" / "context_engine.py"
    app = AppTest.from_file(str(page), default_timeout=30).run()
    app.session_state["ace_conversation"] = [ConversationTurn(payload, result(payload))]
    app.run()
    assert not app.exception
    assert sum(text.value == payload for text in app.text) == 2
    assert all("pixel.png" not in markdown.value for markdown in app.markdown)
