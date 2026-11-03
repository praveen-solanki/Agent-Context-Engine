"""The new console renders without exposing credentials or making model calls."""

from pathlib import Path
from streamlit.testing.v1 import AppTest


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
