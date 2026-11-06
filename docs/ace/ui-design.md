# Conversational workspace design

The UI remains Streamlit; routing, persistence, extraction and providers are unchanged.
The screen's job is to keep the conversation readable while making its remembered
project state inspectable. Its distinguishing element is the separate context
inspector: goal, progress, next step, memory and source evidence retain their meaning.

## Installed guidance

Run `./scripts/install-design-skills.sh` to install the requested upstream guidance
under `.agents/skills/`. The installer pins both Git commits, does not run upstream
scripts, preserves existing installs and keeps third-party reference content local.
Remove the respective directory to reinstall the pinned version.

- [dickwu/apple-design-skill](https://github.com/dickwu/apple-design-skill): layout,
  typography, semantic color, sidebars, split views, buttons and accessibility.
- [emilkowalski/skills — apple-design](https://github.com/emilkowalski/skills/tree/main/skills/apple-design):
  immediate press feedback, restrained motion, system typography and accessibility preferences.

Apple's principles are translated to web controls; this is not a native Apple UI.
Skill guidance is used during development, not loaded into application/model prompts.

## Applied design decisions

The previous serif branding and green/cream palette are replaced with a system-font
workspace and a restrained blue accent. The active conversation has an inset marker
and tinted selection, rather than looking like another primary action. The context
inspector and conversation have separate white surfaces. Existing disclosure controls,
labels, evidence, retry and navigation behavior are preserved.

Tokens: canvas `#f6f7fa`, surface `#ffffff`, content `#20242c`, muted `#596371`,
accent `#245bc0`, separator `#d8dee7`. Calculated content/canvas contrast is 14.52:1,
muted/canvas 5.69:1 and accent/canvas 5.88:1. Caption opacity is reset to 1 because
Streamlit's inherited 0.6 opacity would otherwise reduce effective contrast.
Body text is 1rem, captions .82rem, headings scale with available width. Default
buttons have a 2.75rem minimum height. Visible focus applies to buttons, links,
inputs, textareas and disclosure summaries.

Regular layout: `navigation | conversation + composer | project context`.
Compact layout: `collapsible navigation; conversation + composer; project context`.
The existing Context toggle retains a distraction-free conversation view.
No artificial loading delay, animated transcript entrance, gesture system or motion
library is added. Button press feedback uses a small transform; reduced motion
disables it. Increased contrast strengthens separators; reduced transparency uses
solid surfaces; forced-colors mode preserves focus and selected navigation borders.

References read: HIG `accessibility.md` (Vision/Mobility), `layout.md` (Visual hierarchy),
`typography.md`, `color.md`, `designing-for-macos.md`, `sidebars.md`, `split-views.md`,
`buttons.md` (Best practices), `motion.md` (Best practices), plus cross-platform mapping.
Emil's guidance: sections 1, 11, 14 and 15. No native menu-bar or spring gestures are
imitated in this web app. Light appearance is the supported configured theme;
this change does not claim a verified dark appearance or full accessibility certification.

## Verification

- 28 focused workspace UI checks pass, with providers and API replaced.
- Changed presentation module: strict Pyright, zero errors/warnings.
- Actual Chromium rendering at 1440px and 390px: no horizontal viewport overflow;
  narrow context inspector uses the full available 358px and stacks below chat.
- Emulated reduced motion: button transition duration 0s; increased contrast:
  separator token resolves to `#596371`.
- Pinned installer executed successfully; shell syntax checked.
- No model calls, backend edits or full test suite for this UI increment.

The browser checks use a synthetic workspace. Screen-reader coverage and a complete
browser/device matrix remain unverified; no backend or benchmark completion is implied.
