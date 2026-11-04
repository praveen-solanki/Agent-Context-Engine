# Validation evidence — 2026-11-04

## Evidence-first completion audit

Baseline `e55fb5a` was verified before implementation: 450 passed, one launcher
test-double readiness race failed, one unrelated legacy live-model UI case was
deselected. The fake health probe was corrected; production `run.sh` is unchanged.
After the minimal outcome/recall fixes: **463 passed, 1 deselected in 18.82 s**,
strict Pyright zero errors/warnings. Real integration used disposable MongoDB and
Neo4j (7690), separate from the live-model fixture. Commands and per-item skip
decisions are in [REMAINING_WORK.md](../../REMAINING_WORK.md).

The saved `live-demo.json` has a false-positive task oracle: its last answer
declines to recommend while all six old flags pass. That report remains intact
and is not evidence of completed work. The current unchanged-HEAD live rerun did
deliver Option A, but B/C used memory-only citations for document claims; see
[baseline failure](results/demo-audit-baseline-20261104.json). The first stricter
verifier also exposed its own format/language classification errors, preserved
in [v1 failure](results/demo-oracle-v1-failure-20261104.json).

Source checkpoint `9ad2d52` separates typed completion and answer-only language
assessment and independently verifies option, exact quotes, document facts and
citations. [Verified live run](results/live-demo-verified-20261104.json) passes
all per-session outcome checks using actual isolated API/worker/Mongo/Neo4j and
NVIDIA. [Current negative proof](results/recommendation-oracle-negative-v2-20261104.json)
rejects the exact old refusal. Host/verifier provider usage is reported separately;
worker ingestion billing and total cost are unknown. Same-model judging and one
synthetic scenario do not establish universal correctness or comparative benefit.

A real-store regression with 220 recent unrelated preferences hid a 90-day-old
relevant project decision at a candidate cap of 32. Authorized lexical scoring
now precedes LIMIT; the failing test passes. Assembly policy is `ace-assembly-v2`.
No new infrastructure/model call is used. Semantic retrieval, richer search,
task-state sources, temporal/shared parity and source-cost/load gates remain open.

GitHub metadata reports the repository is public. A replacement model credential
was provided and successfully used from ignored private configuration. Revocation
of the earlier exposed key remains unverified by this workspace.

## Project binding, session reset and memory grounding

- **54 focused unit/UI checks passed**, with strict Pyright clean. No local
  end-to-end or live-database suite was run for this focused revision.
- PROJECT write decisions and retrieval query parameters match for multiple
  authorized project IDs, including IDs that cannot be preserved by slugifying.
  Missing project bindings fail closed; untrusted model labels do not select
  graph IDs. Existing message metadata/fingerprints are preserved.
- UI checks verify New session clears the old input, answer, context and search
  query, disables stale handoff saves, and retains an explicit saved handoff.
- Host checks verify memory-only answers without unrelated reads, source/evidence
  presentation, durable citation replay, missing-citation repair, rejection of
  invented/unread source IDs and stale-memory replay, reserved source namespaces,
  and continued document-citation requirements for web research. Tests use
  multiple values; runtime behavior contains no codename/fruit-specific rules.
- Citation checks establish source identity and evidence provenance. They do not
  constitute a universal semantic correctness guarantee for model-generated text.
- No bulk migration of old mis-scoped data is performed. Reassert those facts
  after upgrading API, worker and console; historical evidence remains intact.

## Local launcher

- Complete credential-free regression suite against disposable MongoDB/Neo4j:
  **427 passed, 1 live-model legacy UI test deselected**. Strict Pyright passed
  with zero errors/warnings; `bash -n run.sh` passed.
- Launcher tests cover fresh/private configuration, preserving existing credentials,
  custom/invalid ports, CA path errors, missing keys, sanitized validation errors,
  supported environment overrides through sudo, simulated missing Docker/uv
  installation, startup ordering, successful-demo replay suppression, explicit
  reruns, skipped/failed demos, backend failures, help and safe stop behavior.
- Real fresh-copy launcher smoke test on Linux with existing Docker: built and
  started isolated MongoDB/Neo4j/API/worker services, and served the UI. Both API
  and UI health endpoints returned HTTP 200.
- The automatic NVIDIA-backed demo passed all six real-model checks (document
  reads/citations, current Spanish requirement, excluded superseded English,
  Spanish answer and cached replay). Its measured demo duration was **48.604 s**;
  this excludes installation/build and is not a timing guarantee.
- Real `--stop` and restart passed. The existing `.env` was byte-for-byte
  unchanged, services/UI became ready again, and the completed demo was skipped.
- Native fresh-OS Docker installation, macOS/Homebrew/Docker Desktop and WSL2
  were not executed in this Linux workspace. Missing-tool installers are exercised
  through hermetic fake executables; native platform acceptance remains pending.

The original Context-Graph checkout remains unchanged. Work continues only in the
Agent-Context-Engine copy. Baseline: `3e2454e09deb12aa68c90e76a4948c221d7974b2`.

## Current validation

- Optional web-search revision: **404 tests passed, one live-model UI test
  deselected** for this credential-free run; Pyright clean. Search requests were
  mocked as requested. No live Brave credential or response is claimed.
- Previous full live-provider validation: **375 tests passed, no skips or deselections**, including the live NVIDIA-backed
  legacy Streamlit test with entirely fictional person/team fixtures.
- Strict Pyright: **zero errors and warnings**.
- Real NVIDIA structured-chat and 2048-dimensional embedding probes passed.
- Historical three-session report passed six weak checks but its last answer
  refused to recommend. It is preserved as a negative example; the newly verified
  report above supersedes it as evidence of bounded task completion.
- Container image build, database readiness and authenticated API readiness
  passed. API/worker run as a non-root user; runtime logs use a writable path.
- Credential-value scan of tracked and pending source files passed. The supplied
  key was moved from the tracked example to ignored runtime configuration. Its
  earlier Git history remains; rotation is required to invalidate that copy.

Optional-search checks cover the fixed HTTPS provider endpoint, query-only
requests, missing credentials, authentication/rate-limit/timeout errors, rejected
redirects, bounded response bodies, malformed/empty responses, unsafe URLs,
deduplication, actual search-button rendering, source snapshots, durable answer
citations and recovery without repeating reads. Search-required turns cannot
answer before reading a selected source. Changing an already cited source cannot
silently return the old cached answer.

Reproduce the full suite with disposable integration databases and configured
model credentials:

```sh
CG_INTEGRATION=1 CG_NEO4J__URI=bolt://127.0.0.1:7690 \
  CG_MONGO__DATABASE=ace_baseline_test uv run --frozen pytest
uv run --frozen pyright
```

The store tests use eight-dimensional vectors. Use a separate graph from the
2048-dimensional live ingestion/demo. Live UI fixtures clean up only their tagged
synthetic nodes. Mock provider tests explicitly isolate batch settings from local
NIM configuration.

## Measured comparison

[Six-baseline probe](results/baseline-probe.json): full history, last three
records, running summary, vector top three, the original retriever and ACE.
All received the same model, query, document, schema and context budget. All six
selected the correct current language and next action in this one scenario.
ACE also emitted an episode reference outside the probe's strict document-only
citation rubric; that first-pass citation failure is preserved in the report.
The research host now rejects/repairs unsupported citations with a bounded budget,
covered by real-event-store tests including interruption after a successful read.

This is **one synthetic scenario and one trial**, not evidence of universal task
success, statistical superiority or production latency. Running-summary and
embedding preparation are recorded separately. Ingestion billing, failed-request
billing and provider price tables are not combined into a dollar-per-task claim.
No prices, confidence intervals or public dataset results have been invented.

## Defects found and corrected

- Mixed user/tool episodes could launder tool text through a first-speaker trust
  label. ACE now enforces exact-span trust boundaries and keeps untrusted tool/
  agent events as evidence without treating them as durable user instructions.
- Unresolved values such as “current” could become canonical language preferences.
  The ACE bridge now deterministically rejects these unsupported values.
- A model could reread a document or invent a citation. The host limits available
  documents, records authenticated outcomes, recovers partial reads, validates
  citations, and returns cached answers without repeating actions.
- Settings-source deep merging could retain lower-priority authentication bindings.
  The highest-priority registry now replaces the lower-priority registry as a whole.
- Root validation errors and diagnostic fields could echo sensitive content.
  Runtime settings hide inputs; general pipeline logs redact private fields.
- NIM returned HTTP 500 for mixed-input embedding batches. Every single-input
  request succeeded; the development/evaluation configuration uses batch size one.
- The container worker initially could not write its log directory. Logs now use
  a writable temporary directory without granting the process root privileges.

## Remaining whole-product gates

The blueprint is still an incremental product roadmap, not a completed production
certification. Required remaining gates include shared/task/historical retrieval
parity, wider multi-session/public-dataset evaluation and ablations, a genuine
cross-provider run, production distributed fencing/quotas, TLS/identity deployment,
external backup erasure/retention and disaster-recovery/load/chaos validation.
Single tenant/user physical trust partition isolation remains mandatory.

Primary-data erasure is implemented and tested, including lease barriers,
revocation replay protection and preservation of foreign records. Minimal privacy
fences/job metadata remain. External backups and already downloaded exports are
explicit operator responsibilities; the service reports `primary_purged`, not a
claim that every external copy has been erased.
