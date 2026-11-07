"""Known failure classes receive actionable, content-free recovery messages."""

import httpx
import pytest

from agent_context import client as client_module
from agent_context.continuity import WorkspaceTurn
from context_graph.errors import ExtractionValidationError, ProviderError
from tests.ui.test_ace_console import offline as offline, page
from ui import workspace as service
from ui.workspace import PendingTurn, WorkspaceSnapshot


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("service", "workspace service"),
        ("model", "model service"),
        ("schema", "model response"),
        ("timeout", "timed out"),
        ("stopped", "background memory processing stopped"),
        ("503", "workspace service"),
        ("500", "workspace service"),
        ("429", "rate limit"),
    ],
)
def test_known_failure_has_safe_actionable_explanation(
    kind: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(
        snapshot: WorkspaceSnapshot,
        pending: PendingTurn,
        *args: object,
        **kwargs: object,
    ) -> WorkspaceTurn:
        errors = {
            "service": httpx.ConnectError("PRIVATE_URL"),
            "model": ProviderError("PRIVATE_PROVIDER"),
            "schema": ExtractionValidationError("PRIVATE_RESPONSE"),
            "timeout": TimeoutError("PRIVATE_TIMEOUT"),
            "stopped": getattr(client_module, "EventProcessingStopped", RuntimeError)(
                "PRIVATE_EVENT"
            ),
        }
        if kind.isdigit():
            request = httpx.Request(
                "POST", "http://private.invalid/v1/context/assemble"
            )
            raise httpx.HTTPStatusError(
                "PRIVATE_INTERNAL",
                request=request,
                response=httpx.Response(
                    int(kind), request=request, text="PRIVATE_RESPONSE"
                ),
            )
        raise errors[kind]

    monkeypatch.setattr(service, "send", fail)
    app = page()
    app.chat_input[0].set_value("Recall the project").run()
    assert not app.exception
    assert any(expected in error.value for error in app.error)
    assert all("PRIVATE" not in error.value for error in app.error)
