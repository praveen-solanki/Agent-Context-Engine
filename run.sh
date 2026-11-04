#!/usr/bin/env bash
# Local development launcher. Never source .env as shell code.
set -Eeuo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

demo=auto
browser=true
action=start
ui_pid=
docker_cmd=(docker)

usage() {
  cat <<'HELP'
Usage: ./run.sh [--demo | --skip-demo] [--no-browser]
       ./run.sh --stop | --logs | --help

Installs uv/Python and Docker when missing, configures private local credentials,
starts MongoDB/Neo4j/API/worker, opens the UI, and runs the real-model demo once.
Ubuntu/Debian/WSL2 and macOS are supported. Installation may ask for sudo access.
The first run asks for an NVIDIA key unless already configured. Brave is optional.

  --demo        Run the three-session pipeline demo again (uses model quota).
  --skip-demo   Start the services/UI without running the startup demo.
  --no-browser  Print URLs without opening a browser.
  --stop        Stop backend services, retaining database volumes.
  --logs        Follow backend service logs.

Keep this terminal open for the UI. Ctrl+C stops this UI; backend services remain
running until ./run.sh --stop. Private launcher logs/state live in ignored .ace/.
ACE_UI_PORT and ACE_EXTERNAL_PORT override the default ports 8501 and 18000.
HELP
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
as_root() {
  if [[ $(id -u) == 0 ]]; then "$@"; else sudo "$@"; fi
}

for arg in "$@"; do
  case "$arg" in
    --help|-h) usage; exit 0 ;;
    --demo) demo=always ;;
    --skip-demo) demo=never ;;
    --no-browser) browser=false ;;
    --stop) action=stop ;;
    --logs) action=logs ;;
    *) usage >&2; die "Unknown argument: $arg" ;;
  esac
done

platform=$(uname -s)
case "$platform" in
  Linux|Darwin) ;;
  *) die 'Use Ubuntu/Debian, macOS, or Ubuntu inside Windows WSL2.' ;;
esac

ensure_curl() {
  if command -v curl >/dev/null; then return; fi
  if [[ $platform == Linux ]] && command -v apt-get >/dev/null; then
    as_root apt-get update
    as_root apt-get install -y curl ca-certificates
  else
    die 'Install curl with your operating system package manager and rerun.'
  fi
}

ensure_docker() {
  if ! command -v docker >/dev/null; then
    ensure_curl
    if [[ $platform == Darwin ]]; then
      if ! command -v brew >/dev/null; then
        printf 'Installing Homebrew with its official installer; follow its system prompts.\n'
        installer=$(mktemp)
        curl --fail --silent --show-error --location https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh -o "$installer"
        /bin/bash "$installer"
        rm -f "$installer"
        export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
      fi
      brew install --cask docker
    else
      [[ -f /etc/os-release ]] || die 'Cannot identify this Linux distribution.'
      # This is an operating-system file, never application/user configuration.
      . /etc/os-release
      case "$ID" in
        ubuntu|debian) ;;
        *) die 'Automatic Docker installation supports Ubuntu/Debian. Install Docker Engine and Compose v2 for your distribution, then rerun.' ;;
      esac
      printf 'Installing Docker with its official installer; sudo may ask for your password.\n'
      installer=$(mktemp)
      curl --fail --silent --show-error --location https://get.docker.com -o "$installer"
      as_root sh "$installer"
      rm -f "$installer"
    fi
  fi
  if ! docker info >/dev/null 2>&1; then
    if [[ $platform == Darwin ]]; then
      open -a Docker
      printf 'Waiting for Docker Desktop; complete any first-launch prompts.\n'
      for ((attempt=0; attempt<120; attempt++)); do
        if docker info >/dev/null 2>&1; then break; fi
        sleep 2
      done
    elif command -v systemctl >/dev/null && [[ -d /run/systemd/system ]]; then
      as_root systemctl start docker
    fi
  fi
  if ! docker info >/dev/null 2>&1; then
    if [[ $platform == Linux ]] && as_root docker info >/dev/null 2>&1; then
      if [[ $(id -u) != 0 ]]; then
        # Preserve only Compose's supported overrides, never expose their values
        # as command arguments or require membership in the docker group.
        docker_cmd=(sudo --preserve-env=NVIDIA_API_KEY,CG_NEO4J__PASSWORD,ACE_TENANT_ID,ACE_USER_ID,ACE_AUTH_BINDINGS,ACE_EXTERNAL_PORT,ACE_CA_BUNDLE,LLM_BASE_URL,LLM_MODEL,EMBEDDING_BASE_URL,EMBEDDING_MODEL,EMBEDDING_BATCH_SIZE,COMPOSE_PROJECT_NAME,DOCKER_CONFIG docker)
      fi
    else
      die 'Docker is unavailable. Start Docker Desktop/Engine (enable systemd for a WSL Engine install), then rerun.'
    fi
  fi
  if ! "${docker_cmd[@]}" compose version >/dev/null 2>&1; then
    if [[ $platform == Linux ]] && command -v apt-get >/dev/null; then
      as_root apt-get update
      if apt-cache show docker-compose-plugin >/dev/null 2>&1; then
        as_root apt-get install -y docker-compose-plugin
      elif apt-cache show docker-compose-v2 >/dev/null 2>&1; then
        as_root apt-get install -y docker-compose-v2
      fi
    fi
    "${docker_cmd[@]}" compose version >/dev/null 2>&1 || die 'Install Docker Compose v2 for your operating system, then rerun.'
  fi
}

ensure_docker
if [[ $action == stop ]]; then
  "${docker_cmd[@]}" compose stop
  exit 0
elif [[ $action == logs ]]; then
  exec "${docker_cmd[@]}" compose logs --follow --tail=100
fi

if ! command -v uv >/dev/null; then
  ensure_curl
  installer=$(mktemp)
  curl --fail --silent --show-error --location https://astral.sh/uv/0.13.4/install.sh -o "$installer"
  sh "$installer"
  rm -f "$installer"
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null || die 'uv installation did not produce an executable on PATH.'
printf 'Installing Python 3.12 and locked project dependencies…\n'
uv sync --frozen --python 3.12 --system-certs

configuration=$(uv run --frozen python -m agent_context.local_setup)
IFS=$'\t' read -r api_url ui_url ui_port <<< "$configuration"
[[ -n $api_url && -n $ui_url && -n $ui_port ]] || die 'Local configuration was not produced.'
export ACE_API_URL="$api_url"
mkdir -p .ace

# Fail before starting services if this launcher cannot bind its UI port.
uv run --frozen python - "$ui_port" <<'PY'
import socket
import sys

with socket.socket() as listener:
    try:
        listener.bind(("127.0.0.1", int(sys.argv[1])))
    except OSError:
        raise SystemExit("UI port is in use. Stop the existing UI or set ACE_UI_PORT=8502.")
PY

printf 'Building and starting MongoDB, Neo4j, API and pipeline worker…\n'
if ! "${docker_cmd[@]}" compose up --build -d --wait --wait-timeout 240; then
  die 'Backend startup failed. Inspect ./run.sh --logs; existing database volumes were retained.'
fi

cleanup() {
  if [[ -n $ui_pid ]]; then
    kill "$ui_pid" 2>/dev/null || true
    wait "$ui_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

uv run --frozen python -m streamlit run ui/context_engine.py \
  --server.address=127.0.0.1 --server.port="$ui_port" \
  --server.headless=true --browser.gatherUsageStats=false >.ace/ui.log 2>&1 &
ui_pid=$!

ready=false
ensure_curl
for ((attempt=0; attempt<60; attempt++)); do
  if ! kill -0 "$ui_pid" 2>/dev/null; then break; fi
  if curl --noproxy 127.0.0.1 --fail --silent --max-time 2 "$ui_url/_stcore/health" >/dev/null; then
    ready=true
    break
  fi
  sleep 1
done
[[ $ready == true ]] || die 'UI did not become ready. Inspect .ace/ui.log.'
printf '\nUI:      %s\nBackend: %s\nAPI docs: %s/docs\n' "$ui_url" "$api_url" "$api_url"

if [[ $browser == true ]]; then
  if [[ $platform == Darwin ]]; then
    open "$ui_url" >/dev/null 2>&1 || true
  elif command -v wslview >/dev/null; then
    wslview "$ui_url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null; then
    xdg-open "$ui_url" >/dev/null 2>&1 || true
  fi
fi

if [[ $demo == always || ( $demo == auto && ! -f .ace/demo-complete ) ]]; then
  printf '\nRunning the real-model three-session pipeline demo (uses NVIDIA quota)…\n'
  if uv run --frozen agent-context-demo >.ace/demo.log 2>&1; then
    touch .ace/demo-complete
    printf 'Demo passed. Report and session IDs: .ace/demo.log and data/ace_demo/.\n'
  else
    rm -f .ace/demo-complete
    printf 'Demo FAILED. The UI is available; inspect .ace/demo.log and ./run.sh --logs. Retry with ./run.sh --demo.\n' >&2
  fi
fi
printf '\nKeep this terminal open for the UI. Ctrl+C stops the UI.\nStop the backend later with ./run.sh --stop.\n'
wait "$ui_pid"
