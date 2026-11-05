# Validation evidence — latest increment 2026-11-05


## Conversational workspace — focused verification only

Baseline `4e56b06`. Verified the existing host-grounding and initial console
before editing (11 checks), then reused ingestion, task CAS/assembly and governance.
Implemented only the owner-authorized first four conversation/UI improvements;
usefulness/benchmark execution and production-readiness work are deferred.

Final distinct focused checks, accumulated across scoped runs:

| Checks | Result and evidence |
|---|---|
| Source-validated task deltas, durable history and UI interaction | **28 passed**: `tests/unit/test_workspace_continuity.py`, `tests/ui/test_ace_console.py` |
| Actual navigation/task API and Python host over disposable MongoDB | **10 passed**: `tests/integration/test_ace_workspace.py` |
| Directly affected existing answer grounding | **10 passed**: `tests/unit/test_memory_grounding.py` |
| Existing hash compatibility, agent authority/tool receipts and duplicate intake | **3 passed**: selected tests listed below |
| Strict Pyright on changed implementation and tests | **0 errors, 0 warnings** |

No full suite or paid model run was used for this increment. Integration uses
real API/SDK/event/task persistence with mocked planners/answers and explicit
worker watermark advancement. Existing graph extraction, live-provider behavior,
billing, benchmarks and production gates are not claimed newly validated.

The new tests verify current task state across sessions, exact user quotes,
unplanned user reports, blocker/dependency changes, ambiguous intent, unapproved
suggestions, task-version references, scope-bound history/pagination/renaming,
legacy metadata, erasure fences, retry after partial recording without duplicate
document reads, concurrent plan warnings, stale-request refusal after another conversation changes
the plan, and interrupted exact-target corrections.
Streamlit AppTest covers real page controls with replaced service I/O: server
history/browser URL restoration, project switching, automatic submission, retry
IDs, no manual save, plain text, optional search, evidence/correction/removal,
context collapse and protection against replacing an unfinished request.

Reproduce the scoped verification (local disposable MongoDB on port 27017):

```sh
.venv/bin/pytest -q tests/unit/test_workspace_continuity.py tests/ui/test_ace_console.py tests/unit/test_memory_grounding.py
CG_INTEGRATION=1 .venv/bin/pytest -q tests/integration/test_ace_workspace.py \
  tests/integration/test_ace_task_state.py::test_additive_work_fields_preserve_existing_handoff_idempotency_hashes \
  tests/integration/test_ace_task_state.py::test_agents_can_report_proven_progress_but_cannot_approve_requirements \
  tests/integration/test_ace_events.py::test_concurrent_duplicate_intake_has_one_durable_event
.venv/bin/pyright src/agent_context/api.py src/agent_context/client.py \
  src/agent_context/contracts.py src/agent_context/continuity.py \
  src/agent_context/demo.py src/agent_context/event_store.py \
  src/agent_context/governance.py src/agent_context/handoff.py \
  src/agent_context/navigation.py src/agent_context/task_state.py \
  ui/context_engine.py ui/context_engine_view.py ui/workspace.py \
  tests/unit/test_workspace_continuity.py tests/ui/test_ace_console.py \
  tests/integration/test_ace_workspace.py tests/integration/test_ace_task_state.py
```

Existing limits remain: configured projects, one workspace plan per user/project,
128 events/session by default, bounded task revisions/entries/context budgets,
and a document-read-only bundled host. User reports are not external execution
proof. Historical selections are not persisted and are labelled accordingly.
Update API/worker together with UI (`./run.sh --skip-demo`).

Headless Chromium inspected the actual page with a temporary mocked workspace
fixture at 1440×1050 and 390×844. Both viewport checks had matching inner/document
width (no horizontal overflow). The final layout was visually inspected; desktop
context scrolls independently and the Context toggle is available on mobile.
This was a layout check, not a live-model product demonstration.

The older broad-suite and live-model results below are historical evidence;
they were not rerun or used as a new completion claim for this UI increment.

## Reusable public benchmark pipeline — fixture-only verification

**537 passed, two paid live-model checks skipped, one legacy live-model UI case
deselected (22.22 s)**. Strict Pyright: zero errors/warnings. This includes the
new staged benchmark workflow against real isolated MongoDB/Neo4j with all
model/embedding responses mocked. No full public dataset or paid model evaluation
was executed. The benchmark fixture graph was separate from both ordinary
integration data and the user-facing application; its claims/data are cleaned
after tests. The original Context-Graph repository remains unchanged.

```sh
CG_INTEGRATION=1 CG_NEO4J__URI=bolt://127.0.0.1:7690 \
ACE_BENCHMARK_TEST_NEO4J_URI=bolt://127.0.0.1:7693 \
CG_MONGO__DATABASE=ace_remaining_final .venv/bin/pytest \
  -k 'not test_the_ui_runs_the_tool_and_shows_the_result' -q --tb=short
.venv/bin/pyright
```

Before implementation, 39 existing evaluator/oracle/converter tests and 82
writer/retriever/assembler tests passed and their components were preserved.
The new native/normalized fixture suite exercises 24 scheduled mocked trials
across four inputs and all six methods. A separate test runs acquisition,
preparation, enabled execution, scoring/reporting and zero-provider-call resume
through the actual CLI functions. Ground-truth labels stay outside generation.
Tests also cover source checksum corruption, bounded/failed downloads, pagination,
per-file acquisition recovery, sample-limit changes, malformed JSON/roles/time,
premixed distractors, provider retries/request ceilings, missing/invalid usage,
saved-judge input mismatch and retained incomplete-attempt costs.

The broader regression caught four cache-identity failures while sampling changes
were still incorrectly compared with full dataset settings. The corrected raw
identity excludes sampling settings; the reproductions and final full suite pass.
The existing meter now treats null/noninteger/negative/malformed usage as unknown
rather than known zero. Optional replay clocks preserve original runtime defaults.

`uv sync --frozen --offline` rebuilt/installed the new command successfully.
The installed `agent-context-benchmark plan ... --dataset longmemeval-s --limit 3`
reported zero model calls, and `schema` emitted valid configuration JSON Schema.
`docker compose -p ace-benchmark -f compose.yaml -f benchmarks/compose.override.yaml
config --quiet` passed without starting another app or printing secrets. CI is
configured to run the fixture integration first on its fresh job graph; no remote
CI result for this new local increment is claimed.

Public reads were limited to upstream documentation/tree metadata, at most
16 KiB of a ConvoMem premixed file and bounded LoCoMo prefixes (its native
timestamp was found after 45056 bytes). That check reproduced an unsupported date
syntax; the parser and fixture now use the actual upstream form. No full benchmark
was acquired/run. LoCoMo's actual `README.MD`/`LICENSE.txt` paths and advertised
CC-BY-NC-4.0 license are now verified; prior 404s used different filenames.
See [pipeline verification record](results/benchmark-pipeline-verification-20261105.json)
and [setup/execution guide](benchmarks.md). That record contains test evidence,
not real dataset accuracy, latency, token savings, dollar totals or official
leaderboard claims. Broader R08 and production-system R09/R10 gates remain open.

## Latest session-scope, compatibility and evaluation increment

The final credential-free regression against disposable MongoDB/Neo4j passed
**506 tests, two explicitly opt-in live tests skipped, one legacy live-model UI
case deselected in 17.65 s**. Strict Pyright reports zero errors/warnings.
The focused real-store HTTP/governance/migration/SDK subset passed nine tests.
The older numbers below are historical checkpoints, not the latest total.

```sh
CG_INTEGRATION=1 CG_NEO4J__URI=bolt://127.0.0.1:7690 \
CG_MONGO__DATABASE=ace_remaining_final .venv/bin/pytest \
  -k 'not test_the_ui_runs_the_tool_and_shows_the_result' -q --tb=short
.venv/bin/pyright
```

The authorization regression first reproduced a known SESSION ID bypassing
removed project access. The fixed real-store API path verifies successful access
before grant removal, then empty assembly/search/trace and inaccessible evidence,
including evidence for USER facts sourced in that private project. Project
metadata comes from the authenticated outbox, not extraction text. Real-store
dry-run/apply/retry/rollback tests verify old unknown bindings remain withheld
and immutable bindings cannot be moved between projects. The isolated benchmark
database actually backfilled three existing Sessions using version-one plans.
The user-facing database was not changed. See the operations migration runbook.
The final binding comparison acquires the Neo4j node write lock before reading
the immutable/CAS fields. Eight competing-initial-binding races each accepted
one project and rejected the other. The temporary lock property was absent
afterward. This is a Session metadata invariant, not distributed fencing of all
graph writes. After the final image rebuild, [worker upgrade smoke](results/session-binding-upgrade-20261105.json)
passed all six checks: real intake/availability, trusted owner/project/version,
temporary lock removal and zero remaining backfill changes for that fixture.

A read-only SDK basic-assembly call to the unchanged API on port 18000 returned
422 before serialization omitted new unused defaults and 200 afterward. Tests
also preserve explicit failed-tool `False` and required expected-version zero.
New task/search capabilities require the new backend; old basic calls remain
compatible. No UI code was changed by this increment.

After rebuilding/recreating only the isolated audit API/worker, the independent
HTTP/SDK continuation check passed again: [current runtime proof](results/continuation-9b926a4a4c3a.json),
all seven checks, Bolt E4B + Lightning 30B, pytest **57.23 s**. The changed-artifact
check also passed: [artifact proof](results/artifact-check-067cc2d19fbe.json).
An initial invocation used the wrong alternate-model environment variable and
stopped with `KeyError: ACE_ALTERNATE_MODEL`; [failed invocation](results/continuation-44589a8d6af3.json)
is retained with `completed=false`. Its preliminary checks are not a successful
two-model run. The corrected invocation passed without a product-code change.
These runs verify a deployment upgrade and recorded-outcome workflow, not a
cross-provider result or distributed crash/backup recovery.

The existing six-baseline evaluator's source gate, citation rubric, query
embeddings, repeated-trial recording and summary budget handling are fixed and
unit-tested. Actual fresh [source run](results/research-source-2d65493471cf.json)
passes the current seven-check gate. Protocol v5 reports for
[4000 bytes](results/2d65493471cf-4000b-5edcfaa970dc.json) and
[500 bytes](results/2d65493471cf-500b-4d786c737183.json) contain 18 answer trials
each: all six methods pass all three trials at both budgets. This is a tie, not
evidence that ACE improves task success. Answer prompt tokens for ACE were lower
than full history, higher than rolling summary; ACE answers were slower here.
Preparation and [worker ingestion usage](results/ace-source-ingestion-2d65493471cf.json)
are separate. Embedding/server usage and prices remain unknown, so no total-cost
or statistical superiority claim is made. Earlier v2/v3/v4 reports retain the
rubric failures and over-budget summary failure rather than rewriting history.

[Dataset audit](results/ace-dataset-audit.json) records actual fetched metadata:
ConvoMem's current noncommercial license/revision, available MIT-advertised
LongMemEval cleaned data, and failed inspected LoCoMo links. No dataset score is
claimed: LongMemEval is available but **NOT YET RUN**, not inaccessible. R08 still
needs broader tasks, public benchmarks, ablations and full cost accounting.
R09/R10 production quotas, TLS/identity, graph fencing, load/chaos and coordinated
privacy-aware restore remain open. The original exposed credential's revocation
is still unverified; the replacement working does not prove revocation.

Publication was initially rejected under approval for an older patch. After
explicit user approval, the three audited increments were pushed through
`cec34e8`; [their GitHub CI passed](https://github.com/praveen-solanki/Agent-Context-Engine/actions/runs/41969960178).
The newer benchmark-pipeline work at the top of this file remains local; no
remote CI result for that increment is claimed.

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

2026-11-05 current-task increment: **480 passed, two explicit opt-in live tests
skipped, one legacy live-UI case deselected in 16.37s**; Pyright clean. Eight
focused real-Mongo state/SDK/HTTP tests verify protected requirements, authentic
event causation, retained verified outcomes, CAS races/replay, mandatory budget,
current scope/selection trace/watermark, stale/reconciled handoffs, revocation and
changed artifacts. The canonical task projection reuses existing handoff CAS,
artifact/outcome verifiers and privacy storage; old snapshot hashes are preserved.

Separately, the isolated real API/worker two-model test passed in **55.00s**:
`results/continuation-c404a96f34ed.json` records both actual model decisions and
seven workflow checks. Current Spanish requirements replaced English; cancelled
work stayed cancelled; completed action IDs were preserved; the host selected
and performed the remaining audit, recovered the recorded receipt without
another execution, and rejected unknown operations/expired handoffs. A separate
**9.09s** live test changed a real stored artifact and proved current-state/bundle
warnings and unsafe resume (`artifact-check-2eed7ca74225.json`).

The first alternate-model attempt failed with an account-level Mistral 404 and
is preserved as `continuation-c78aba3c5cbf.json`, explicitly incomplete. The
successful models are NVIDIA Bolt E4B and Lightning 30B on the same provider;
this does not establish cross-provider support. These are bounded functional
acceptance runs, not multi-scenario benchmark gains, total billing or production
SLOs. Generic task operations are API/SDK capabilities; the frozen console is
unchanged. Arbitrary external tools still need their own idempotency/reconciliation.

2026-11-05 retrieval increment: the full suite with disposable real Mongo/Neo4j
passed **474 tests, one legacy credentialed UI case deselected, in 16.59s**;
Pyright reported zero errors/warnings. Search's missing contract and evidence's
missing exact spans were reproduced before changing them. Focused real-store
tests cover private lexical/semantic recall under 220 irrelevant candidates,
current versus explicit historical values, cap-hidden conflicts, bounded
speaker/trust-preserving evidence, and SDK/HTTP compatibility. Unit tests cover
pagination, changed/invalid cursors, conflicts and historical separation.
The final evidence privacy-recheck tests passed separately (four real-store
cases). `results/retrieval-live-20261105.json` records a real isolated
API/worker/NVIDIA event → available → new-session semantic search → evidence →
bundle check. It reports one synthetic run and source hashes, not benchmark
quality, cost savings or production latency. Semantic/history/search behavior
is now implemented for the private deployment; current task state and shared
scope/load/production gates remain outstanding.

The blueprint is still an incremental product roadmap, not a completed production
certification. Required remaining gates include shared/legacy graph-TASK retrieval
parity, wider multi-session/public-dataset evaluation and ablations, a genuine
cross-provider run, production distributed fencing/quotas, TLS/identity deployment,
external backup erasure/retention and disaster-recovery/load/chaos validation.
Single tenant/user physical trust partition isolation remains mandatory.

Primary-data erasure is implemented and tested, including lease barriers,
revocation replay protection and preservation of foreign records. Minimal privacy
fences/job metadata remain. External backups and already downloaded exports are
explicit operator responsibilities; the service reports `primary_purged`, not a
claim that every external copy has been erased.
