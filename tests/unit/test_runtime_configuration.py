"""Authentication registries must be replaced atomically across settings sources."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_context.runtime import RuntimeSettings
from tests.unit.test_event_contracts import principal


def test_environment_registry_replaces_dotenv_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    lower = {"b" * 64: principal(tenant_id="old-tenant").model_dump(mode="json")}
    (tmp_path / ".env").write_text("ACE_AUTH_BINDINGS='" + json.dumps(lower) + "'\n")
    higher = {"a" * 64: principal().model_dump(mode="json")}
    monkeypatch.setenv("ACE_TENANT_ID", "t1")
    monkeypatch.setenv("ACE_USER_ID", "u1")
    monkeypatch.setenv("ACE_AUTH_BINDINGS", json.dumps(higher))
    settings = RuntimeSettings()
    assert set(settings.auth_bindings) == {"a" * 64}


def test_invalid_runtime_settings_do_not_echo_sensitive_input() -> None:
    with pytest.raises(ValueError) as failure:
        RuntimeSettings(
            tenant_id="t1",
            user_id="u1",
            auth_bindings={"a" * 64: principal(user_id="SENSITIVE_SENTINEL")},
        )
    assert "SENSITIVE_SENTINEL" not in str(failure.value)
