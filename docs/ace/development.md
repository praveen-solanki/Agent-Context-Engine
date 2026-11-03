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
handoff preparation and handoff resume. It has timeouts and bounded retries for
transient failures. Close it using `await client.aclose()`.

Context bundles use a conservative UTF-8 byte token bound unless a host injects
its model tokenizer. Reserve host/system, tools, request, output and safety
tokens explicitly. Count is checked after rendering; atomic items are never
truncated. Keep `retrieved_data` in a data/tool channel, never elevate it into
system instructions. Optional source failures are explicit; mandatory source
or mandatory-budget failures fail closed.

Handoff completion requires an authenticated successful tool result with matching
call/event/project/session references; a model saying “done” is insufficient.
Resume checks permissions, expected revision, expiration, outstanding operations
and evidence again. It never executes tools. Generic startup rejects artifact
references because arbitrary remote artifact versions cannot be verified safely;
hosts must inject an authoritative verifier through `create_app` for that feature.

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
