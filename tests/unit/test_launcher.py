"""Exercise launcher orchestration with fake executables, never host installers."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture
def launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copyfile(Path(__file__).resolve().parents[2] / "run.sh", tmp_path / "run.sh")
    tools = tmp_path / "tools"
    tools.mkdir()
    commands = {
        "docker": """#!/usr/bin/env bash
printf 'docker %s\\n' "$*" >> "$LAUNCH_COMMANDS"
if [[ "$*" == *'compose up'* && ${FAIL_COMPOSE:-0} == 1 ]]; then exit 1; fi
""",
        "uv": """#!/usr/bin/env bash
printf 'uv %s\\n' "$*" >> "$LAUNCH_COMMANDS"
if [[ "$*" == *'agent_context.local_setup'* ]]; then
  printf 'http://127.0.0.1:18000\\thttp://127.0.0.1:8501\\t8501\\n'
elif [[ "$*" == *'streamlit run'* ]]; then
  sleep 0.2
elif [[ "$*" == *'agent-context-demo'* && ${FAIL_DEMO:-0} == 1 ]]; then
  exit 1
fi
""",
        "curl": "#!/usr/bin/env bash\nexit 0\n",
        # Browser availability must never launch anything on the test host.
        "xdg-open": "#!/usr/bin/env bash\nexit 0\n",
    }
    for name, script in commands.items():
        executable = tools / name
        executable.write_text(script)
        executable.chmod(0o700)
    monkeypatch.setenv("PATH", str(tools) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("LAUNCH_COMMANDS", str(tmp_path / "commands.log"))
    return tmp_path


def run(launcher: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # Run from another directory to verify the launcher resolves its own root.
    return subprocess.run(
        ["bash", str(launcher / "run.sh"), *args],
        cwd=launcher.parent, text=True, capture_output=True, timeout=10, check=False,
    )


def test_startup_order_and_once_only_demo(launcher: Path) -> None:
    first = run(launcher, "--no-browser")
    assert first.returncode == 0, first.stderr
    assert "UI:      http://127.0.0.1:8501" in first.stdout
    commands = (launcher / "commands.log").read_text()
    assert commands.index("compose up") < commands.index("streamlit run")
    assert commands.index("streamlit run") < commands.index("agent-context-demo")
    assert (launcher / ".ace/demo-complete").is_file()
    assert run(launcher, "--no-browser").returncode == 0
    assert (launcher / "commands.log").read_text().count("agent-context-demo") == 1
    assert run(launcher, "--demo", "--no-browser").returncode == 0
    assert (launcher / "commands.log").read_text().count("agent-context-demo") == 2


def test_skip_demo(launcher: Path) -> None:
    assert run(launcher, "--skip-demo", "--no-browser").returncode == 0
    assert "agent-context-demo" not in (launcher / "commands.log").read_text()
    assert not (launcher / ".ace/demo-complete").exists()


def test_backend_failure_does_not_start_ui(
    launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAIL_COMPOSE", "1")
    result = run(launcher, "--no-browser")
    assert result.returncode != 0
    assert "Backend startup failed" in result.stderr
    assert "streamlit run" not in (launcher / "commands.log").read_text()


def test_failed_demo_is_reported_and_not_marked_complete(
    launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAIL_DEMO", "1")
    result = run(launcher, "--no-browser")
    assert "Demo FAILED" in result.stderr
    assert not (launcher / ".ace/demo-complete").exists()
    assert "streamlit run" in (launcher / "commands.log").read_text()


@pytest.mark.parametrize("option", ["--help", "--invalid"])
def test_help_and_invalid_arguments_never_install(
    launcher: Path, option: str
) -> None:
    result = run(launcher, option)
    assert result.returncode == (0 if option == "--help" else 1)
    assert not (launcher / "commands.log").exists()


def test_stop_preserves_volumes_and_does_not_require_python(launcher: Path) -> None:
    assert run(launcher, "--stop").returncode == 0
    commands = (launcher / "commands.log").read_text()
    assert "docker compose stop" in commands
    assert "uv " not in commands
    assert "down" not in commands


def test_sudo_fallback_preserves_supported_overrides_without_printing_secrets(
    launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = launcher / "tools"
    docker = tools / "docker"
    docker.write_text(
        docker.read_text().replace(
            "if [[ \"$*\" == *'compose up'*",
            'if [[ "$*" == info && ${PRIVILEGED:-0} != 1 ]]; then exit 1; fi\n'
            'if [[ "$*" == *\'compose up\'*',
        )
    )
    extras = {
        "id": "#!/usr/bin/env bash\nprintf '1000\\n'\n",
        "systemctl": "#!/usr/bin/env bash\nexit 0\n",
        "sudo": """#!/usr/bin/env bash
printf 'sudo %s\\n' "$*" >> "$LAUNCH_COMMANDS"
if [[ ${1:-} == --preserve-env=* ]]; then shift; fi
PRIVILEGED=1 "$@"
""",
    }
    for name, body in extras.items():
        path = tools / name
        path.write_text(body)
        path.chmod(0o700)
    monkeypatch.setenv("NVIDIA_API_KEY", "synthetic-launch-key")
    result = run(launcher, "--skip-demo", "--no-browser")
    assert result.returncode == 0, result.stderr
    commands = (launcher / "commands.log").read_text()
    assert "--preserve-env=NVIDIA_API_KEY," in commands
    assert "synthetic-launch-key" not in commands + result.stdout + result.stderr


def test_missing_docker_and_uv_use_installers_without_host_changes(
    launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = launcher / "tools"
    # A hermetic PATH makes command discovery independent of the test machine.
    for name in ("bash", "sh", "dirname", "uname", "mktemp", "rm", "cp", "chmod", "mkdir", "sleep", "cat", "touch", "id"):
        target = shutil.which(name)
        assert target
        (tools / name).symlink_to(target)
    (tools / "id").unlink()
    (tools / "id").write_text("#!/usr/bin/env bash\nprintf '0\\n'\n")
    (tools / "id").chmod(0o700)
    for name in ("docker", "uv"):
        (tools / name).rename(launcher / (name + ".template"))
    (tools / "curl").write_text("""#!/usr/bin/env bash
url= output=
while [[ $# -gt 0 ]]; do
  case "$1" in
    https://*) url=$1 ;;
    -o) shift; output=$1 ;;
  esac
  shift
done
if [[ -z $output ]]; then exit 0; fi
if [[ $url == https://get.docker.com ]]; then
  printf '#!/bin/sh\\ncp "$INSTALL_ROOT/docker.template" "$INSTALL_BIN/docker"\\n' > "$output"
else
  printf '#!/bin/sh\\nmkdir -p "$HOME/.local/bin"\\ncp "$INSTALL_ROOT/uv.template" "$HOME/.local/bin/uv"\\n' > "$output"
fi
""")
    monkeypatch.setenv("PATH", str(tools))
    monkeypatch.setenv("HOME", str(launcher / "home"))
    monkeypatch.setenv("INSTALL_ROOT", str(launcher))
    monkeypatch.setenv("INSTALL_BIN", str(tools))
    result = run(launcher, "--skip-demo", "--no-browser")
    assert result.returncode == 0, result.stderr
    assert (tools / "docker").is_file()
    assert (launcher / "home/.local/bin/uv").is_file()
    assert "streamlit run" in (launcher / "commands.log").read_text()
