"""Local setup creates private credentials and preserves existing files."""

import hashlib
import json
from pathlib import Path

import pytest
from dotenv import dotenv_values

from agent_context.init_dev import initialize


def test_initializer_creates_private_credentials_and_refuses_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    Path(".env.example").write_text("NVIDIA_API_KEY=change-me\n")
    path = initialize(tenant_id="t1", user_id="u1")
    values = dotenv_values(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert values["NVIDIA_API_KEY"] == "change-me"
    user_token = values["ACE_DEMO_USER_TOKEN"]
    assert user_token
    host_token = values["ACE_DEMO_AGENT_TOKEN"]
    assert host_token and user_token != host_token
    bindings = json.loads(values["ACE_AUTH_BINDINGS"] or "{}")
    assert bindings[hashlib.sha256(user_token.encode()).hexdigest()]["user_id"] == "u1"
    snapshot = path.read_bytes()
    with pytest.raises(FileExistsError):
        initialize(tenant_id="t2", user_id="u2")
    assert path.read_bytes() == snapshot
