#!/usr/bin/env bash
# Install pinned optional development guidance; never execute upstream scripts.
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
  if [[ ! -d "$staging/$revision/.git" ]]; then
    git init -q "$staging/$revision"
    git -C "$staging/$revision" fetch -q --depth 1 "$url" "$revision"
    git -C "$staging/$revision" checkout -q --detach FETCH_HEAD
  fi
  mkdir -p "$skill_root" "$staging/install-$name"
  cp "$staging/$revision/$source/SKILL.md" "$staging/install-$name/SKILL.md"
  if [[ -d "$staging/$revision/$source/references" ]]; then
    cp -R "$staging/$revision/$source/references" "$staging/install-$name/references"
  fi
  printf '%s\n%s\n' "$url" "$revision" > "$staging/install-$name/UPSTREAM"
  mv "$staging/install-$name" "$skill_root/$name"
  printf 'Installed: %s\n' "$name"
}
case "${1:-design}" in
  design)
    install_skill https://github.com/dickwu/apple-design-skill.git ff4ebddf0488598723a82bfdce1afb04de0b1c44 . apple-hig-design
    install_skill https://github.com/emilkowalski/skills.git c8a79627b59d72d764d6ab6f2c87c09a48169833 skills/apple-design apple-motion-design
    ;;
  engineering)
    install_skill https://github.com/DietrichGebert/ponytail.git 96608e078b2d5ea607c5c3b8b5a54d1c1fba6846 skills/ponytail ponytail
    install_skill https://github.com/DietrichGebert/ponytail.git 96608e078b2d5ea607c5c3b8b5a54d1c1fba6846 skills/ponytail-review ponytail-review
    install_skill https://github.com/DietrichGebert/ponytail.git 96608e078b2d5ea607c5c3b8b5a54d1c1fba6846 skills/ponytail-audit ponytail-audit
    install_skill https://github.com/affaan-m/everything-claude-code.git b38be6a7f6350964d59328b52f0624e1d1d552d1 skills/change-impact ecc-change-impact
    install_skill https://github.com/affaan-m/everything-claude-code.git b38be6a7f6350964d59328b52f0624e1d1d552d1 skills/verification-loop ecc-verification-loop
    install_skill https://github.com/affaan-m/everything-claude-code.git b38be6a7f6350964d59328b52f0624e1d1d552d1 skills/ai-regression-testing ecc-ai-regression-testing
    install_skill https://github.com/affaan-m/everything-claude-code.git b38be6a7f6350964d59328b52f0624e1d1d552d1 skills/benchmark-optimization-loop ecc-benchmark-optimization-loop
    ;;
  *) printf 'Usage: %s [design|engineering]\n' "$0" >&2; exit 2 ;;
esac
