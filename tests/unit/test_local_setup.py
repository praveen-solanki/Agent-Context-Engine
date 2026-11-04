"""A fresh launcher config is usable without rotating existing identities."""

from __future__ import annotations

from pathlib import Path
import sys

from dotenv import dotenv_values, set_key
from pydantic import ValidationError
import pytest

from agent_context import local_setup


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in tuple(local_setup.os.environ):
        if name.startswith("ACE_") or name in {"NVIDIA_API_KEY", "CG_NEO4J__PASSWORD"}:
            monkeypatch.delenv(name)
    Path(".env.example").write_text(
        "NVIDIA_API_KEY=change-me\nCG_NEO4J__PASSWORD=change-me\n"
    )
    ca = tmp_path / "test-ca.pem"
    ca.write_text("test-only CA path; no network calls")
    monkeypatch.setenv("ACE_CA_BUNDLE", str(ca))
    monkeypatch.setenv("NVIDIA_API_KEY", "synthetic-test-key")
    return tmp_path


def test_fresh_configuration_is_private_and_repeatable(checkout: Path) -> None:
    assert local_setup.configure() == (
        "http://127.0.0.1:18000", "http://127.0.0.1:8501", 8501
    )
    path = checkout / ".env"
    values = dotenv_values(path)
    assert values["CG_NEO4J__PASSWORD"] not in {None, "", "change-me"}
    assert values["NVIDIA_API_KEY"] == "change-me"  # inherited secret stays out of files
    assert path.stat().st_mode & 0o777 == 0o600
    snapshot = path.read_bytes()
    local_setup.configure()
    assert path.read_bytes() == snapshot


def test_existing_credentials_and_custom_settings_survive(checkout: Path) -> None:
    local_setup.configure()
    set_key(".env", "CG_NEO4J__PASSWORD", "existing-database-password")
    set_key(".env", "BRAVE_SEARCH_API_KEY", "synthetic-search-key")
    before = dotenv_values(".env")
    local_setup.configure()
    assert dotenv_values(".env") == before


def test_custom_ports_and_local_api_override(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACE_EXTERNAL_PORT", "18200")
    monkeypatch.setenv("ACE_UI_PORT", "8502")
    assert local_setup.configure() == (
        "http://127.0.0.1:18200", "http://127.0.0.1:8502", 8502
    )
    assert dotenv_values(".env")["ACE_API_URL"] == "http://127.0.0.1:18200"


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_ports_fail_before_startup(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, port: str
) -> None:
    monkeypatch.setenv("ACE_UI_PORT", port)
    with pytest.raises(ValidationError):
        local_setup.configure()


def test_api_and_ui_cannot_share_port(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ACE_UI_PORT", "18000")
    with pytest.raises(ValueError, match="must be different"):
        local_setup.configure()


def test_incomplete_existing_authentication_is_not_replaced(checkout: Path) -> None:
    local_setup.configure()
    set_key(".env", "ACE_DEMO_USER_TOKEN", "mismatched-token")
    snapshot = Path(".env").read_bytes()
    with pytest.raises(ValueError, match="incomplete local authentication"):
        local_setup.configure()
    assert Path(".env").read_bytes() == snapshot


def test_missing_key_fails_noninteractively_without_exposing_configuration(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    with pytest.raises(ValueError, match="Set NVIDIA_API_KEY"):
        local_setup.configure()


def test_first_run_prompts_for_a_key_without_echoing_it(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def enter_key(_prompt: str) -> str:
        return "synthetic-entered-key"

    monkeypatch.setattr(local_setup.getpass, "getpass", enter_key)
    local_setup.configure()
    assert dotenv_values(".env")["NVIDIA_API_KEY"] == "synthetic-entered-key"
    output = capsys.readouterr()
    assert "synthetic-entered-key" not in output.out + output.err


def test_missing_ca_bundle_fails_without_changing_existing_settings(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_setup.configure()
    snapshot = Path(".env").read_bytes()
    monkeypatch.setenv("ACE_CA_BUNDLE", str(checkout / "missing.pem"))
    with pytest.raises(ValueError, match="existing CA"):
        local_setup.configure()
    assert Path(".env").read_bytes() == snapshot


def test_main_hides_validation_input_values(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ACE_UI_PORT", "synthetic-sensitive-invalid-value")
    with pytest.raises(SystemExit, match="Invalid local configuration"):
        local_setup.main()
    output = capsys.readouterr()
    assert "synthetic-sensitive-invalid-value" not in output.out + output.err


def test_placeholder_in_environment_cannot_shadow_a_prompted_key(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "change-me")
    with pytest.raises(ValueError, match="placeholder in the environment"):
        local_setup.configure()


def test_explicit_database_password_is_not_rotated(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CG_NEO4J__PASSWORD", "inherited-password")
    local_setup.configure()
    assert dotenv_values(".env")["CG_NEO4J__PASSWORD"] == "change-me"
