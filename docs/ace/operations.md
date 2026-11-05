# Development and recovery runbook

## One-command local launcher

In a local clone of the Agent-Context-Engine repository, run:

```sh
./run.sh
```

Run as your normal user. On Ubuntu/Debian (including systemd-enabled WSL2), the
launcher installs missing Docker Engine using Docker's official installer, and
installs an available Compose v2 package if needed. On macOS, it installs missing
Homebrew and Docker Desktop through their official installers. OS installation
can require your administrator password; Docker Desktop may need first-launch
approval. Windows users run this script inside Ubuntu/WSL2, not PowerShell.
Other Linux distributions can use an already installed Docker/Compose setup.
Allow roughly 8 GB memory and 10 GB free disk for a comfortable local demo.

The launcher installs uv if absent, uses Python 3.12 and frozen dependencies,
creates private `.env` authentication with the existing initializer, generates a
database password only for a fresh local file, and asks for a missing NVIDIA key
without echoing it. For unattended execution, provide `NVIDIA_API_KEY` through a
secure environment. Optional `BRAVE_SEARCH_API_KEY` can be set in `.env` later;
the launcher never requires it. Real keys are not provided by the repository.

It builds/starts MongoDB, Neo4j, the API and worker with Compose readiness checks,
starts the UI on loopback, prints both URLs, and attempts to open your browser.
The worker automatically processes events; no separate ingestion command is
needed. Once per checkout, the launcher also runs the existing synthetic
three-session demo against the actual API/worker/NVIDIA model. This consumes
provider quota and records demo language preferences in this local trust
partition. A successful demo is marked only after all six outcome checks pass.
If it fails, the UI remains available and the failure/log location is printed;
the next launch retries. Demo reports are not automatically displayed in the
console's new browser session; inspect `data/ace_demo/` or `.ace/demo.log` and
send your own request in the UI.

Defaults are UI `http://127.0.0.1:8501` and API `http://127.0.0.1:18000`.
These are local URLs, not a public deployment. Keep the launcher terminal open.
Ctrl+C stops its UI while backend services and data remain available.

```sh
./run.sh --skip-demo           # services + UI, no startup model demo
./run.sh --demo                # repeat the live three-session demo
./run.sh --no-browser          # print URLs without opening a browser
./run.sh --logs                # follow backend logs
./run.sh --stop                # stop backend services, retain database volumes
ACE_UI_PORT=8502 ACE_EXTERNAL_PORT=18200 ./run.sh
```

After upgrading from the old six-flag demo, run `./run.sh --demo` once: an old
success marker otherwise skips the new outcome verifier. The updated demo
requires a delivered supported recommendation, not just Spanish words or a source
name. Reports retain typed assessments, independently checked quotes/source IDs,
model/source versions and separate host/verifier usage. The verifier uses the
same provider as generation; it is not universal semantic proof or total billing.

Reruns reuse existing credentials and database volumes. Configuration is never
executed as shell code. The console API URL is set to the locally launched API;
existing bearer tokens, database password, model/search settings are preserved.
An incomplete pre-existing authentication file fails with repair guidance rather
than generating replacement identities. `.env` and ignored `.ace/` logs/state
are private (new files mode 0600; new directories mode 0700). They are excluded
from Git and the Docker build context. A valid CA file is selected for Docker's
build secret/runtime mount; an explicit invalid CA path fails without disabling
verification. The startup path does not delete volumes or reset stored context.

## Fresh local setup

```sh
uv sync --frozen --system-certs
uv run --frozen agent-context-init
```

The initializer creates `.env` exclusively with mode 0600, separate user/host
credentials and their server-side SHA-256 bindings. It refuses to overwrite an
existing file and never prints the credential values. Configure the model key
securely in environment settings or the ignored local file. Do not commit it.
Use one isolated Neo4j/Mongo trust partition per tenant/user deployment.

```sh
docker compose up --build -d
```

API readiness is checked internally by Compose. API is bound only to loopback,
port 18000 by default; databases have no published ports in this stack. The image
excludes `.env`, Git metadata, datasets, logs and tests. The worker receives the
chat credential; semantic API retrieval receives an embedding credential (local
Compose falls back to the NVIDIA key). Raw console tokens are not copied into
service environments.
CA trust is mounted read-only through `ACE_CA_BUNDLE`, defaulting to the host's
system bundle. Do not disable TLS verification. Local database authentication and
networking are development settings, not a secure production deployment template.

For the controlled benchmark fixture initialize with `--tenant ace-live --user
research-user` in a fresh checkout/partition. Set `ACE_API_URL` to the local API
port used by the selected host or Compose stack. Run:

```sh
uv run --frozen agent-context-demo
uv run --frozen agent-context-evaluate data/ace_demo/<run-id>.json
uv run --frozen python -m streamlit run ui/context_engine.py --server.headless=true
```

The new console displays actual research answers, selected context, token counts,
evidence, exclusion reasons, verified tool work and handoff revisions. The original
`ui/streamlit_app.py` remains a local legacy diagnostic view. Do not expose its raw
user-selection/graph-planning interface as a multi-tenant authenticated product.

## Updating project memory and session behavior

After pulling the project-binding/grounding fix, restart using
`./run.sh --skip-demo` (stop the existing UI with Ctrl+C first). The launcher
rebuilds API/worker code as well as restarting the console. PROJECT context is
now stored under the authenticated event's project ID using the same tenant
namespace as retrieval; model-generated project labels do not choose IDs.
No database-wide scope migration or authorization widening is performed.
Previously mis-scoped records must be asserted again after upgrading. Existing
USER-scoped records remain user-scoped; historical evidence is preserved.

Answers can cite `memory:<context-id>` in addition to verified document IDs. The
console shows the cited memory and its evidence episode IDs. These citations
validate source identity/provenance, not automatic semantic proof of every
sentence. A cached answer whose cited memory is no longer selected cannot be
reused; start a new turn. Web-required mode still requires document evidence.

**New session** clears previous input, result/context and web-search selections.
An explicit saved handoff remains available for continuation; durable memory is
not erased by starting a new session.

## Upgrading existing session project bindings

The 2026-11-05 session-scope fix requires trusted owner/project metadata on graph
Sessions. New worker projections write it automatically. Existing sessions whose
binding is unknown are withheld from SESSION retrieval and source evidence until
backfilled; USER/PROJECT fact semantics are not rewritten. Apply this metadata
migration to an existing isolated tenant/user deployment after upgrading its API
and worker. Take the normal coordinated store checkpoint first. The local stack
is a development deployment, not a verified disaster-recovery system.

Quiesce the worker during planning/apply. Use the existing configured API container
so tenant/user, database names and credentials match the actual deployment. The
default local Compose Mongo database is `agent_context`; merely changing a host
environment variable does not change that Compose setting.

```sh
docker compose stop worker
docker compose exec -T api python -m agent_context.session_bindings plan --plan-file /tmp/ace-session-bindings-v1.json
mkdir -p .ace
chmod 700 .ace
docker compose cp api:/tmp/ace-session-bindings-v1.json .ace/session-bindings-v1.json
chmod 600 .ace/session-bindings-v1.json
# Inspect the private plan's identities, hashes and before-state before applying.
docker compose exec -T api python -m agent_context.session_bindings apply --plan-file /tmp/ace-session-bindings-v1.json
docker compose start worker
```

Planning makes no changes. A plan is bounded to 4096 trusted streams and contains
identities/hashes, not conversation text. Retain it securely outside the container
for recovery. Apply checks the authoritative outbox and active privacy fence,
then compares all binding fields before updating only Session metadata. It is
safe to retry after partial progress. Conflicting owner/project/source identities
fail rather than overwrite data; investigate and re-plan, never edit the plan to
force a different project. Legacy sessions without a trusted ACE stream are not
assigned a guessed binding; they remain withheld.

If rollback is needed, stop the worker and restore the retained plan into the
current API container before invoking it:

```sh
docker compose stop worker
docker compose cp .ace/session-bindings-v1.json api:/tmp/ace-session-bindings-v1.json
docker compose exec -T api python -m agent_context.session_bindings rollback --plan-file /tmp/ace-session-bindings-v1.json
docker compose start worker
```

Rollback restores exact prior binding fields only while the migration still owns
them. A later trusted worker reaffirmation clears the migration marker, so an old
rollback refuses to overwrite it. An unbound rollback result is again withheld;
it does not bypass authorization. Neither direction rewrites Context/Episode
content, deletes records or calls a model. Real-store tests cover dry-run, apply,
retry, rollback, immutable binding and rejection after worker reaffirmation.
The isolated audit stack backfilled three sessions; the user-facing stack was
not migrated or redeployed by that test.

## Repeated bounded evaluation

Use the existing evaluator against a fresh verified report in the same isolated
fixture/database, not a copied report without its corresponding source events:

```sh
uv run --frozen agent-context-evaluate data/ace_demo/<run-id>.json --trials 3 --context-bytes 4000 --seed 0
uv run --frozen agent-context-evaluate data/ace_demo/<run-id>.json --trials 3 --context-bytes 500 --seed 0
```

Reports use unique filenames under `data/ace_evaluation/` and retain input hashes,
source snapshots, seeds, source registries, individual failures and reported chat
usage. The original six-flag source report is rejected before network calls.
Embedding/server usage and dollar prices are not inferred. This remains one
synthetic scenario, not a public-dataset benchmark. The saved v5 runs tied on
task success; compare preparation plus answer cost before making savings claims.

Basic SDK requests omit unused new defaults and were checked against the old
running API. Upgrade API/worker/SDK together to use new task/search fields;
an old backend does not gain new functionality from a newer client.

## Optional web search

Set `BRAVE_SEARCH_API_KEY` in the console process's secure environment or ignored
`.env`. It is optional; API/worker startup and the bundled sample-document demo
continue to work without it. Restart the console after changing its environment.
After pulling this change, rebuild/restart the API and worker with
`docker compose up --build -d` so their additive event schema accepts stored
answer citations. Existing events remain readable.

In the console, expand **Web search (optional)**, enter a **Web search query** and
click **Search web**. Enable **Use these web results for the next answer**, then
ask your question in **Message**. The research host must read at least one selected
source before answering. **Cited web source** buttons open only the validated URLs
corresponding to the sources actually cited by that answer.

Only the explicit search query is sent to Brave; the app does not automatically
forward stored personal context, chat history, NVIDIA credentials or handoffs to
the search service. Search snippets are bounded untrusted evidence, not full web
page reads. Redirects are not followed and arbitrary result URLs are never fetched
by the server. Private/local/credential-bearing URLs are excluded. Source
snapshots, citations and authenticated read outcomes are preserved through the
same event path as sample documents; changed sources cannot silently reuse a
cached answer.

`ACE_SEARCH_RESULT_COUNT` (1–5) and `ACE_SEARCH_TIMEOUT_SECONDS` configure the
optional adapter. Provider authentication/rate-limit failures and empty results
are shown explicitly. Without a key, the search button is disabled with setup
guidance. The implementation was tested with mocked Brave responses and real
local event-store integration; live Brave validation is deferred until a key is
configured.

## Revocation, export and erasure

Authenticated API controls include owned session inspection, scoped evidence,
`POST /v1/context/revocations`, streamed `GET /v1/users/me/export`, and
`DELETE /v1/users/me/context`. Revocation requires the selected item's fingerprint
and correct permission. It persists a visibility fence before graph changes;
replay cannot reactivate a user-revoked node. The fence has a bounded metadata
quota and fails closed rather than silently forgetting older revocations.

Erasure requires the distinct delete permission. Quarantine immediately blocks
new intake, assembly, artifacts and handoffs for that subject. Maintenance waits
for active processing leases, then idempotently removes owned canonical context,
unshared concept vectors, episodes, processing checkpoints/results, events,
handoffs, artifacts and assembly records. Other subjects' records are preserved.
`GET /v1/users/me/erasure` remains readable by the authorized subject after
quarantine and reports primary-storage state and external backup responsibilities.

Downloaded exports cannot be recalled from a user's computer. Production backup
retention, legal holds, encrypted storage and account reprovisioning require an
operator policy before any end-to-end hard-deletion SLA can be claimed. Privacy
fences must be applied again after restoring an older database snapshot.

## Failure recovery

- Recorded events are not yet available context. Inspect their status/watermark.
- Restart a crashed worker with the same tenant, user and `ACE_RUN_VERSION` so
  segmentation, extraction and checkpoint identity remain stable.
- A partially committed graph write is reconciled by idempotent replay after the
  Mongo lease expires. Do not reset checkpoints to hide a failed batch.
- Dead-letter replay requires admin permission and the same original event IDs.
- A handoff with changed artifact hashes, expired state or unresolved operations
  must be reconciled before continuing; resume never executes an external action.
- After a host interruption following a verified read, retry the same turn ID and
  message. The host restores recorded read outcomes; it does not perform that
  read again. Changed document content requires explicit reconciliation.
- Use `docker compose stop` to retain development data. Never use volume-removal
  options for an environment containing work that must be preserved.

Compose volumes retain primary data. Production recovery must test coordinated
Mongo and offline/community Neo4j snapshots, preserve privacy tombstones and
outbox watermarks, and re-run consistency checks before exposing restored data.
Those production restore guarantees are not claimed by the development smoke test.
