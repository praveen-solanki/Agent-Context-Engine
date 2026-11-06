#!/usr/bin/env bash
# Install the requested design guidance locally; do not execute upstream scripts.
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
skill_root="$repo_root/.agents/skills"
staging="$(mktemp -d)"
trap 'rm -rf -- "$staging"' EXIT
install_skill() {
  local url="$1" revision="$2" source="$3" name="$4"
  if [[ -e "$skill_root/$name" ]]; then
    printf 'Already installed: %s (remove this directory to reinstall)\n' "$name"
    return
  fi
  git init -q "$staging/$name"
  git -C "$staging/$name" fetch -q --depth 1 "$url" "$revision"
  git -C "$staging/$name" checkout -q --detach FETCH_HEAD
  mkdir -p "$skill_root/$name"
  cp "$staging/$name/$source/SKILL.md" "$skill_root/$name/SKILL.md"
  if [[ -d "$staging/$name/$source/references" ]]; then
    cp -R "$staging/$name/$source/references" "$skill_root/$name/references"
  fi
  printf '%s\n%s\n' "$url" "$revision" > "$skill_root/$name/UPSTREAM"
  printf 'Installed: %s\n' "$name"
}
install_skill https://github.com/dickwu/apple-design-skill.git ff4ebddf0488598723a82bfdce1afb04de0b1c44 . apple-hig-design
install_skill https://github.com/emilkowalski/skills.git c8a79627b59d72d764d6ab6f2c87c09a48169833 skills/apple-design apple-motion-design
