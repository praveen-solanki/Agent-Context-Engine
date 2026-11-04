"""Idempotent private configuration for the local shell launcher."""

from __future__ import annotations

import getpass
import hashlib
import os
from pathlib import Path
import secrets
import ssl
import sys

import certifi
from dotenv import dotenv_values, set_key
from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_context.init_dev import initialize
from agent_context.runtime import RuntimeSettings


class LocalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ACE_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    external_port: int = Field(default=18000, ge=1, le=65535)
    ui_port: int = Field(default=8501, ge=1, le=65535)
    ca_bundle: Path | None = None


def configure() -> tuple[str, str, int]:
    """Preserve credentials and volumes; fill only missing machine-local defaults."""
    path = Path(".env")
    fresh = not path.exists()
    if fresh:
        initialize(tenant_id="local-tenant", user_id="local-user")
    path.chmod(0o600)
    values = {**dotenv_values(path), **os.environ}
    settings = LocalSettings()
    if settings.external_port == settings.ui_port:
        raise ValueError("ACE_UI_PORT and ACE_EXTERNAL_PORT must be different")

    runtime = RuntimeSettings()
    for variable, kind in (
        ("ACE_DEMO_USER_TOKEN", "user"),
        ("ACE_DEMO_AGENT_TOKEN", "agent"),
    ):
        token = values.get(variable)
        principal = runtime.auth_bindings.get(
            hashlib.sha256(token.encode()).hexdigest() if token else ""
        )
        if principal is None or principal.actor_kind != kind:
            raise ValueError(
                "Existing .env has incomplete local authentication. Restore its "
                "matching tokens/bindings, or run agent-context-init in a fresh checkout."
            )

    if (
        fresh
        and "CG_NEO4J__PASSWORD" not in os.environ
        and values.get("CG_NEO4J__PASSWORD") in (None, "", "change-me")
    ):
        set_key(path, "CG_NEO4J__PASSWORD", secrets.token_hex(24))
    elif values.get("CG_NEO4J__PASSWORD") in (None, ""):
        raise ValueError("Configure CG_NEO4J__PASSWORD to match the existing database")

    if values.get("NVIDIA_API_KEY") in (None, "", "change-me", "local-dev"):
        if "NVIDIA_API_KEY" in os.environ:
            raise ValueError("NVIDIA_API_KEY is a placeholder in the environment; unset it or supply a working key")
        if not sys.stdin.isatty():
            raise ValueError("Set NVIDIA_API_KEY in the environment or .env, then rerun")
        key = getpass.getpass("NVIDIA API key (hidden): ").strip()
        if not key or key in {"change-me", "local-dev"}:
            raise ValueError("A working NVIDIA_API_KEY is required")
        set_key(path, "NVIDIA_API_KEY", key)

    if settings.ca_bundle is None:
        settings.ca_bundle = Path(
            ssl.get_default_verify_paths().cafile or certifi.where()
        ).resolve()
        set_key(path, "ACE_CA_BUNDLE", str(settings.ca_bundle))
    if not settings.ca_bundle.is_file():
        raise ValueError("ACE_CA_BUNDLE must name an existing CA certificate bundle")

    api_url = f"http://127.0.0.1:{settings.external_port}"
    set_key(path, "ACE_API_URL", api_url)
    return api_url, f"http://127.0.0.1:{settings.ui_port}", settings.ui_port


def main() -> None:
    try:
        api_url, ui_url, ui_port = configure()
    except ValidationError:
        # Do not print validation objects: they can contain credential inputs.
        raise SystemExit("Invalid local configuration; check ports and authentication settings in .env") from None
    except ValueError as error:
        raise SystemExit(str(error)) from None
    print(f"{api_url}\t{ui_url}\t{ui_port}")


if __name__ == "__main__":
    main()
