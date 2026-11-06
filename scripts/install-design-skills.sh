#!/usr/bin/env bash
# Preserve the original design-skill installation command.
set -euo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/install-skills.sh" design "$@"
