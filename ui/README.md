# Conversational workspace

Start or update the matching API, worker and UI from the repository root:

```sh
./run.sh --skip-demo
```

The page is `context_engine.py`. The existing launcher, ingestion, retrieval,
research host and governance services are reused. This update adds no separate
demo app, database or agent framework.

- **Left:** authorized projects and saved conversations. New conversation starts
  a clean chat. Automatic mode resolves its project from the message; Selected
  project pins an explicit choice. Rename conversation changes only its title.
- **Centre:** normal conversation. Describe objectives, requirements, plans,
  progress or corrections; there is no Save progress step. Reopening a saved
  conversation restores recorded messages without calling the answer model.
- **Right, optional:** current goal, requirements, progress, blockers, next planned
  step, dependencies and memory. The Context toggle collapses this panel.
  Sources and activity under an answer exposes its evidence and recorded work.

Project/task changes use source-validated user quotes and the existing versioned
TaskStateService. User reports are labelled separately from authenticated tool
outcomes. Suggested steps are proposals until explicitly accepted in conversation
(or with Add to plan). Ambiguous changes prompt a question. No percentage or
external completion is invented. The next planned step is the first remaining
accepted step; prerequisites can still be unresolved.

An unchanged approved goal echoed by the planner is treated as a no-op. Actual
new claims still require exact quotes; invalid proposals receive bounded repair.
Planner prose is not an answer or source: clarification/rejection passes only a
fixed status to the same context/citation host as ordinary replies. An active goal
with no accepted step remains active. After upgrading, restate a constraint that
was previously rejected; the app does not rewrite old answers or silently migrate
unapplied historical plan changes.

Memory entries provide View evidence, Apply correction and Remove from memory.
Corrections retain an exact target/fingerprint in the durable request, revoke the
old entry using existing governance, and ingest the replacement normally. Original
conversation text remains available. Removal does not delete source history.

Conversation history comes from existing server event streams, with a project and
session URL for restoring it after browser refresh. An interrupted recorded request
can be retried with its original ID; existing document-read receipts are recovered. A request overtaken by another
conversation's plan change must be restated, preventing an old retry from reverting
the newer plan.
Historical answers are labelled as recorded; their original selected context
bundles were not persisted. Current memory is displayed separately. New answers
record the task revision they used, and concurrent task changes produce a warning.

Source selection is under Sources in the sidebar. Project memory is the default;
Sample brief and optional Brave Web search remain available. Documents here are
registered text/search snapshots; this update does not add a PDF uploader or a
coding/browser executor.

`workspace.py` contains service I/O and history reconstruction;
`context_engine_view.py` contains presentation; `context_engine.css` contains the
warm neutral/teal styles. User/model/source content renders as plain text. Custom
HTML is limited to static repository-owned styles/layout.

Projects now support automatic matching and private owned creation. The default
**Automatic** mode resolves an existing project by name/alias/description or
creates one for clear active new work. Unclear/multi-project messages wait for
selection or rephrasing before recording; general unbound chat uses **Personal**.
Selecting a project in the sidebar enables **Selected project** until Automatic
is chosen again. Owned projects have a **Project name and aliases** form; rename
keeps their ID/context. Current-request sources and routing decisions are frozen
through retries. A switch opens a new bound stream rather than changing history.

`ACE_AUTH_BINDINGS` remains the trusted identity/permission registry. The server
creates owned memberships and validates the configured same-owner host delegate;
model-generated IDs never grant access. The built-in initializer's research-project
still works. Update API, worker and UI together. Read the
[edge-case/operation guide](../docs/ace/project-routing.md) for configuration,
limits, legacy preference handling, unsent-draft behavior and explicit correction
of a wrong association. Unsent routing drafts remain in browser state until
recorded; do not refresh/close an unsent draft you need to keep.
There is one workspace plan (`project-work`) per user/project. Existing API/SDK
multi-task functionality is preserved. Session event, task revision, entry and
context-budget limits are unchanged; starting a new conversation does not reset a
project task's revision quota. Existing explicit handoffs remain in the API/SDK;
they are no longer a manual-save requirement in this page.

Focused validation, without live provider calls:

```sh
uv run --frozen pytest -q tests/unit/test_workspace_continuity.py tests/ui/test_ace_console.py
CG_INTEGRATION=1 uv run --frozen pytest -q tests/integration/test_ace_workspace.py
uv run --frozen pyright src/agent_context/continuity.py ui/context_engine.py ui/context_engine_view.py ui/workspace.py
```

The integration file uses disposable `ace_test_*` databases on local MongoDB
(`127.0.0.1:27017`), mocked answer/planning providers and explicit worker watermark
advancement. It tests the new API/SDK interaction, not live extraction/model
quality or a complete pipeline. Benchmark/usefulness measurements and production
readiness are explicitly outside this change.

Design references retained from the existing UI:

- [NN/g: Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/)
- [W3C: Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

When automatic routing is uncertain about a new undertaking, copy its exact name
from your message into **Create and use project**. This confirms creation before
the unsent message is recorded. Multi-project updates require rephrasing instead.
