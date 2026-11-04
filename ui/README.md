# Research console

Run `./run.sh` from the repository root. The redesigned console is
`context_engine.py`; the legacy diagnostic pages are separate.

The console keeps the existing SDK, research-host, search and handoff calls.
`context_engine_view.py` contains presentation components and browser-session
conversation snapshots. `context_engine.css` contains the page's responsive
styles; `.streamlit/config.toml` supplies the light navy/neutral theme.

The main view contains the conversation and a fixed message composer. Project
notes, saved progress and source selection live in the sidebar. Answer details
show cited sources, memory evidence and recorded activity. Technical selection
traces remain available in an additional expander.

Conversation history is local to the current browser session; this UI does not
add a backend session browser. New session clears that view and source selections
while retaining explicitly saved progress. User/model/source text remains plain
text; custom HTML is restricted to static, repository-owned layout and styles.

Design references:

- [NN/g: Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
  — make the primary task visible and reveal advanced controls on request.
- [W3C: Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
  — readable text contrast, including secondary text; visible keyboard focus.

Validate the UI without live model calls:

```sh
uv run --frozen pytest tests/ui/test_ace_console.py
uv run --frozen pyright
```
