# Running the new service

This is an incremental implementation, not a completed or production-ready
blueprint. The original Context Graph CLI and Streamlit demo remain available.

## Local prerequisites

Use Python 3.12+ and `uv sync --frozen --system-certs` from the repository root.
In the managed cloud workspace use `UV_CACHE_DIR=/workspace/.cache/uv` because
the home-directory cache is read-only. Use the existing checkout; do not create
a worktree unless requested. Keep each trust partition's databases isolated.

Start Neo4j 5.26 and MongoDB 7 using your disposable development services. The
existing `docker-compose.neo4j-convomem.yml` can start the original Neo4j demo;
the new API/worker do not require modifying that compose file. Configure:

```
CG_NEO4J__URI=bolt://127.0.0.1:7689
CG_NEO4J__USER=neo4j
CG_NEO4J__PASSWORD=<your-local-development-password>
CG_NEO4J__DATABASE=neo4j
CG_MONGO__URI=mongodb://127.0.0.1:27017
CG_MONGO__DATABASE=agent_context_development
ACE_TENANT_ID=local-tenant
ACE_USER_ID=local-user
ACE_PORT=8000
ACE_RUN_VERSION=v1
```

Store local configuration in the ignored `.env`, preserve existing settings and
keep real credentials in environment settings/your secret manager. Mongo's
production URI must use acknowledged durable writes and production connections
need TLS. Local development examples are not secure production configurations.

## Authentication

There are no default credentials and no trusted identity fields in event JSON.
Generate separate high-entropy bearer tokens for the human caller and agent host
using your secret manager (at least 32 characters). Configure `ACE_AUTH_BINDINGS`
as a JSON object mapping each token's lowercase SHA-256 digest to its trusted
principal. Never put the raw token in this JSON, source code, logs or Git.

Principal shape (replace identifiers and grants):

```json
{
  "tenant_id": "local-tenant",
  "user_id": "local-user",
  "actor_id": "local-user",
  "actor_kind": "user",
  "permissions": ["view", "assert", "correct"],
  "projects": ["research-project"]
}
```

The agent-host token uses `actor_kind=agent` and its real agent ID as `actor_id`;
that ID must match submitted `agent_id`. Give it only `view` and `assert`.
Only a separately granted administrator may replay dead letters. The tokens
belong to the host integration, not to model prompts or agent-generated content.
Permission and project grants are server configuration, never inferred from chat.

The deployable factory currently enforces a single tenant/user trust partition.
Use a separate Neo4j/Mongo database deployment for each partition. Concept
resolution in the preserved pipeline has global queries; sharing a database
across partitions is not yet supported. Shared-team/directory retrieval is
fail-closed, not silently inferred from membership claims.

## Processes and consistency

Start `uv run --frozen agent-context-api`. Storage readiness checks Mongo ping and
a real Neo4j query; `/health/live` is process liveness. The API does not prove the
model or worker is ready. OpenAPI is at `/openapi.json`.

Configure the existing NVIDIA/OpenAI-compatible model settings securely before
starting `uv run --frozen agent-context-worker`. `NVIDIA_API_KEY` (or supported
`LLM_API_KEY` override), model host, model name and embedding dimension remain
provider-configurable in the existing settings. The worker refuses known empty
or example credentials. It uses a stable run ID derived from the deployment and
`ACE_RUN_VERSION`; do not change that version to bypass a failed event.

Live processes do not survive a published environment snapshot: restart both
processes and databases as required. The API and worker own and close their
connections. Cancel/restart a worker safely: expired claims are replayable;
partial graph commits reconcile through original idempotent writes/checkpoints.

`POST /v1/events` returns 202 and a **recorded** status. It is not proof that
context exists. Poll `GET /v1/events/{event_id}/status` or request
`minimum_sequence` in `POST /v1/context/assemble`. That option waits for the
session's availability watermark with a bounded timeout and returns 503 if it
cannot be satisfied. Event sequences start at 1 and must be contiguous; event
times must not go backwards. Reuse the original event ID when retrying.

The Python `AgentContextClient` supports event recording, context assembly,
progressive context search, evidence inspection, handoff preparation and handoff resume. It has timeouts and bounded retries for
transient failures. Close it using `await client.aclose()`.

Context bundles use a conservative UTF-8 byte token bound unless a host injects
its model tokenizer. Reserve host/system, tools, request, output and safety
tokens explicitly. Count is checked after rendering; atomic items are never
truncated. Keep `retrieved_data` in a data/tool channel, never elevate it into
system instructions. Optional source failures are explicit; mandatory source
or mandatory-budget failures fail closed.

### Search, effective history and semantic retrieval

`POST /v1/context/search` accepts `SearchRequest`: agent/session/project IDs,
query, optional minimum sequence, limit (1–100), cursor and optional `as_of`.
It returns candidate items and evidence handles, not a packed prompt or token
budget. Use `AgentContextClient.search_context()` and then `.evidence(item_id)`.
Search and assembly share authorization, lifecycle, ranking and conflict checks.
Pages cover a bounded candidate window (256 per source by default); `window_full`
signals possible truncation. Narrow the query when necessary. Every page reruns
retrieval and privacy checks; a changed query, grants or result snapshot rejects
the cursor with 422, requiring a fresh search. A cursor never grants access.

`as_of` requests effective/event-time history. Superseded values are returned only
before their supersession, within their validity window and after observation.
This is not a bitemporal reconstruction of what the database knew then. Revoked
or privacy-blocked items remain excluded even for historical searches. Historical
results are labeled and are never inserted by the current-only assemble route.
Evidence inspection intentionally permits a user to inspect their own withdrawn
source; `usable_as_current_context=false` distinguishes it from active context.
Excerpts include exact message offsets, role, speaker and per-span trust, capped
at eight episodes, 4000 characters and 32 spans per episode. Legacy sources
without spans retain their existing text and do not acquire invented offsets.

The runtime now uses the existing embedding provider and stored Context vectors
to rank authorized candidates before LIMIT. NIM requests use `input_type=query`;
ingestion continues to use `passage`. Neo4j's cosine result is normalized so
orthogonal vectors do not gain relevance. Model/dimension mismatches are excluded
from semantic scoring; lexical matching remains available. This uses native
cosine over candidates restricted by the owner/scope query, avoiding global ANN
top-k followed by authorization filtering. An inspected plan used the status
index followed by owner filtering; an indexed owner partition is not claimed.
It does not establish large-partition load
performance. No new vector service or graph planner is introduced.

Configure the API's `EMBEDDING_API_KEY`, base URL/model and `EMBEDDING_DIMENSION`
to match the worker. Local Compose uses the NVIDIA key as an embedding-key
fallback. `ACE_SEMANTIC_RETRIEVAL=false` selects an explicit lexical-only mode;
`ACE_SOURCE_TIMEOUT_SECONDS` bounds source latency (default 30 seconds). With
semantic retrieval enabled, an embedding failure fails the required source with
503 instead of silently claiming semantic recall. The API owns/closes its
embedding connection pool. Storage readiness does not probe the model provider.

Handoff completion requires an authenticated successful tool result with matching
call/event/project/session references; a model saying “done” is insufficient.
Resume checks permissions, expected revision, expiration, outstanding operations
and evidence again. It never executes tools. The private artifact registry computes hashes from uploaded content and verifies
current versions for handoff resume. Arbitrary external URLs are never fetched;
remote repositories require a separately configured authoritative verifier.

## Current tasks and continuation

`POST /v1/tasks/state` / `AgentContextClient.update_task(TaskUpdate(...))`
updates a typed current `WorkState`. `GET /v1/tasks/{task_id}?project_id=...` /
`.current_task(project_id, task_id)` inspects the latest version. Both are private
to the authenticated user and require the current project grant. A task ID alone
does not grant access. Every update cites an actual authenticated event from the
same project/session and uses `expected_version` plus an idempotency key.

The update payload is an explicit authenticated state assertion; its
`source_event_id` is a causation/lineage reference, not a claim that every field
was semantically extracted from that text. Evidence inspection returns the
stored `state_assertion` separately from the original causation event. Successful
actions additionally require real matching host tool outcomes, and artifact
references require the current server-computed content hash. Model prose is not
proof that work completed.

A user creates/approves goals, requirements, selected `must_keep` constraints,
cancellations, dependencies, expiry and status. Changing these fields requires
`correct`; an agent cannot approve them or create a new task. An authenticated
agent can report progress from its own tool-result event. Previously verified
completed actions cannot be removed or rewritten. `must_keep` must be a subset
of current requirements; cancelled steps cannot remain pending. The latest state
replaces obsolete pending/requirement lists rather than merging old instructions.

Pass `task_id` and `project_id` to `AssembleRequest` to request current task
context. Optional `task_version` is a precondition (409 on change). Runtime
registers this as a required source: missing task returns 404; unavailable source
event or expired task fails explicitly. It never silently omits requested task
state. The complete state section is atomic and mandatory within the allocated
render budget; insufficient space returns `mandatory_context_exceeds_budget`.
It remains data labeled `current_task_state`, never host policy. Ordinary memory
preferences remain optional relevance candidates. Bundles now expose typed
`selections`, authorization `scope`, and the observed `consistency_sequence`
when a minimum event watermark was requested. The byte bound covers `rendered`,
not diagnostic metadata a host chooses to serialize separately.

Current tasks reuse the handoff store's atomic CAS and bounded immutable revision
list. A server-owned reserved ID gives each user/project/task exactly one current
head, so separate handoff IDs cannot fork that head. There is no new database,
event pipeline or workflow executor. Existing export/quarantine/primary erasure
includes these records through the same collection. Quotas remain explicit:
64KB per snapshot, 64 revisions per task, 32 entries/action references per list,
4000 UTF-8 bytes per work entry. This is a bounded workflow contract, not an
unbounded project history system. Historical memory search does not invent old
operational task state; it reports `historical_task_state_not_included` when a
task is requested with `as_of`.

For a bound task, prepare a handoff with matching current content and
`task_state_version`. Resume returns the immutable historical `handoff`, the
current task reference, and one freshly assembled bundle. Mismatched task
versions/requirements, cancelled/completed task status, unresolved operations,
changed artifacts, expired handoffs and unavailable evidence prevent safe
continuation. Reconcile the state and prepare a matching snapshot, then consume
`resume.bundle.rendered` only after `safe_to_continue` is true. The bundled host
uses that bundle and does not inject a competing old handoff when current task
state exists. A host must also honor bundle warnings and verify current versions
before external actions. Stable action IDs and recorded receipts allow recovery;
unknown external outcomes require reconciliation. ACE does not provide atomic
exactly-once transactions with arbitrary external tools.

Legacy handoffs without canonical task state retain their previous snapshot-only
semantics. Their idempotency hashes remain compatible. No legacy record is
silently promoted to an approved task; old mis-scoped graph data is not migrated.
The SDK and API should be upgraded together for the additive response fields.
The existing console stays intact; generic tasks use these HTTP/SDK operations,
not new task-management UI controls. Shared directory/graph-TASK retrieval is
still fail-closed; the new private operational TASK section is separately bound
to its authenticated project.

For opt-in end-to-end validation, select a disposable API explicitly with
`ACE_LIVE_CONTINUATION_URL`, configure existing demo user/host tokens securely,
and select an actually accessible `ACE_ALTERNATE_MODEL`. Run:

```sh
CG_INTEGRATION=1 uv run --frozen pytest tests/integration/test_ace_continuation_live.py -q
```

`ACE_LIVE_REPORT_DIR` controls result output (default `/tmp`). For exact build
evidence, `ACE_LIVE_RUNTIME_SOURCE_ROOT` points to the unchanged build tree used
for that running API; otherwise reports label hashes as local-checkout evidence.
The independent test uses SDK/HTTP only, switches models, verifies the next
action and recovered receipts, and rejects stale/interrupted/expired continuation.
It saves failed runs with `completed=false`; preliminary passing checks are not
overall task success. It is not a benchmark or cross-provider certification.

## Validation

```
uv run --frozen pytest
uv run --frozen pyright
CG_INTEGRATION=1 CG_NEO4J__URI=bolt://127.0.0.1:7690 \
  CG_MONGO__DATABASE=ace_baseline_test uv run --frozen pytest tests/integration
```

Integration services must be disposable. New Mongo tests create unique databases
and remove them at teardown. Neo4j adapter tests delete only their tagged nodes.
The preserved store tests write eight-dimensional vectors; do not point them at
an application's 2048-dimensional graph. The vector score tests now include
tied candidates instead of assuming a unique nearest neighbor.

Live-model Streamlit integration additionally needs a seeded user/team graph and
provider credentials. It is not validated by database-only tests or mocked
providers. No full model-quality, latency/cost or benchmark result is claimed.

Current live validation and remaining production gates are recorded in [validation.md](validation.md). For initialization, Compose, privacy controls and recovery, follow [operations.md](operations.md).


## Workspace navigation and conversational task updates

`GET /v1/projects` returns only the authenticated principal's project grants and
permissions. `GET /v1/sessions?project_id=...&limit=30&cursor=...` lists only that
user's project conversations in descending last-append order. Cursors are scoped
to tenant/user/project, metadata pages omit event text, and pre-existing streams
without navigation metadata remain readable. `POST /v1/sessions/{session_id}/title`
accepts `{"title":"Research notes"}` for an owned project conversation. Renaming
changes display metadata, preserving immutable stream content and activity order.
The SDK exposes `projects`, `sessions` and `rename_session`.

`WorkspaceAssistant` composes the existing SDK and ResearchAssistant. Its quoted
TaskIntent deltas update the canonical `project-work` task through the existing
CAS contract. It adds no workflow executor. WorkState's `reported_completed`
contains exact user quotes and source session/event IDs, distinct from `completed`
receipts. The service rejects new reports without the authenticated user's actual
source quote; agents cannot approve user reports. Empty new work fields preserve
legacy handoff idempotency hashes.

Additive EventInput fields are `suggested_next_steps` and `task_context`
(assistant answers only), and `correction_target` (correction events only, containing
the existing RevocationInput contract). The latter allows interrupted corrections
to recover the original scoped item/fingerprint. Existing defaults and old host
schemas remain intact; workspace schemas are opt-in. Upgrade API and worker with
the UI. `AgentContextClient.revoke` calls the existing revocation endpoint.

See [workspace behavior and focused tests](../../ui/README.md). This change does
not implement the deferred usefulness or production-readiness work.
