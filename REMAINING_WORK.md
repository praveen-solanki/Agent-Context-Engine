# Agent Context Engine — Remaining Work, Verification and Completion Checklist

**Repository:** https://github.com/praveen-solanki/Agent-Context-Engine  
**Reference requirements:** [CONTEXT_ENGINE_MASTER_BLUEPRINT.md](CONTEXT_ENGINE_MASTER_BLUEPRINT.md)  
**Reference implementation:** [docs/ace/architecture.md](docs/ace/architecture.md), [docs/ace/validation.md](docs/ace/validation.md), [docs/ace/operations.md](docs/ace/operations.md)  
**Baseline inspected:** main at commit [4da284123868b1471d5add66c29810d11f5f351a](https://github.com/praveen-solanki/Agent-Context-Engine/commit/4da284123868b1471d5add66c29810d11f5f351a), 2026-11-04.  
**Purpose:** Finish and verify the **already-agreed Agent Context Engine**, without introducing new product features, choosing a different product direction, or rebuilding the existing context graph.  
**Status:** A gap-closing execution plan, **not** evidence that the work described as pending has been completed. Update this file after each verified change.

> **MANDATORY INSTRUCTION TO ANY FUTURE CODING ASSISTANT:** Start by reading this entire file, the master blueprint, AGENTS.md, README.md, and the actual relevant source and tests. Re-check the latest main branch before changing anything. For **every** task below, search for the existing implementation, inspect its call path and tests, run the relevant tests, and compare observed behavior with the acceptance criteria. **If it is already implemented and passes meaningful verification, mark CONFIRMED DONE, cite the code/test/results, and SKIP it. Do not reimplement, refactor, rename or add a parallel version.** If partially implemented, fix only the concrete missing behavior. Do not take a checkbox, documentation claim, a passing mocked unit test or a previous chat's statement as sufficient proof.

---

## Automatic owned projects and concurrent defect corrections — 2026-11-05

**CONFIRMED DONE within the scoped verification bounds.** The owner explicitly
authorized this extension and concurrent screenshot defect fixes, overriding older
fixed-project/UI-freeze notes for this increment. Reused existing auth, immutable
streams, task CAS, retrieval/assembler, SDK/host and governance rather than rebuilding.

- Added a bounded owner directory and trusted same-owner host delegation; semantic
  proposals resolve before event/memory/tool/task writes. Clear existing projects
  reuse their ID; clear new active work creates a private owned entry.
- Added ambiguity/multi-project rephrasing, manual override, stable aliases/renames,
  quota/conflict handling, Personal space and project-less owner bootstrap. Existing
  configured projects use approved goal hints and stable-ID display-name overlays.
- Scope switches open new bound conversations; retries retain their binding and
  explicit research sources. No existing transcript/task identity is rewritten.
- Fixed stale headings/chat/task during project switches, project-specific USER
  memories crossing the panel boundary, and question/refusal-derived unknown facts.
  Explicit personal preferences and real user uncertainty remain supported.
- Included directory metadata in owner export/primary erasure and privacy quarantine.

Evidence: **79 targeted checks passed across scoped runs**, changed-code/test
Pyright clean; source-level reproductions and a four-second local stale-frame
browser check are recorded in [validation](docs/ace/validation.md) and the
[verification artifact](docs/ace/results/automatic-project-routing-20261105.json).
See the [complete identified failure matrix](docs/ace/project-routing.md) for
coverage, setup, architecture and limits. No full suite/application run, public benchmark or production-readiness work was performed.


A separate capped probe made three live model-only requests with no database writes.
Existing-project and multi-project proposals matched expectations. The new-project
proposal failed the conservative ID/confidence guards; explicit **Create and use
project** confirmation is implemented and tested without weakening those guards.
Billing was not measured. This is not a semantic accuracy benchmark.

Remaining limits are explicit: semantic resolution can be mistaken; ambiguity is
not guessed. Unsent drafts are browser-local. No automatic project merge/history
move or bulk task rollback. Legacy project-origin USER memories without personal
proof remain source-bound (no deletion); reassert real global preferences as needed.
Update API, worker and UI together. Standing owner preference: push completed,
verified changes automatically. Earlier UI/constraint increments through `f9467ad`
are already published; this increment's publication is recorded in the task reply.

---

## Constraint-update/recall follow-up — 2026-11-05

**CONFIRMED DEFECT → FIXED within focused verification bounds.** At `6f8560d`,
NVIDIA copied the approved old goal into TaskIntent while adding an exact new
constraint. Source validation rejected the entire delta because the old goal was
absent from the latest message. An identical approved goal is now a no-op; actual
new facts/goals retain exact-source checks. Invalid proposals get bounded,
field-specific repair instead of immediate discard.

The parser's clarification string also bypassed assembly/citation validation and
could contain an uncited project summary. That path is removed. Only fixed
validation-status flags reach the existing grounded answer host; raw parser prose
is neither published nor supplied as rival evidence. An empty plan is labelled
unknown-next-step for an active goal, not completion.

**38 affected checks passed**, changed-code/test Pyright clean; before-fix
reproductions and capped model-only observations are preserved in
[verification](docs/ace/validation.md) and the
[synthetic probe record](docs/ace/results/workspace-constraint-recall-20261105.json).
Both recorded real-model English/French constraint proposals validate after the
no-op correction; this was local replay of the same outputs, not a new live
workflow run. No full suite, full ingestion E2E, benchmark or production-readiness
work. Previously rejected updates must be restated after upgrade; historical
answers are not rewritten. This follow-up was published as `f9467ad`.

---

## Current UI increment — 2026-11-05 (owner-authorized scope)

This instruction supersedes the older frozen-console/UI exclusions below for
this increment only. Implement the first four conversation/UI improvements;
**do not implement usefulness/benchmark or production-readiness work.** Baseline
`4e56b06` was already pushed and passed GitHub CI. The workspace increment below
was subsequently published as `6f8560d`; the later constraint correction was published as `f9467ad`.

| Requested improvement | Inspected implementation and decision | Verified result |
|---|---|---|
| 1. Automatic conversation-to-project continuity | Existing event ingestion, canonical task CAS and receipts: **CONFIRMED DONE, SKIP rebuilding**. Manual UI handoff controls were partial wiring. Added source-validated TaskIntent orchestration over the same SDK/task service. | **CONFIRMED DONE within tested bounds**: quoted goals/requirements/plans, sourced user progress, cancellations/blockers/dependencies; ordinary questions do not create tasks, ambiguous changes ask for clarification. |
| 2. Persistent project/conversation navigation | Existing streams and project grants: **CONFIRMED DONE, SKIP new storage/auth**. Listing and durable titles were missing. Added metadata/index and owner/project-filtered API/SDK navigation. | **CONFIRMED DONE**: reopening/browser refresh, renaming, pagination, old streams, project/user/tenant isolation and erasure fence. |
| 3. Current-state continuation and honest progress | Current-task assembly and tool verification already exist: **CONFIRMED DONE, SKIP assembler rewrite**. Connected the actual chat host and context panel. | **CONFIRMED DONE within existing bounded tasks/host**: new sessions assemble current task revisions; reports remain unverified; suggestions stay unapproved; receipts survive interrupted answers without duplicate reads; concurrent plan changes produce a warning. |
| 4. Evidence inspection and memory correction/removal | Existing evidence/revocation services: **CONFIRMED DONE, SKIP governance rewrite**. Added real UI actions and durable correction target references. | **CONFIRMED DONE for new wiring**: original statements/tool results, exact memory target/fingerprint, interrupted correction recovery, plain-text evidence, correction/removal controls and pending-request protection. Existing ingestion/governance semantics are reused. |

The UI now has saved projects/conversations on the left, normal conversation in
the centre and a collapsible current-context inspector on the right. No manual
Save progress or Continue your work form is required. This is the actual page,
not a separate demo implementation. See [workspace guide](ui/README.md).

Focused verification: **28 unit/UI checks and ten new real-Mongo API/SDK checks
pass**. Ten directly affected host-grounding checks and three existing compatibility
checks (legacy handoff hash, agent authority/receipts, duplicate intake) also pass:
**51 distinct focused checks total**, accumulated across scoped runs. Strict
Pyright on changed code/tests: zero errors/warnings. No full suite, paid provider
run, full ingestion E2E or benchmark was run. See [validation evidence](docs/ace/validation.md).

Limits remain explicit: configured project grants, one workspace plan per
user/project, existing event/revision/entry/token quotas, source-grounding versus
semantic correctness, and no arbitrary external executor. Source extraction still
uses the existing configured provider/worker. Historic answers are labelled and
do not claim retained original selections. New tests use mocked planners/answers
and explicit worker watermarks, so they do not establish live model reliability.
The two deferred areas remain untouched and open.

---

## Current status and next execution — verified 2026-11-05

**Latest inspected baseline:** `6c76b13`; retrieval increment committed at `8ed65b8`, followed by the verified task-state increment described in Section 7. This supplements the older baseline at the top; **re-verify at HEAD before coding**.

**Already done — confirm and SKIP, do not rebuild:**
- Existing ingestion, segmentation, exact Episode/source spans, extraction, concept resolution, scoped lifecycle, supersession and provenance (B01–B03).
- Bounded authenticated event intake/outbox/worker, corrected project binding, private current-scope retrieval, core deterministic assembler, basic verified handoffs, API/SDK, demo host, primary privacy controls, Docker/local launcher and CI (B04–B11). Preserve implementations and tests.
- **R07 bounded research-demo outcome oracle is fixed and verified**: typed recommendation checks reject the exact prior false-positive refusal; a separate real NVIDIA-backed three-session run delivers the actual Spanish Option A recommendation with document citation. See [verified demo](docs/ace/results/live-demo-verified-20261104.json) and [negative proof](docs/ace/results/recommendation-oracle-negative-v2-20261104.json). Do not implement another oracle; broaden **R08** separately.
- **R01 specific literal-recall starvation defect is fixed**: authorized lexical relevance is scored before the Neo4j LIMIT, with a real-database regression of 220 irrelevant newer items versus a relevant older decision. Do not recreate this fix; **R01 still has other gaps**.
- **Private search/history/evidence and semantic integration are CONFIRMED DONE within the tested bounds**: `8ed65b8`, real Neo4j tests and `retrieval-live-20261105.json`. Current task state, mandatory packing, stale-to-reconciled handoff, cancellation and verified progress now pass the independent two-model workflow in `continuation-c404a96f34ed.json`; changed-artifact refusal passes `artifact-check-2eed7ca74225.json`. Preserve these implementations; broader benchmark/production gates remain open.

**Still open — in strict priority order:**

| Order | Requirement | Still needed (only if current code/tests do not already satisfy it) | Concrete finish criterion |
|---|---|---|---|
| 1 | **R01 + R05 — retrieval parity** | Tested private lexical/semantic/history/search/evidence and operational TASK sources are done; preserve them. Broad retrieval quality/cost and load remain to measure. Shared directory/legacy graph-TASK support remains explicitly fail-closed under the selected partition model. | Extend only a demonstrated remaining gap; do not rebuild confirmed paths. |
| 2 | **R02 — adaptive context assembly** | Current task section, verified progress, accepted constraints, atomic mandatory budget, scope/selection trace and watermark are wired and tested. Wider quality/noise/utility comparisons remain R08. | Preserve the verified assembler and evaluate its actual benefit. |
| 3 | **R03 + remaining R04 — continuation** | Bounded authenticated task transitions and safe current-state resume now pass real-service tests. Unknown external side effects still require host reconciliation; arbitrary external exactly-once behavior is not claimed. | Preserve known-receipt retry safety; distributed/crash/recovery closure remains R10. |
| 4 | **R06 — independent host/model use** | SDK/HTTP-only host passed with two accessible NVIDIA models. Genuine cross-provider run remains UNVERIFIED without a second configured provider. The catalogue-listed Mistral model returned 404; failed report is preserved. | Run the same contract on an available alternate provider; do not infer it from model settings. |
| 5 | **R08 — rigorous evaluation** | Expand beyond the one synthetic six-baseline probe: representative multi-session datasets, repeated task-success checks, state correctness, ablations, full ingestion/host/provider token-cost and latency accounting, security failures. | Reproducible comparison showing measured benefits **or honest negative findings**, no invented superiority claim. |
| 6 | **R09 + R10 — production gates** | Tenant-isolation/deployment decision; verify rotation/revocation of historically exposed credential; security and poisoning tests; distributed worker/write fencing; rates/quotas; secure TLS/identity; observability; load/chaos; privacy-aware backup restore and retention. | Target deployment's security, recovery and reliability supported by actual tests/runbooks, not local Docker alone. |
| 7 | **R11 — documentation reconciliation** | Keep README, master blueprint, validation and this file consistent with proven functionality. | Code, tests, documentation and status table agree. |

**Current code:** search is distinct from assembly; runtime wires native lexical/semantic retrieval plus the required current-task source. Historical memory is explicit. Canonical task versions and accepted requirements are reconciled before handoff continuation. Legacy snapshot-only clients retain their documented weaker semantics. Generic task controls remain API/SDK operations; the owner-authorized workspace increment above now connects its current project plan to conversational UI updates.

**Latest local evidence:** **537 passing tests, two paid live checks skipped, one legacy live-UI test deselected (22.22 s)**; Pyright clean. Benchmark integration uses real isolated stores and mocked providers. Earlier two-model continuation and changed-artifact live runs remain separate historical evidence; they were not rerun for this no-paid-benchmark request. Exposed-key revocation remains unverified pending owner confirmation. No production readiness or statistical performance gain is claimed.

**Immediate next task:** The reusable R08 dataset pipeline is implemented and fixture-verified; do not rebuild it or run costly/full benchmarks without a new request. Use `docs/ace/benchmarks.md` for actual experiment commands. Full public results, ablations and real-cost/quality conclusions remain unmeasured. R09/R10, cross-provider validation and exposed-key revocation remain separate open gates. The earlier audit and benchmark pipeline through `4e56b06` were pushed with explicit approval and passed GitHub CI. The newer workspace increment above is local pending publication.

---

## 0. Exact boundary: what success means, what must not change

### 0.1 Product goal (unchanged)

Build a **production-oriented context engineering system for long-running AI agents** which:
- derives evidence-backed, scoped, temporally correct context from real user/agent activity;
- knows which context is currently valid, relevant, safe and necessary for the agent's **next task step**;
- assembles a minimal sufficient, budget-bounded context bundle with explicit evidence and selection reasons;
- carries current project/task requirements, verified progress, blockers and next actions across sessions and compatible agents/models;
- safely accepts feedback and corrections, handles revocation and deletion, and maintains provenance;
- exposes an integration surface usable independently of the bundled research demo;
- proves improvement or clearly reports no improvement through reproducible multi-session task evaluation;
- meets the security, reliability, recovery and deployment gates originally defined for production usage.

**The graph is an internal store/index, not the project purpose.** No new generic knowledge-graph capability is a goal. The product is the correct context at the correct agent step.

### 0.2 Strict non-goals: no new features

DO NOT add a new product use case or technology simply because it is trendy. In particular, this completion pass must **not**:
- build another agent framework, unrestricted autonomous coding/browser/computer agent, or multi-agent platform;
- build a second graph, migrate databases merely to remove the word graph, or introduce a new vector database;
- add model training, fine-tuning, RL, new modalities, a new chatbot product, or a new frontend rewrite;
- add MCP or unrelated SDK adapters merely for checklist optics; the existing HTTP/Python interface already establishes the integration boundary. An **independent host/model validation** is required; a new adapter is not, unless a real existing integration contract is broken;
- expand Brave search, document ingestion, UI styling or graph visualization. Existing optional search and UI should remain intact.
- create additional services, abstractions, dependencies or hardcoded thresholds without a demonstrated requirement from the master blueprint and a test proving the gap;
- remove or rewrite working components because another architecture might be fashionable.

Scope is **completing the existing master blueprint**, not feature discovery. If a blueprint item was expressly optional, do not start it unless it is needed to satisfy a mandatory acceptance criterion. A narrower solution passing the intended behavior is better than a large speculative rewrite.

### 0.3 Required per-item verification protocol (apply EVERY time)

Before implementation, fill an entry in the evidence ledger (Section 7):

1. **Locate:** search current code, API routes, settings, tests, docs, call sites, integration points, CI, commits and real saved reports. Record exact files/functions.
2. **Trace:** follow data end-to-end (input → auth → persistence → ingestion → retrieval → selection → host → output/feedback); identify where existing behavior is produced and whether it is wired into the actual product runtime, not just available in an unused module.
3. **Confirm:** run focused unit tests plus relevant real Mongo/Neo4j integration or real-model/demo tests; create a meaningful regression assertion only where the existing test does not establish intended behavior.
4. **Compare:** state which exact acceptance criterion is satisfied and which remains unsatisfied. Record proof of success or a reproducible counterexample.
5. **Decide:** 
   - **CONFIRMED DONE** — code reachable in production path AND relevant tests/results prove the expected behavior → **SKIP all implementation**; optionally update stale documentation.
   - **PARTIAL** — implementation exists but missing wiring, semantics, quality or an acceptance gate → change the **smallest specific part**.
   - **MISSING** — required behavior not found → implement it using current abstractions wherever possible.
   - **UNVERIFIED** — apparent implementation, but tests/live dependencies unavailable → do not call missing or completed; record how to verify and avoid a rewrite.
   - **NOT REQUIRED** — optional/out of scope → leave unchanged.
6. **Verify after edits:** rerun focused tests, related integration, Pyright, old core regression suite and applicable end-to-end demo. No silent degradations.
7. **Close:** link commit/PR, tests, real output, benchmark report, schema/compatibility implications, remaining limitation, date; update both this file and the master-blueprint progress ledger.

Never automatically treat this document's **initial** assessment as final. It is grounded in the specified inspected commit and can become stale.

### 0.4 Evidence strength hierarchy

1. Reproducible, verified real end-to-end scenario, including behavior/asserted outcome and failure path.
2. Live database/provider integration exercising the actual deployed service and worker.
3. Contract/integration tests against real components or faithful doubles.
4. Unit tests isolated around a component.
5. Source inspection alone.
6. README, checklists, saved self-reported validation and previous-chat claims.

A passing GitHub Actions workflow proves the tests in that workflow passed; it does **not** prove all blueprint outcomes. A successful demo run may still have a faulty success criterion. Keep evidence categories separate.

---

## 2026-11-05 — Reusable public-dataset benchmark pipeline

**CONFIRMED DONE — SKIP (fixture-verified implementation):**

- Before edits, 39 existing evaluator/oracle/converter checks and 82 existing
  writer/retriever/assembler checks passed. Existing ingestion, SDK/API, outbox,
  scoring oracle, packing, cosine, provider/retry and legacy retrieval components
  were reused. The original synthetic evaluator and ingestion-only ConvoMem
  converter are preserved; they were not replaced with parallel implementations.
- `agent-context-benchmark` provides `plan`, `schema`, `acquire`, `prepare`,
  explicitly enabled `run`, `score`, `report` and owner-checked scratch `clean`.
  Dataset/method selection, budgets, sampling, seeds, trials, models and prices
  are configuration, not hardcoded research answers.
- Native LongMemEval oracle/s/m, ConvoMem raw/premixed and LoCoMo adapters retain
  QA references, categories, original source evidence and dates. ConvoMem's
  premixed outer distractors remain in history. Normalized JSON/JSONL supports
  supplied offline QA/next-action datasets. Unknown schemas, duplicate IDs,
  future history and malformed data fail before model calls.
- Pinned acquisition supports explicit SHA-256s, paginated Hugging Face file
  discovery, local files/directories, per-file checkpoints and bounded streaming
  JSON. Regression tests reproduced/fixed sampling settings incorrectly
  invalidating raw-cache identity. Limits can now expand without downloading
  unchanged data again; mismatched source identities/checksums are rejected.
- Real authenticated HTTP/SDK → outbox → worker → existing ingestion → assembly
  and legacy retrieval run against exclusive empty scratch stores. Subject/history
  isolation avoids the global resolver's shared-state contamination. Store reset
  requires matching ownership in both stores and an `ace_benchmark_` Mongo name;
  populated unclaimed stores are refused. Replay clocks are injected into
  existing effective-write/promotion/retrieval/assembly paths; default runtime
  clocks and UI behavior remain unchanged.
- All six methods use the same answer model/prompt/schema, question/date, context
  allowance and output budget. Summaries are rolling and bounded, passage/query
  embeddings are distinct, summary/vector caches are checksum verified, and
  identical subject/history ingestion can be reused. No ground-truth labels are
  sent to ingestion/preparation/generation; only the optional judge receives them.
- Deterministic EM/F1 and abstention diagnostics, optional category-aware judge,
  source recall where mapped, category metrics, subject/conversation-clustered
  intervals and sample-limited latency percentiles are automated. Saved judge
  results bind exact inputs/version; a changed answer cannot reuse an old verdict.
- Stage-level chat/embedding attempts, failures, reported tokens, latencies and
  configured USD rates are retained. Missing/invalid/null usage is unknown rather
  than zero. Shared work is charged once globally, with separate per-method setup
  attribution. Archived incomplete attempts remain in all-attempt cost totals.
  A hard request ceiling also covers retries/repairs; `run` without `--execute`
  makes no provider calls. Resume skips completed cases and preserves failures.
- Private per-case/run JSON, Markdown summaries and LongMemEval-compatible
  hypothesis exports retain configuration, source/model/prompt/code fingerprints
  and dependency versions. No official semantic-score equivalence is asserted.

**Evidence and setup:** [benchmark guide](docs/ace/benchmarks.md),
`tests/unit/test_benchmark_datasets.py`, `test_benchmark_runner.py`,
`tests/integration/test_benchmark_pipeline.py` and the validation ledger. The
integration suite uses tiny native/normalized fixtures, real isolated stores and
fully mocked model/embedding responses, including the CLI's complete staged path
and zero-call resume. CI is configured to run these fixtures first on its empty
graph. The current changes have not yet run on remote CI.
Final regression: **537 passed, two paid live-model checks skipped, one legacy
live-UI case deselected (22.22 s)**; Pyright zero errors/warnings. The installed
CLI and documented Compose override validate. See
`docs/ace/results/benchmark-pipeline-verification-20261105.json` for the exact
commands and source fingerprints.

**R08 remains PARTIAL for measured results:** per the user's explicit instruction,
no full dataset evaluation or paid model experiment ran. Native full-corpus
compatibility, actual benchmark quality, real dollar costs, official evaluator
parity and large-run performance remain unmeasured. LoCoMo's actual
`README.MD`/`LICENSE.txt` were found and its CC-BY-NC-4.0 metadata verified;
older differently cased URL 404s are historical. MemoryArena/StateMemBench/handoff
assets still lack a verified native integration; normalized offline exports are
supported, not their interactive environments. R09/R10 production-system gates
are unchanged. See `docs/ace/validation.md` for final executed test counts.

## 2026-11-05 — R08 measurement and R09 session-scope increment

**Status: PARTIAL overall.** This is an evidence update, not completion of the
public-benchmark or production-readiness gates. Existing ingestion, recommendation
oracle, assembly, task/CAS, handoff and privacy primitives were inspected and
preserved. The only changes address reproduced missing/incorrect behavior.

**CONFIRMED DONE — SKIP, within these bounds:**

- `evaluation.py` now rejects the obsolete six-flag source report before creating
  clients. It reuses the existing typed R07 recommendation oracle and recomputes
  all saved A/B/C outcome checks, verifier version, document hash and replay gate.
  Red/negative tests demonstrate the earlier gate could accept invalid evidence.
- The existing six baselines now repeat with recorded seeds and shuffled order,
  equal model/prompt/schema/document access/context allowance, immutable source
  snapshots and unique reports. The existing retriever receives embeddings;
  vector queries use the correct query input mode. Failed trials/retries and
  missing usage are retained. No parallel evaluation framework was introduced.
- Citation scoring accepts authoritative memory/episode/event IDs and the
  supplied document, or a hash-bound prepared-context view. IDs embedded in
  untrusted text do not become registry entries. All methods receive the same
  bounded schema-repair policy. The summary baseline is compressed/validated
  against its actual UTF-8 byte allowance rather than silently dropped when
  over budget. These are measurement fixes, not an ACE-specific scoring bonus.
- A real Neo4j regression reproduced a session/project access bypass: graph
  Session metadata discarded the trusted event project binding, so omitting
  `project_id` could retrieve a known private session after its project grant was
  removed. `persist_session` now retains immutable trusted owner/project metadata;
  retrieval, defensive assembly and exact evidence recheck it. Unknown legacy
  bindings fail closed. A real-store HTTP test verifies authorized access first,
  then 403 for an explicit removed project, empty assembly/search/trace without
  that project, and 404 for evidence. It covers source-project privacy even for
  a USER-scoped fact. No conversation text or model-produced ID grants access.
- `session_bindings.py` provides a bounded version-one metadata migration from
  authoritative outbox streams. Dry-run, compare-and-set apply/retry and guarded
  rollback are tested against real MongoDB/Neo4j. Worker reaffirmation prevents
  an old plan rolling back a newer trusted write. No context/value/text rewrite
  or re-ingestion/model call occurs. Three existing sessions in the isolated
  benchmark database were actually backfilled. See the operations runbook before
  applying to an existing installation; no migration ran on the user-facing DB.
  Binding comparisons hold the Neo4j node lock before reading current fields;
  eight real concurrent initial-binding races each accept one project and reject
  the other. The final rebuilt worker passes all six checks in
  [`session-binding-upgrade-20261105.json`](docs/ace/results/session-binding-upgrade-20261105.json),
  including correct trusted metadata and no outstanding fixture backfill.
- New SDK defaults initially broke basic calls to the old running API (422).
  Omitting unset/default fields preserves old basic requests, while retaining
  explicit `False` and required version zero. Unit checks passed, and a read-only
  basic assemble call to the unchanged API on port 18000 then returned 200.
  New search/task functionality still requires the matching updated API.

**Actual R08 result, no superiority claim:** fresh source
[`research-source-2d65493471cf.json`](docs/ace/results/research-source-2d65493471cf.json)
passes the current seven-check recommendation/replay gate. Final protocol v5 ran
three trials for each of six methods at each of two budgets: **36 answer trials,
all passed, no failed trials**. All methods tied on this bounded task.

| Context allowance | Full-history reported prompt tokens | ACE reported prompt tokens | Rolling-summary reported prompt tokens |
| --- | ---: | ---: | ---: |
| 4000 UTF-8 bytes, three trials | 5682 | 1986 | 1326 |
| 500 UTF-8 bytes, three trials | 2010 | 1986 | 1224 |

These are answer prompt-token totals, not end-to-end costs. Summary preparation
and other stage usage are separate. ACE was slower in these saved answer trials;
no latency advantage is claimed. See final
[`4000-byte report`](docs/ace/results/2d65493471cf-4000b-5edcfaa970dc.json) and
[`500-byte report`](docs/ace/results/2d65493471cf-500b-4d786c737183.json).
Earlier v2/v3/v4 reports are retained alongside them, including source-ID rubric
failures and the oversized-summary failure; they are not final product scores.
The separate worker record reports 19 successful ingestion chat responses,
14392 prompt / 1172 completion tokens; embedding/server usage and dollar costs
remain unknown. Do not amortize repeated trials as independent production tasks.

**Public-data audit:**
[`ace-dataset-audit.json`](docs/ace/results/ace-dataset-audit.json) records fetched
metadata and hashes. Salesforce/ConvoMem revision
`e3e9b39115b02346824c70d349350de738f8be41` advertises CC-BY-NC-4.0; the local raw
corpus is absent, and the tracked converted subset lacks QA ground truth and an
exact upstream revision. LongMemEval cleaned revision
`98d7416c24c778c2fee6e6f3006e7a073259d48f` advertises MIT and provides usable data;
it is **AVAILABLE, NOT YET RUN**, not blocked/unavailable. The inspected LoCoMo
primary URLs returned 404; upstream version/license remains unverified. None of
these metadata checks constitutes a public-dataset benchmark score.

**Regression proof:** real disposable-store full suite **506 passed, two opt-in
live checks skipped, one legacy live-model UI case deselected (17.65 s)**;
Pyright zero errors/warnings. Focused HTTP/privacy/migration/SDK checks: nine
passed. New evaluation tests cover a failed provider trial in the actual
comparison loop, source tampering, retry/missing-usage accounting, registry
forgery and multibyte summary budgets. The deployment upgrade is separately
exercised in the isolated audit stack; see `docs/ace/validation.md` for live runs.

**Still open, do not mark done:** public/multi-scenario/state/security comparative
evaluation, ablations, total embedding/ingestion/provider costs, sufficient
independent samples for confidence/tail latency, cross-provider validation,
exposed-key revocation confirmation, production distributed graph fencing,
quotas/identity/TLS/load/chaos and privacy-aware backup/restore. No UI change,
shared-database multi-tenancy, production SLO or exactly-once external transaction
claim is introduced. Publication was initially rejected under approval for an
older patch. The user subsequently approved these three increments; they were
pushed through `cec34e8` and passed GitHub CI. The newer benchmark-pipeline
increment above remains local; its remote CI has not run.

## 1. What is already present — VERIFY ONCE, PRESERVE AND SKIP WHEN CONFIRMED

| ID | Existing capability and location | Initial assessment (2026-11-04) | Confirm and then **skip** |
|---|---|---|---|
| B01 | Existing conversation/Episode/SourceSpan ingestion: src/context_graph/domain, pipeline, graph, ledger | Implemented baseline | Provenance exactness, topic-span integrity, no dropped content; original e2e tests |
| B02 | LLM/similarity segmentation, relevance gate, token batching and temporary extraction rolling state | Implemented baseline | Regression tests; do not mistake temporary RollingSessionState for durable project state |
| B03 | Extraction validation, embeddings, concept resolution, idempotent writing, supersession, scoped policy, candidate promotion and revocation | Implemented baseline | Tests for semantic identity, current value and trust; no duplicate writers |
| B04 | Authenticated event contract and Mongo stream/outbox, event worker, event-to-SessionInput bridge: src/agent_context/contracts.py, events.py, event_store.py, bridge.py, runtime.py | Implemented for bounded ordered streams | User/agent roles, idempotent duplicate, worker retry, watermark/availability, incremental ingestion; do not rebuild ingestion |
| B05 | Scope binding for a trusted project ID, private USER/SESSION/PROJECT candidate retrieval | Implemented for private scopes | tests/unit/test_project_binding.py + tests/integration/test_ace_retrieval.py; do not substitute model-supplied project labels |
| B06 | ContextAssembler with deterministic ranking, dedup, conflict blocking, budget reserve, atomic item packing, JSON data rendering, exclusions | Basic implementation | tests/unit/test_assembly.py; **does not prove richer multi-source/task-aware orchestration** |
| B07 | Versioned Mongo handoffs, optimistic concurrency, verified tool-result completion and content-hashed artifact registry | Implemented for explicit handoff contracts | tests/integration/test_ace_handoff.py; still assess live-state reconciliation |
| B08 | FastAPI routes, trusted principal bindings, request-size limit, Python AgentContextClient | Implemented | tests/integration/test_ace_api.py + client tests; preserve paths and contracts |
| B09 | ResearchAssistant demo, source citation validation and replay control; optional bounded Brave search | Implemented prototype | Host tests and saved live demo; completion evaluator has a weakness (Section 3.1) |
| B10 | Immediate revocation fence, primary-data export, quarantine, lease-aware primary erasure | Implemented with stated limitations | tests/integration/test_ace_governance.py; production backup/legal/restore remains outstanding |
| B11 | Development Docker Compose, one-command launcher, Streamlit console, CI, Pyright | Implemented for local workflow | run.sh, compose.yaml, .github/workflows/ci.yml, docs/ace/validation.md |
| B12 | ConvoMem converter and synthetic generator + initial six-baseline experiment | Present | Comparative scope, methodology and completion metrics remain insufficient |

**Existing claims must be reconciled with the current code.** Do **not** reimplement B01–B12 merely because they also appear in the original blueprint. Fix only problems exposed by Section 2/3 acceptance tests.

**Known saved evidence at audit time:**
- docs/ace/validation.md reports 427 regression passes with one legacy live-model UI test deselected in one run, plus separate live-provider runs; exact conditions differ.
- Latest observed GitHub Actions check at commit 4da2841 was successful.
- docs/ace/results/live-demo.json records a three-session NVIDIA-backed run.
- docs/ace/results/baseline-probe.json reports **one** synthetic comparison with six baselines. All six got language and next-choice fields correct, so it cannot support ACE superiority.
- Never combine these counts into a single newly asserted test run.

---

## 2. Required remaining implementation and verification — ordered by dependency

### R01 — Complete candidate retrieval within the existing context service [CRITICAL]

**Blueprint:** F3 and F4, Phase 2/3.  
**Existing code:** src/agent_context/retrieval.py, assembly.py; retrieval_tester/retrieval.py, retrieval_tester/context_tool.py; src/context_graph/graph/neo4j_store.py.

**Observed at audit:** The deployed runtime constructs ContextAssembler with one Neo4jCandidateSource. Its query filters active private USER/SESSION/PROJECT contexts, sorts mostly by type/recency, and LIMITs candidates *before* the assembler's query relevance scoring. The new assembler computes lexical overlap/priority/recency; the older retriever and schema-planner provide other retrieval behaviors but are not automatically combined into the live context bundle. Shared/team/task/historical retrieval parity is explicitly documented as pending.

**Do, but only where absent:**
1. Confirm what relevance search already exists in Neo4j graph store / original retriever; **reuse it**, not a new index/service.
2. Define/confirm the existing candidate-source contract and expose **authorized** context candidates from semantic, lexical (if needed), pinned/standing, temporal, episodic/evidence and current project/task-state sources. Implement the minimum necessary using existing Neo4j/Mongo interfaces. Keep old graph planner optional and require ablation evidence before using it.
3. Address pre-ranking LIMIT starvation: a relevant but older/non-pinned fact must not be hidden by a flood of recent unrelated facts. Use authorized indexed search + bounded candidate merging, not reading another user's data and filtering afterward.
4. Enforce scope at the datastore query and repeat defensive authorization in assembly: tenant, user, session, bound project; preserve existing trusted organization/directory semantics where original blueprint requires. **Do not** infer grants from user/LLM text.
5. Define requested as-of/current/historical behavior and only active effective state for present-oriented queries. Historic facts may be cited for "what changed" but must not be presented as current instructions.
6. Evidence retrieval should return bounded source excerpts, exact episode/span references and source/trust labels; avoid injecting full transcripts by default. Respect raw event speaker and tool-trust boundaries.
7. Implement an actual progressive **/v1/context/search** if the route still only aliases assemble; authorized search returns candidate/evidence results and pagination/limits rather than pretending a packed bundle is a search result. Reuse underlying retrieval service. If the current route has since been corrected and tested, mark DONE/SKIP.
8. Confirm backend compatibility and performance; do not replace Neo4j for marketing.

**Required adversarial and functional cases:**
- Two hundred recent irrelevant facts cannot crowd out an older relevant project decision.
- Synonymous wording retrieves the correct fact where embeddings/semantic retrieval are applicable; lexical exact key works too.
- A corrected preference wins over its superseded value; historical query can report previous value without making it active.
- A USER or other-project fact never crosses a boundary; TEAM/DEPARTMENT/ORG context only appears with genuine authoritative memberships and policy if included in the target.
- An episode/source ID points to the exact supporting text and real speaker; an untrusted tool snippet is not promoted to user instruction.
- Missing, stale, revoked or expired items do not leak through secondary search paths.

**Done when:** The **actual deployed assembler** receives task/query-relevant, authorized candidates from required sources; tests prove freshness, recall, scope, evidence and bounded cost. A helper method that is never called by the runtime is not completion.

### R02 — Finish adaptive, task-aware ContextBundle assembly [CRITICAL]

**Blueprint:** F4, Phase 3.  
**Existing code:** src/agent_context/assembly.py, contracts.py, retrieval.py, demo.py.

**Observed:** ContextAssembler already does deterministic ranking, conflict withholding, exact rendered JSON, budget checks and exclusions. The initial scorer is query-word intersection + type priority + recency decay. The Neo4j adapter assigns priority 1 for Preference/Constraint/WorkingStyle but does **not** set the required flag. The runtime gives no separate live task-state or handoff candidate source. Thus it is a useful initial memory packer, not yet the complete context orchestration target.

**Required behavior / smallest extension:**
1. Define the **assembly input contract** around next-step objective, project/task ID, authorized session/run, current user request, available token reserves and purpose. Reuse AssembleRequest; only add missing fields justified by an end-to-end scenario.
2. Source an explicit **current task/project state** (see R03) in addition to durable memory. Include effective requirements, decisions, completed verified work, pending actions, blockers and relevant source references in separate typed sections. Do not force the host to manually reconstruct this from unrelated handoff text.
3. Distinguish (a) host-defined trusted policy, (b) user-approved must-keep task constraints, (c) ordinary relevance candidates, (d) untrusted retrieved evidence. A model/text snippet **must not** declare itself mandatory or grant policy authority. Verify origin before assigning required/pinned status.
4. Preserve all applicable **must-keep** content within budget, fail explicitly when it cannot fit, and avoid silently dropping current requirements because there are too many high-priority preferences. Do not blindly treat *every* preference as a hard requirement.
5. Resolve duplicate concepts, effective dates and **competing active single-valued values**; trace why values were excluded or why a conflict is unresolved. Do not select a stale fact solely from recency/similarity. Preserve conflict warning even when a reliable authority cannot resolve it.
6. Implement task-aware, explainable candidate ranking using available relevance/priority/temporal/evidence signals. A deterministic formula is acceptable initially. **Do not require an LLM reranker**; only add one if a measured comparison proves value.
7. Keep structural/semantic dependencies together, preserve immutable evidence handles and conversation/tool-turn boundaries. Support on-demand evidence via the already-intended scoped search interface.
8. Count tokens **after final rendering**, including relevant host allocations. The current UTF-8 bytes method is a conservative upper bound, not actual billed provider tokens. Clearly distinguish the two; if tokenizer support already exists and works, reuse it. Do not claim model-token savings from byte bound alone.
9. Expose selected/excluded reasons, context version, auth scope, source evidence, consistency watermark and runtime/assembly trace in existing bundle/diagnostics contracts where they are missing. Trace must not leak unauthorized IDs or raw private data.
10. Keep retrieved data in data/tool channels; never turn it into system instructions. Test hostile quotes, prompt-like payloads and tool snippets.

**Acceptance scenarios:** Semantically relevant older decision; latest project requirement; conflicting active values; irrelevant long tool result; revoked preference; small valid budget; impossible mandatory budget; unauthorized candidate; source timeout; repeated deterministic assembly; on-demand evidence; same agent action with and without context. Verify no required item silently excluded.

**Done when:** A single authorized agent-step request yields **current, minimal sufficient, evidence-backed, task-aware context**, not just a list of memory facts. Continue to use the existing ContextAssembler and protect current tests.

### R03 — Integrate genuine project/task continuation state with handoffs [CRITICAL]

**Blueprint:** F5, Phase 4.  
**Existing code:** src/agent_context/handoff.py, artifacts.py, outcomes.py, bridge.py, runtime.py, demo.py.

**Observed:** Versioned handoffs with optimistic concurrency exist, and tool outcome/artifact hash checks are meaningful. Resume returns historical handoff plus a freshly assembled bundle and warning flags. However, the handoff is independently supplied by the host; there is no **general live current project/task state** in the context selection path. An old handoff's requirements are not consistently reconciled with newer canonical context. The research host merges historical_handoff separately into its prompt.

**Required completion (no new platform):**
1. Define and persist **current, authorized task/workflow state** using existing Mongo event/handoff/state primitives, only adding a narrowly scoped state projection if needed. Record goal, current requirements, status, verified actions and outputs, pending actions, blockers, dependencies, next-step references and last update/version. Avoid creating a second memory engine or graph ontology.
2. Treat authenticated successful tool outcomes and verified artifact hashes as proof of completed work; model statements remain claims. Maintain a link to original event/episode and exact tool call.
3. Ensure **user corrections and current authoritative requirements override an old handoff's outdated text**. A handoff is an immutable historical snapshot, not authoritative current instruction. Detect and explain stale/inconsistent task state.
4. During resume, validate current principal/project grant, handoff revision/TTL, source event availability, in-flight/pending actions, artifact versions, current task/state version and current context. Mark unsafe and require reconciliation for changes.
5. Produce one clear **resume context bundle** that states current goal, accepted changes, completed verified steps, pending next action, blockers, citations and handoff lineage. Avoid the host silently assembling a second inconsistent prompt using old handoff text.
6. Preserve side-effect idempotency: no re-executing a successful action after retry, crash or session switch; pending/unknown outcome is not marked complete.
7. Support new session and independent compatible agent/model consuming the same documented API; do not embed demo-only language or document names in core continuation logic.
8. If some of these already work end-to-end, document proof and **skip** the matching change.

**Critical acceptance demo:** Session A sets current requirements and completes action X. Session B changes a requirement, cancels an obsolete step and completes Y. Session C requests "continue"; the agent obtains **B's current requirements**, only X/Y as verifiably completed, correct next step and current artifacts. It must not reactivate A's outdated constraint, replay X/Y or make a fake completion claim. Repeat with an interrupted action and an expired/stale handoff. Verify at least one compatible second model or host uses the same engine.

**Done when:** The agent **can actually resume and complete a multi-session task**, not merely receive a preference and a handoff JSON. All task-state claims are grounded in current state/evidence.

### R04 — Complete event/feedback semantics required by continuation [HIGH]

**Blueprint:** F1/F2/F5, Phase 1/4.  
**Existing code:** src/agent_context/contracts.py, events.py, event_store.py, bridge.py, src/context_graph/pipeline/orchestrator.py.

**Observed:** Bounded ordered streams, authenticated user/agent roles, tool results, corrections, revocations and automatic worker processing are present. The current EventKind does not explicitly represent task-state transitions, decisions, output artifacts or tool-call initiation; some information is carried through host handoffs and result events. Late/out-of-order messages are rejected and historical imports are not supported in the new event API. The original CLI does support historical session ingestion.

**Only implement actual gaps found while validating R03:**
- Verify every required workflow transition is attributable, ordered, idempotent and recoverable. If existing handoff/event types already express it correctly, **reuse them**; don't add event kinds for decoration.
- Check session close and incremental append consistency, failed ingestion/availability watermark, duplicate replay, partial graph writes and worker claim expiry. Ensure no “recorded” acknowledgment is mistaken for “context available”.
- Reconcile corrected values, revocations, derived-context opt-out and event source authority through the unchanged core extraction pipeline.
- If old sessions/data need replay to satisfy the original import requirement, use the existing CLI adapter first. Add no new import subsystem until a concrete missing scenario proves necessity.
- Keep tool outputs/agent messages as untrusted evidence; tests for mixed-user/tool spans and source attribution already exist—**confirm and skip** when they pass.
- Validate ownership of project ID comes from trusted event/session binding, not an extraction model label.
- Fail safely when an event is too large/late/inconsistent; document actual API behavior rather than pretending late events are automatically supported.

**Done when:** User correction, tool outcome, task-state change, handoff and next-session assembly work through the real API/worker consistently under retries. No parallel event pipeline.

### R05 — Preserve complete, correct scope and temporal semantics [HIGH]

**Blueprint:** F2/F3/F7, Phase 2/7.  
**Existing code:** src/context_graph/domain/*, pipeline/policy.py, writer.py, graph/neo4j_store.py; src/agent_context/retrieval.py, bridge.py, governance.py.

**Observed:** Trusted private USER/SESSION/PROJECT path is implemented, including a recent project binding repair. Original Context Graph supports more scopes (TEAM/DEPARTMENT/ORGANIZATION) and historical value links; ACE public candidate path currently fails closed for unsupported/shared/task scopes. Documented mis-scoped historical data is not migrated automatically.

**Verification and minimal closure:**
1. Enumerate original supported scopes and the planned agent context semantics. For each, check **write scope → stored identity → authorized read scope → assembly scope**; mismatched namespace IDs must never silently hide data or make it accessible to another principal.
2. Reuse original trusted organization membership logic where shared-scope parity is truly required. Never let a conversation self-grant membership or promote itself into shared authority.
3. Ensure TASK/PROJECT state is attached to an authenticated task/project binding, not text similarity or LLM guessed IDs. Define behavior for unbound or unknown project/task claims.
4. For all scope types actually required in the agreed target, test current values, expirations, supersessions, revocations, permission changes and explicit historical/as-of behavior.
5. Test migrated/legacy input using real representative fixture IDs; when a migration is necessary, create explicit versioned migration, dry-run, rollback and re-ingestion policy. Avoid blanket rewriting old nodes or renaming the package.
6. Test cross-user/project/team isolation and constraint validity before any prompt assembly, including evidence/search/trace/handoff routes.
7. If a scope is deliberately unsupported under the **chosen single-user physical-partition deployment**, record that limitation and validate fail-closed behavior; do not falsely mark full shared/multi-tenant support complete.

**Done when:** Intended scopes and temporal rules are coherent end-to-end; no unauthorized scope crosses into the model, and every unsupported case fails explicitly.

### R06 — Prove the context engine works as a reusable agent service [HIGH]

**Blueprint:** F6, Phase 5.  
**Existing code:** src/agent_context/api.py, client.py, demo.py, runtime.py; ui/context_engine.py, context_engine_view.py.

- Confirm the existing Python SDK and API are sufficient to integrate an **independent agent host** with record → status → assemble → read evidence → handoff → resume. Do not build a new framework or unrelated plugin.
- Validate host/agent identity separation; no client-supplied tenant/user impersonation.
- Check that the host actually consumes the engine's **assembled** bundle at relevant steps and sends authenticated execution outcomes back; it should not bypass the engine with raw historic handoff text.
- Test model/provider portability with the existing OpenAI-compatible provider interfaces and a genuine alternate compatible provider/host where available. Log exact model and environment, do not claim cross-provider based on a config toggle alone.
- Verify the new API contract remains graph-agnostic and usable without knowledge of Cypher, graph node labels or source repo internals.
- Confirm local console shows live selected context, selected/excluded reasons, verified actions, handoff and citations; fix only broken behavior, not UI design aesthetics.
- Keep the original retrieval tester/graph visualization for diagnostics only. Its intentionally read-only/manual ingestion semantics need not be changed or merged into ACE's new demo.
- Confirm fixed endpoint paths do what they claim: especially /v1/context/search is not a no-op alias for assemble; create a distinct search behavior only to fulfill the original on-demand evidence contract (R01).

**Done when:** One non-demo host uses the documented API to consume and update context across sessions with no graph-dependent integration code; real behavior and schema are documented.

### R07 — Correct demo success criteria and establish reliable end-to-end acceptance [CRITICAL]

**Blueprint:** Sections 8/9/13 and Phase 5/6.  
**Existing code/artifacts:** src/agent_context/demo_cli.py, demo.py, tests/integration/test_ace_research_host.py; docs/ace/results/live-demo.json.

**Concrete counterexample from saved report:** Session C's saved Spanish answer says it cannot deliver a final recommendation because it needs more information, while the report's six boolean checks all evaluate to true. The current demo checks "Spanish answer" via a list of Spanish keywords, including words from a *refusal to recommend*. Therefore **all six pass != task completed**. This is a test-oracle weakness in the saved example, **not** proof that the model always fails or that a later code change hasn't fixed it.

**Required work:**
1. First rerun current HEAD with the exact demo inputs and inspect artifacts. If the assertion already checks **actual recommendation and successful continuation**, record that and skip.
2. Define machine-verifiable success for the existing synthetic task: correct current requirement, correct chosen option, adequate source support, final recommendation actually delivered, no stale instructions, correct next action, no repeated side effect, safe handoff and correct replay.
3. Use typed structured outcome fields or deterministic assertions rather than keyword-presence in free-form text. Do **not** parse success from words like "recomendación" alone. Include explicit negative fixtures: ambiguous answer, contradictory answer, citation present but unsupported, stale requirement, abstention when sufficient evidence is present.
4. Validate that document evidence actually supports every completed task claim; memory citation IDs alone prove provenance, not semantic entailment.
5. For the original 3-session fixture, verify the last session truly completes the expected action; fail the demo if it merely states a limitation.
6. Preserve separate checks for security/citations, correctness, cost, latency and tool replay; a pass in one category must not imply others.
7. Save a new representative real-model run and failure log; keep earlier results unchanged for auditability.

**Done when:** The demo rejects the exact false positive in the stored Session C result and only passes when agent task outcome is correct.

### R08 — Complete comparative, public and adversarial evaluations [CRITICAL]

**Blueprint:** F8, Section 9, Phase 6.  
**Existing code/artifacts:** src/agent_context/evaluation.py; docs/ace/results/baseline-probe.json and validation.md; convomem_benchmark_converter/, test_conversation_generator/.

**Observed:** One real-model synthetic test compares full history, last three records, running summary, vector top 3, original retriever and ACE. **All six** got required language and option; ACE had a first-pass citation-policy failure. This does NOT establish superior task completion, lower total cost or production reliability.

**Required work (within original benchmark scope):**
1. Reuse existing evaluation code. First establish reproducibility: fixed scenario IDs, commit/model/prompt/embedding versions, token budgets, deterministic fixtures, judge schemas, expected actions and dataset splits.
2. Include multiple multi-session changed-requirement, conflicting/stale fact, project continuation, verified tool outcome, pending/replayed task, cross-scope, missing-information and source-injection scenarios.
3. Run original planned public benchmarks **when usable/license-accessible**: ConvoMem, LongMemEval, LoCoMo; task/state/continuity datasets such as MemoryArena, StateMemBench and handoff benchmarks if available and actually appropriate. Record exact source/version/split and skip unavailable benchmarks transparently; do not fabricate numbers.
4. Keep all six already-implemented baselines and equalize model, prompts, retrieved document access, tool budget, eval rubric and total context-token allowance. Report indexing/extraction/setup/summary/embedding costs separately **and** amortized end-to-end cost; do not compare ACE warm retrieval against a competitor's cold indexing.
5. Test real **task completion and next action**, current-state accuracy, stale-value leakage, allowed citations, answer grounding, abstention when evidence is insufficient, context recall, missing must-keep constraints, authorization failures and duplicate external action rate.
6. Report prompt and completion tokens, context render bytes vs real provider tokens, retrieval/assembly latency, total task latency, provider calls, cost when verifiable, p50/p95/p99 under appropriate sample sizes. Do not extrapolate from one trial.
7. Run repeated trials and confidence intervals where practical; include failed/invalid trials and openly report uncertainty.
8. Run **ablations of existing/planned behavior**: semantic vs lexical, recency, state, handoff, mandatory constraint retention, provenance, evidence/source selection, budget/noise, optional graph planner; don't build features exclusively for ablation.
9. Compare the same agent's real next-step action with and without ACE. If ACE does not improve outcomes or cost enough to justify overhead, **fix selection strategy** and document what failed instead of inventing a win.
10. Ensure the citations rubric matches the allowed source types (memory vs document) and separately scores source correctness; preserve the original probe's citation failure as a historical issue, rather than silently rewriting results.
11. Produce reproducible JSON/Markdown reports and a short limitations section for every evaluation.

**Done when:** There is a statistically and methodologically defensible report of ACE's benefits and trade-offs in multi-session agent tasks. A negative or mixed result is valid evidence, but the implementation must then be evaluated against the desired product outcome honestly.

### R09 — Complete production-critical security and privacy guarantees [CRITICAL FOR PRODUCTION]

**Blueprint:** F7/F8 and Phase 7.  
**Existing:** auth bindings, Principal, policy, PrivacyControls, GovernanceService, scoped graph source and local deployment.

**Already implemented, verify and skip:** authenticated actor distinction, private project binding, input-body caps, query-time scoped private retrieval, revocation replay fence, export, opt-out/derivation controls, primary-storage erasure, sanitized logs, fail-closed unsupported scopes.

**Outstanding requirements / validation gates:**
- **Critical security hygiene:** validation.md acknowledges a model credential previously appeared in committed history. Confirm credential owner and rotation/revocation; assume deleting from .env.example did not revoke it. Avoid printing or copying it while auditing.
- **Production multi-tenancy:** runtime.py currently enforces **one tenant/user trust partition per database deployment** because original concept-resolution lookups are global. If the target product must serve multiple tenants/users in shared infrastructure, implement and test tenant partitioning through concept resolution, embeddings, graph writes, all retrieval/evidence/handoff/export/query paths and caches. If deployment isolation is the explicitly selected production model, verify it operationally and document scalability/cost; never claim shared DB multi-tenancy.
- Test every endpoint against unauthorized cross-user/project access, including **event status, direct evidence, graph planner, historical retrieval, trace, export and erasure**; fail closed before data leaves the store.
- Verify trusted directory/team/organization membership writes remain separate from conversational claims and cannot be promoted to access grants.
- Add or validate rate limiting, quota boundaries, service identity, timeouts and audit trails required by the existing production specification. Do not expose the raw legacy graph/Streamlit demo as a public multi-tenant surface.
- Prompt-injection/context poisoning tests across imported turns, tool results and web snippets. Already existing span-trust and citation repair tests count as evidence **only when they exercise the live path**.
- Correct/revoke/erase semantics must be safe under concurrent worker claims, restore and retries. Existing primary erasure does not remove external backup/export copies; define an operator retention/legal-hold/restoration policy before promising a full erasure SLA.
- Confirm encryption in transit, production secrets management, least-privilege DB accounts, key rotation and secure log redaction. Local Compose security is not a public deployment guarantee.
- Run resource/exhaustion and denial-of-service tests for tokens, query work, events, revisions, large payloads, retry storms, long transactions and model/provider outages.
- Keep security results explicit: **zero observed unauthorized contexts across defined test matrices** is a test result, not a universal mathematical guarantee.

**Done when:** A documented threat model, negative tests, privacy erasure/recovery runbook and production identity/deployment proof meet the target's actual trust model.

### R10 — Complete distributed reliability, observability and operational deployment [HIGH FOR PRODUCTION]

**Blueprint:** F8/Section 11/Phase 7.  
**Existing:** Mongo lease/fencing token, idempotent graph writes, CI, Docker, local launcher, log sanitization, docs/ace/operations.md.

**Documented gaps:** distributed Neo4j write fencing, crash-during-driver-commit chaos testing, full backup restoration, TLS/identity production deployment, rate limits/quotas, SLOs and realistic load tests.

**Required verification/completion:**
1. Test simultaneous workers/competing claims, slow model requests beyond lease, process kill before/after graph write, Mongo commit failures, duplicate delivery, watermark reconciliation and dead-letter replay. Ensure a stale lease owner cannot write conflicting graph state even if Mongo fencing refuses its final watermark.
2. Confirm graph+Mongo consistency semantics and read-your-writes behavior: availability watermark must correspond to durable complete context, not merely worker success. Monitor lag between event record and context availability.
3. Validate idempotency for handoff versions, artifacts, correction/revocation, task actions and model retries; fail closed on unknown side-effect completion.
4. Confirm real telemetry: structured request/run/session/event IDs; stage timings and error counts; safe counters for token/model calls and selected/excluded context; privacy-safe tracing. Choose existing logging/observability facilities and avoid unnecessary infrastructure.
5. Establish measured latency, throughput, queue age, model-provider throughput and memory constraints under representative concurrency. Set realistic SLOs from these measurements; do not announce goals as achievements.
6. Confirm versioned schema, migration and rollback process for Neo4j/Mongo, and a reproducible staging release; no destructive migration in an untested release.
7. Verify backup/restore of both stores with consistent checkpoints, outbox and privacy fences (restored snapshots must not resurrect revoked/deleted content); document RPO/RTO capabilities actually achieved.
8. Secure deployments: TLS, secret injection, least-privilege service identities, resource caps, readiness, graceful shutdown, upgrade/rollback and isolation. Existing Compose/launcher remains for **development**.
9. Run full regression, integration, live-provider E2E, chaos/load smoke and CI after any deployment change.
10. Record unsupported OS/platform setup honestly. Do not expand the launcher to every OS unless this is necessary to deliver the originally promised supported environment.

**Done when:** Production readiness is backed by failure/recovery demonstrations and operational docs, not merely Docker build or 200 OK health endpoints.

### R11 — Documentation and scope truthfulness [HIGH; NO NEW FEATURES]

**Blueprint:** Sections 13–16.  
**Existing:** README.md, AGENTS.md, docs/ace/*, master blueprint, this file.

- Preserve the original Context Graph technical invariants; explain that new public ACE surfaces do not contradict the read-only **legacy retrieval tester**.
- The README currently contains original POC statements such as "retrieval is deliberately not implemented here" **after** the newer ACE introduction. Keep legacy description clearly labeled so new contributors do not mistake it for current ACE behavior.
- Correct any stale statement that the new repository is private if its GitHub visibility is public. Do not disclose sensitive configuration.
- Show actual API maturity and feature limitations: private-scope current retrieval, isolation assumptions, handoff semantics, source retrieval, optional search and stored results.
- Keep one source of truth for target design (master blueprint), one for outstanding work (this file) and one for completed verification (docs/ace/validation.md). Cross-link; don't maintain contradictory checklists.
- Update runbooks and README only when code/tests substantiate the changed capability.
- Resume claims: distinguish **existing implemented** vs **demonstrated E2E** vs **measured improvement** vs **production certified**. Do not invent metrics or cross-provider proof.

**Done when:** Someone opening the repo cold can accurately tell what works, what remains, how to reproduce tests, and what is not claimed.

---

## 3. Concrete known risks that must be re-verified before marking complete

### 3.1 Saved demo's false-positive task-success check

**Evidence:** docs/ace/results/live-demo.json, src/agent_context/demo_cli.py.

The stored Session C answer says the agent cannot deliver the final recommendation, despite having a brief describing two options. The success criteria include looking for Spanish words such as "recomendación" in the answer. **A refusal or incomplete answer can pass that check.** Correct this evaluator **only if current HEAD still has this issue**. Add a negative regression using the saved C answer. The model's real answer and the evaluator's judgment must be reviewed separately. A six-flag pass is not a complete task-success score.

### 3.2 ContextAssembler currently works on limited candidates

**Evidence:** src/agent_context/runtime.py instantiates ContextAssembler(Neo4jCandidateSource); retrieval.py query and assembly.py scorer. The candidate source can exclude relevant information before the scorer sees it; keyword overlap is not enough for semantic/long-task relevance. Reuse current graph semantic capabilities when filling this verified gap. Do not build an entirely new retriever by default.

### 3.3 Current constraints are ranked but not necessarily mandatory

**Evidence:** src/agent_context/retrieval.py marks preference/constraint/working style priority but not required; assembly.py may exclude non-required items for budget. Determine when a current, authoritative, user-approved constraint **must** be kept, and test impossible-budget behavior. Do not elevate every retrieved statement to a policy.

### 3.4 Handoff and current task context are not yet unified

**Evidence:** handoff.py and demo.py. Resume produces a historical handoff plus separate live bundle; host serializes both. A changed requirement in the current context may conflict with an older handoff. Validate reconciliation and make the **resulting next-step context** unambiguous, without inventing new agent tool types.

### 3.5 Search endpoint currently appears to be an assembly alias

**Evidence:** src/agent_context/api.py defines /v1/context/search by calling assemble. Verify current HEAD and correct this only if true. The intended behavior was scoped on-demand context/evidence search; this is completion of original F3/F4, not a new feature proposal.

### 3.6 Provider/database isolation and public repo credential risk

**Evidence:** src/agent_context/runtime.py singleton trust partition; docs/ace/validation.md notes credential exposure in prior history. These are release blockers for any multi-user production claim. Revoke affected secrets promptly, verify scope before deploying, and do not leak secrets in issue comments/tests/reports.

### 3.7 Evidence of value is still inconclusive

**Evidence:** docs/ace/results/baseline-probe.json. All six approaches got the task fields right in the only recorded example; ACE had a citation-rubric mismatch. Current first-pass comparison should be preserved and evaluated with a matching rubric; it does not establish quality or cost gains.

### 3.8 Existing fixes must not be regressed

**Evidence:** docs/ace/validation.md and tests/unit/test_project_binding.py, test_memory_grounding.py, test_bridge_trust.py (and live/integration tests). Existing trust-separated episodes, project ID binding, revocation replay prevention, stale citation checks, settings-source isolation and new-session UI state reset appear implemented. **Re-run and skip**; do not write these fixes again.

---

## 4. Required implementation order and dependencies (no speculative work)

| Order | Gate | Execute only if needed; skip when confirmed | Release evidence |
|---|---|---|---|
| 0 | **Current-state verification** | Re-read code, tests, blueprint and baseline; mark B01–B12 done/unverified, identify concrete failing examples | Audit ledger + exact commit SHA |
| 1 | **R07 already confirmed — SKIP** | Bounded demo oracle and negative regression verified; do not redo. Broader outcome evaluation stays in R08 | [Verified demo](docs/ace/results/live-demo-verified-20261104.json) and [negative proof](docs/ace/results/recommendation-oracle-negative-v2-20261104.json) |
| 2 | **R01 + R05: authorized retrieval parity** | Complete only missing candidate/evidence/scope/temporal behaviors | Real Neo4j scoped retrieval tests |
| 3 | **R02: context assembly correctness** | Integrate necessary retrieval and effective context, protect mandatory constraints | Actual context bundle and test traces |
| 4 | **R03 + R04: task state and handoff continuity** | Complete real next-step status and event feedback; avoid duplicate parallel state | Multi-session live E2E, negative retry/stale cases |
| 5 | **R06: independent host/model portability** | Prove existing HTTP/SDK can be used outside demo | Reproducible non-demo integration |
| 6 | **R08: controlled comparative evaluation** | Measure real task success, correctness and full costs; fix only problems exposed | Versioned benchmark report and ablations |
| 7 | **R09 + R10: security and production closure** | Tenant/isolation strategy, reliability, deletion/recovery and load gates | Threat model, tests, runbooks, deployment evidence |
| 8 | **R11: documentation and final acceptance** | Reconcile claims, archive proofs, update checklists | README + master blueprint + validation consistent |

**Rule:** Do not expand scope to make every phase look busy. If a task is confirmed complete, mark it done and go to the next incomplete item. If a new defect appears, fix it within its existing requirement rather than adding a new product feature.

---

## 5. Mandatory end-to-end acceptance suite: the product we originally wanted

These scenarios are required to prove **end-to-end behavior**, not to add features. Reuse existing test fixtures/data and provider/client interfaces whenever possible.

| ID | Scenario | Pass condition | Core requirements |
|---|---|---|---|
| E01 | User says preference in A; new session B asks a related question | Current value used; provenance available without replay of entire A | F1/F2/F3/F4 |
| E02 | User changes a prior preference/constraint | Current value wins, stale value excluded, historical provenance preserved | F2/F3/F4 |
| E03 | User changes a project requirement and cancels step | Resume uses newest requirement, avoids canceled step | F4/F5 |
| E04 | Agent completes verified tool action; crash then retry | No repeated side effect or unverified completed action | F1/F5/F8 |
| E05 | "Continue the project" with multiple unfinished steps | Correct next action, blockers, completed work and current artifacts returned | F4/F5 |
| E06 | Significant old fact vs many recent irrelevant facts | Relevant fact selected without excessive prompt noise | F3/F4 |
| E07 | Need evidence for a specific answer | Exact authorized source excerpt and citation; no fabricated sources | F3/F4 |
| E08 | Forbidden user/project/team or forged identity | Nothing unauthorized returned in candidate, bundle, trace, evidence or host prompt | F3/F7 |
| E09 | Expired/revoked data, permission change, stale cache | Data excluded immediately within documented consistency guarantees | F2/F7 |
| E10 | Untrusted tool/web source contains instructions | Content is data, not privileged instruction; no authority elevation | F7 |
| E11 | Context budget smaller than required constraints | Explicit safe failure, never silent truncation of must-keep conditions | F4 |
| E12 | Partial model/DB failure or duplicate/out-of-order event | Bounded retry/dead-letter, no duplicate context, visible status, safe recovery | F1/F8 |
| E13 | Handoff artifact changed after snapshot | Resume indicates unsafe/stale; reconciles before next external action | F5 |
| E14 | Multi-session independent agent/second compatible model | Existing SDK/API delivers same current context semantics with no graph coupling | F6 |
| E15 | User correction/erasure during in-flight event | Revocation fence/quarantine prevents reappearance; no foreign record erased | F7/F8 |
| E16 | Real final task recommendation in saved research scenario | Actual correct recommendation delivered, grounded citation, not just Spanish keywords | F5/F6/Section 9 |
| E17 | Multiple benchmark tasks and baseline variants | Comparative task/cost metrics reproducible with explicit limitations | Section 9 |
| E18 | Production restore after data correction/deletion | No resurrection after restore, consistency reconciled, observable outcome | F7/F8 |

**Test evidence must show:** actual input, expected state, observed result, exact code/model/config versions, used data stores, final assertion, cost/latency where relevant, and failure diagnostics. Use synthetic data and test-only credentials. No real personal/enterprise data in public artifacts.

---

## 6. Exact code map and permitted change strategy

| Current location | Primary responsibility | Guidance |
|---|---|---|
| src/context_graph/domain/* | Source messages, Episode spans, canonical context, scopes, lineage | **Preserve** data and identity invariants; extend only required contracts |
| src/context_graph/pipeline/* | Segmentation, gate, extraction, resolution, policy, lifecycle/writer | **Reuse**; fix only discovered correctness, trust or idempotency defect |
| src/context_graph/graph/* and ledger/* | Neo4j persistence and Mongo processing checkpoints | **Reuse**; add required safe query/scope/migration behavior; no DB swap |
| src/agent_context/contracts.py, events.py, event_store.py, bridge.py | Public event contract, auth semantics, durable event feedback | **Confirm existing**, then minimal task-state/consistency extension if R03/R04 proves necessary |
| src/agent_context/retrieval.py | Actual deployed authorized candidate source | **High-priority review** for recall, source diversity, scope/time/evidence and candidate starvation |
| src/agent_context/assembly.py | Core context selection, conflict/duplicate policy, budget packing | **High-priority review** for task awareness, mandatory context, evidence and relevance |
| src/agent_context/handoff.py, outcomes.py, artifacts.py | Versioned session/project handoff and verified progress | **Extend minimally** to align snapshot with current task state |
| src/agent_context/api.py, client.py | Agent-facing transport and SDK | **Keep**, correct semantics of search and missing actual integration only |
| src/agent_context/demo.py, demo_cli.py, evaluation.py | Research host, example task, baselines | **Fix outcome tests**, add fair scenarios and reporting using current harness |
| src/agent_context/privacy.py, governance.py, runtime.py | Privacy, erasure, auth/partition, API worker | **Preserve existing safety**, close release gates with tests |
| ui/*, compose.yaml, run.sh, .github/workflows/ci.yml | Developer interface, local setup, CI | **Keep**; fix only broken acceptance paths or production requirements |
| docs/ace/*, README.md, AGENTS.md, master blueprint, this file | Product direction and evidence | **Reconcile after verification**, not as a substitute for actual tests |

Do not rename context_graph imports or graph labels merely to call the product "context". A narrow public facade is already present. The implementation should emphasize context engineering, not graph traversal. If code already uses a fitting interface, extend it rather than creating a second copy.

---

## 7. Live evidence ledger — update as you work

### R01/R05 retrieval increment — 2026-11-05

Inspected and fast-forwarded to the user's documentation-only update `6c76b13`.
Pre-change focused assembly/API/retrieval/governance checks: **26 passed** with
real MongoDB and Neo4j. Existing private scope, lifecycle, packing and R07
behavior remain **CONFIRMED DONE — SKIP**. A new HTTP regression reproduced the
search alias defect (422 without an assembly budget); a real evidence regression
reproduced missing span/speaker/trust fields. Only these gaps and the documented
semantic/effective-history path were extended.

**CONFIRMED DONE within this increment:**
- Distinct, bounded, paginated search without prompt packing; SDK search/evidence
  methods; current authorization and privacy checks on every page; stale cursors
  rejected rather than silently skipping results.
- Native semantic scoring using the existing provider and stored vectors,
  authorized lexical/semantic ranking before LIMIT, and semantic signal consumed
  by the actual assembler. Runtime and Compose now wire query embeddings; NIM
  query/passage modes are distinct. No global private ANN result window, new
  index service, planner or LLM reranker.
- Explicit effective-time historical search, with supersession/validity and
  present-day revocation fences. History is labeled and not used as current
  assembly instructions.
- Bounded source excerpts with original speaker/role, exact message offsets and
  per-span source trust. Owned withdrawn evidence remains inspectable with a
  non-current label; search still excludes it. Episodes must belong to the
  principal's session participation path.
- Competing effective single-valued graph values remain a conflict even when
  the candidate cap would otherwise hide the second value.

Evidence: `tests/unit/test_context_search.py`, provider query-mode tests,
`tests/integration/test_ace_retrieval.py`, API and governance tests. The first
full regression after search/history/semantic/evidence changes passed **474
tests, one legacy live-UI test deselected**, Pyright clean. Subsequent conflict
guard validation passed **29 focused tests**; final regression evidence follows
below. The live isolated API/worker/NVIDIA report is
[retrieval-live-20261105.json](docs/ace/results/retrieval-live-20261105.json):
record → availability → new-session semantic search → exact evidence → packed
context, all five assertions passed. Source hashes identify the exercised build;
one synthetic run is not a recall benchmark or latency SLO.

**At this checkpoint, still PARTIAL:** R01/R05 as whole requirements. Task-state
candidates were subsequently wired and verified in the increment below; shared directory/TASK graph parity is still
fail-closed under the selected physically isolated private deployment. Large
partition query cost and benchmark ablations remain unmeasured. No migration of
previously mis-scoped legacy data is implied. Search's bounded candidate window
and effective-time semantics are documented in `docs/ace/development.md`.

Initial assessments are anchored to the inspected commit. Updated rows below
claim completion only within the explicitly verified boundaries and linked
evidence. Open production/whole-product gates remain open.

### R02/R03/R04 task-state increment — verified 2026-11-05

Before changes, **23 handoff/host/grounding tests passed**: existing version CAS,
artifact/outcome verification and replay were **CONFIRMED DONE — SKIP**. Source
inspection and a missing-module acceptance test confirmed there was no canonical
task-state path. A separate trace regression confirmed missing selected reasons
and scope metadata. Changes reuse `HandoffService`'s bounded atomic revisions in
the same collection, with a server-owned project/task ID, rather than a second
state database or workflow executor.

Current implementation: typed `WorkState` shared by handoffs and current tasks;
authenticated event causation; user-approved constraints; agent progress restricted
to verified outcomes; correction grants; completed-action retention; explicit
cancellations/dependencies; current state as an atomic mandatory TASK section in
the deployed assembler. New API/SDK task operations, scope/selection trace and
read-your-writes watermark are wired. Resume compares the canonical task version,
returns current context, blocks old requirements/changed artifacts, and requires
a matching handoff before continuing. Legacy snapshots remain usable with their
existing weaker semantics; additive fields preserve old idempotency hashes.

Focused state/HTTP verification passes **8 real-Mongo tests**, including
CAS races, forged agent requirements, unproven completion, old-request replay,
tiny budgets, stale/reconciled handoffs and changed artifacts. Full regression:
**480 passed, two opt-in live tests skipped, one legacy live-UI test deselected
(16.37s)**; Pyright zero errors/warnings. Separately:

- [continuation-c404a96f34ed.json](docs/ace/results/continuation-c404a96f34ed.json)
  passed seven actual workflow checks against the isolated deployed API/worker.
  `nvidia/nemotron-3.5-bolt-e4b` and
  `nvidia/nemotron-3.5-lightning-30b-a3b` both selected B's current Spanish
  requirement, preserved X/Y completion IDs, excluded the cancelled step and
  chose the correct remaining audit. The SDK/HTTP-only host executed the audit,
  recovered the durable receipt on retry (one execution), and recorded verified
  progress. Interrupted unknown outcomes and expired handoffs were refused.
  Pytest passed in 55.00s; report elapsed time is recorded separately.
- [artifact-check-2eed7ca74225.json](docs/ace/results/artifact-check-2eed7ca74225.json)
  passed real artifact registry → changed hash → current state/bundle warning →
  unsafe resume in 9.09s. It did not repeat the model workflow.
- [continuation-c78aba3c5cbf.json](docs/ace/results/continuation-c78aba3c5cbf.json)
  preserves the first failed run: Mistral's catalogue entry returned an account
  404 after the primary model passed. It is explicitly `completed=false`;
  preliminary successful checks are not overall task completion. Its build-hash
  annotation distinguishes the actual runtime tree from later checkout changes.

**CONFIRMED DONE — SKIP:** the bounded private current-state path, mandatory
atomic packing, accepted requirement/cancellation updates, recorded-outcome
retention, stale-to-reconciled resume, exact artifact verification and independent
SDK/HTTP host/two-model integration. Current state and handoffs reuse one store,
one work contract and existing event/outcome/artifact/privacy components. No UI
expansion, new model framework or second event pipeline. Legacy hash compatibility
is regression-tested; no migration rewrites old history.

**Still open:** broad R08 quality/utility evidence; genuine cross-provider
validation; unbounded task-history requirements (the explicit existing revision/
list quotas still apply); arbitrary external exactly-once/crash behavior;
production fencing/erasure/restore/load gates. Task API assertions are deliberate
authenticated commands with event causation, not automatic LLM-created authority.
The console retains its existing research flow; generic task controls use the
documented API/SDK.

| Requirement | Starting status | Verified code path / test / report / commit | Next decision |
|---|---|---|---|
| B01–B03 Core ingestion/lifecycle | CONFIRMED DONE (existing invariants) | e55fb5a: original unit + in-memory ingestion tests and real Neo4j/Mongo store tests passed in baseline; pipeline/graph/ledger call paths preserved | SKIP implementation; broader extraction-quality benchmarks remain R08 |
| B04 Events and worker | CONFIRMED DONE (bounded ordered-stream base) | e55fb5a: contracts/events → MongoEventStore → EventWorker → existing ingestion; real event/runtime tests passed | SKIP base; retain R04/R10 task and distributed gates |
| B05 Private scope binding | CONFIRMED DONE | e55fb5a: trusted stream → bridge metadata → WriterPolicy → scoped Neo4j query; project-binding unit and real retrieval tests passed | SKIP this fix; richer retrieval remains R01/R05 |
| B06 Basic assembler | CONFIRMED DONE (basic packing) | e55fb5a: runtime constructs ContextAssembler; assembly budget/conflict/dedup/source tests and HTTP tests passed | SKIP basic parts; task-aware sources remain R02 |
| B07 Handoff/artifact base | CONFIRMED DONE (snapshot primitives) | e55fb5a: HandoffService/ArtifactStore/EventOutcomeVerifier; real handoff and governance tests passed | SKIP base; current-state reconciliation remains R03 |
| B08 API/SDK | CONFIRMED DONE (existing base routes) | e55fb5a: FastAPI + AgentContextClient exercised by real API/research-host tests | SKIP base; search route semantics remain R01 |
| B09 Research demo/citation handling | CONFIRMED DONE (source/replay protocol); PARTIAL (outcomes) | e55fb5a: memory-grounding unit and real research-host tests passed; saved false-positive outcome remains reproducible from oracle code | SKIP citations/replay implementation; fix R07 only |
| B10 Primary privacy controls | CONFIRMED DONE (documented primary-storage scope) | e55fb5a: real revocation/export/quarantine/erasure tests passed | SKIP base; external backup/restore/operator gates remain R09/R10 |
| B11 Local deployment/CI | CONFIRMED DONE (existing Linux local path) | e55fb5a baseline exposed fake-readiness race; corrected test handshake then 462 passed, one live legacy UI test deselected. Fresh isolated Compose API/worker run reached real model answers | SKIP production launcher; native macOS/WSL install remains unverified |
| B12 Converter/generator and initial benchmark | CONFIRMED DONE (existing tools only); PARTIAL (evaluation breadth) | e55fb5a converter/generator unit tests passed; saved six-baseline report inspected | SKIP converter/generator; no comparative-superiority claim |
| R01 Relevant candidate retrieval | CONFIRMED DONE for tested private sources; broader quality/load PARTIAL | `8ed65b8`; actual runtime lexical/semantic/history/search/evidence plus required task source; real Neo4j candidate-pressure/conflict tests and live reports above | SKIP these paths; measure breadth/cost under R08/R10; shared scope remains fail-closed |
| R02 Task-aware assembly | CONFIRMED DONE for bounded current-task contract; broader utility PARTIAL | `assembly.py` + required `TaskCandidateSource`; atomic required state, constraints, reasons/scope/watermark, source/budget/conflict tests; independent two-model next-step proof | SKIP verified packing/state work; evaluate comparative utility |
| R03 Live task state + coherent resume | CONFIRMED DONE for bounded recorded-outcome workflow | `TaskStateService` → existing snapshot CAS; SDK/HTTP/live continuation and changed-artifact reports above | SKIP rebuilding state; external crash/transaction guarantees remain R10 |
| R04 Event feedback/task transitions | CONFIRMED DONE for explicit state projection with real event causation | Existing event kinds reused; authenticated user/agent source matching, availability gate, verified outcomes, CAS/retry tests and real worker path | SKIP new event kinds; distributed failure closure remains R10 |
| R05 Scope/temporal parity | CONFIRMED DONE for private memory/current operational TASK; broader shared scope PARTIAL | Real current/as-of/supersession/revocation tests; bound task/project and negative tenant/user/project checks | Preserve chosen physical partition/fail-closed shared scopes; no legacy graph-TASK migration claimed |
| R06 Independent agent integration | CONFIRMED DONE (SDK/HTTP-only host and two NVIDIA models); cross-provider UNVERIFIED | `test_ace_continuation_live.py`, `continuation-c404a96f34ed.json`; failed alternate Mistral result retained | Do not add adapters; prove a real second provider when configured |
| R07 Real outcome evaluation | CONFIRMED DONE (existing bounded research task) | Source checkpoint 9ad2d52; live-demo-verified-20261104.json passes all per-session typed/quote/source checks; recommendation-oracle-negative-v2-20261104.json rejects the exact preserved refusal; unit negative matrix passes | SKIP rebuilding oracle; same-model-judge limits and broader R08 benchmark gates remain explicit |
| R08 Comparative benchmarks | Pipeline CONFIRMED DONE within fixture-tested bounds; measured results PARTIAL | Reusable pinned acquisition/adapters, real ACE/legacy integration, six methods, controlled experiments, checkpointing, scoring and stage accounting; see benchmark guide and latest validation | Full public runs, official scoring, ablations and real quality/cost/scale conclusions remain unmeasured; do not run them without authorization |
| R09 Production security/privacy | PARTIAL | To fill | Rotation/isolation/negative gates |
| R10 Production ops/chaos/recovery | PARTIAL | To fill | Verify failures/restore/load |
| R11 Documentation consistency | PARTIAL | To fill | Correct after code verification |

For each finished item, append a compact evidence note:

### Audit checkpoint — 2026-11-04, baseline e55fb5a

Traced intake/auth → event stream/outbox → worker/bridge → original ingestion →
scoped candidates → assembler → SDK/host, plus handoff/artifact and primary
privacy paths. The latest upstream commit adds only this checklist; implementation
matches the inspected UI revision. No existing base component is being rebuilt.

Exact pre-change command:

```sh
CG_INTEGRATION=1 CG_NEO4J__URI=bolt://127.0.0.1:7690 CG_MONGO__DATABASE=ace_remaining_baseline UV_CACHE_DIR=/workspace/.cache/uv uv run --frozen pytest -k 'not test_the_ui_runs_the_tool_and_shows_the_result' -q
UV_CACHE_DIR=/workspace/.cache/uv uv run --frozen pyright
```

Observed: **450 passed, 1 failed, 1 deselected**; Pyright zero errors/warnings.
The failure is `test_startup_order_and_once_only_demo`: fake curl always returns
success, so the background fake UI can log after the demo. Real launcher code
does wait for actual UI health; this is a test-double race, not evidence that
production startup skips readiness. Real integration used disposable Neo4j on
7690 and test-only Mongo databases, separate from the live-model fixture.

R07's old saved result is preserved: its session C refusal satisfies the Spanish
keyword check. A new baseline live run uses a fresh Compose project
`ace-remaining-audit`, private stores and synthetic `ace-live/research-user`
identities. Its output will be recorded separately from old reports. The first
attempt reached a harness connection error because editable-package dotenv lookup
found source-checkout settings; the rerun explicitly supplies isolated settings.

Production credential rotation, external backups, alternate-provider credentials,
native macOS/WSL setup and production TLS/identity remain **UNVERIFIED**; local
unit/integration success does not close those gates. PDF ingestion, new frameworks,
UI styling and optional adapter expansion are **NOT REQUIRED** in this pass.

R07 unchanged-HEAD live rerun: report `0755e1440c21.json` now delivers Option A
in the final Spanish response, so the historical refusal is **not** asserted to
reproduce on the current model. The run correctly fails its document-citation
flag because B/C cite only memory despite reading the brief. The stale keyword
oracle still accepts the old saved refusal. The minimal changes are typed,
quoted output assessment plus the existing host's `require_sources` setting for
this document-based demo. Same-model judging is disclosed and source/quote checks
are independent; no universal semantic-accuracy claim is made.

GitHub metadata currently reports `private: false` (2026-11-04). Documentation
must not call the repository private. Previously exposed-key revocation remains
UNVERIFIED pending the credential owner's response; repository visibility is not
changed by this audit.

Post-change preserved regression: **462 passed, 1 deselected in 14.02 s** using
the same command with `CG_MONGO__DATABASE=ace_remaining_regression`. The launcher
double now acknowledges actual fake-UI readiness; `run.sh` is unchanged. R07 unit
cases reject the saved false positive, abstained/ambiguous/contradictory judgments,
wrong options/language, fabricated/incomplete quotes and memory-only support for
document claims. Strict Pyright is clean. A source checkpoint precedes the next
live run so the report can record the precise implementation revision.

~~~text
Requirement:
Checked at commit:
Date:
Code functions/call paths:
Tests executed (exact command):
Real service/provider/database?:
Observed pass result or reproducer:
Status: CONFIRMED DONE / PARTIAL / MISSING / UNVERIFIED / NOT REQUIRED
Change (if any):
Commit/PR:
Migration/compatibility impact:
Residual limitations:
Skip justification (if already done):
~~~

**Do not delete past failed benchmark data or mutate old results to make them appear passing.** Maintain reproducible before/after runs.

---

### Verified milestone — R07 and the reproduced R01 literal-recall defect

- **R07 source checkpoint:** `9ad2d52`. Report:
  [live-demo-verified-20261104.json](docs/ace/results/live-demo-verified-20261104.json).
  Real isolated Mongo/Neo4j/API/worker plus NVIDIA host/verifier; final Option A
  recommendation delivered in Spanish, English superseded, verified reads and
  document citations present, cached replay. All per-session quote/source/choice/
  language checks passed. Recorded elapsed time 46.726 s is one observation, not
  an SLO or comparative benefit.
- **Negative real-model proof:**
  [recommendation-oracle-negative-v2-20261104.json](docs/ace/results/recommendation-oracle-negative-v2-20261104.json)
  classifies the preserved false-positive refusal as abstained and rejects it.
  The original report is unchanged. The v1 verifier's failed format/language
  trial is preserved in `docs/ace/results/demo-oracle-v1-failure-20261104.json`;
  the unchanged-HEAD citation failure is preserved separately as
  `docs/ace/results/demo-audit-baseline-20261104.json`. Failed trials are not
  dropped from the evidence.
- **Minimal R07 change:** use existing `require_sources` mode for this document
  demo and replace the weak success oracle. Completion and answer-only language
  assessments are separate typed calls; deterministic checks validate actual
  quoted choice, exact supporting document facts and source ID. Host/verifier
  usage is separate. Worker ingestion billing is not available; total cost and
  universal semantic correctness are not claimed.
- **R01 reproducer:**
  `CG_INTEGRATION=1 .venv/bin/pytest tests/integration/test_ace_retrieval.py::test_older_relevant_decision_survives_recent_irrelevant_candidate_pressure -q`
  failed on the old query, then passed after a narrow fix to the existing source.
  Query words are normalized consistently with assembly, matched only inside
  authorized valid rows, and ranked before LIMIT. No new index/service/database
  or model call is introduced. Assembly policy version is now `ace-assembly-v2`.
  This proves literal-recall behavior, **not** complete hybrid/semantic retrieval.
- **Post-change regression:** 463 passed, one unrelated legacy live-model UI
  case deselected, in 18.82 s; strict Pyright zero errors/warnings. Command uses
  `CG_MONGO__DATABASE=ace_remaining_final` with the previously recorded options.
- **Compatibility:** no data migration or public API field/path removal. Old
  demo reports remain readable and intact; request `./run.sh --demo` once after
  updating if an old launcher success marker would otherwise skip the new oracle.
- **Credentials:** the owner supplied a replacement key; it is stored only in
  ignored mode-0600 local configuration and was used successfully by the isolated
  worker and host. Revocation of the previously exposed key is still UNVERIFIED.
- **Next ordered gate:** finish the unproven parts of R01/R05, then R02 and R03.
  Current task projection, richer evidence/search, historical/shared/task parity,
  independent host/provider validation, broad benchmarks and production gates are
  **not** marked complete by this milestone. No optional PDF/framework/UI work.

## 8. Reproducibility: first commands and verification sequence

At the start of a coding session, inspect the **actual** repo state, prerequisites, environment and credentials. Use the repository's own runbooks; examples below are not guaranteed to work on every host.

~~~sh
git status --short
git rev-parse HEAD
uv sync --frozen
uv run --frozen pyright
uv run --frozen pytest

# Only against explicitly disposable integration databases:
CG_INTEGRATION=1 CG_NEO4J__URI=bolt://127.0.0.1:7690   CG_MONGO__DATABASE=ace_baseline_test uv run --frozen pytest

# Dev stack, if configured with safe ignored credentials:
./run.sh --skip-demo

# Configured live-provider E2E example:
./run.sh --demo

# Existing comparative harness, given a valid saved demo output:
uv run --frozen agent-context-evaluate data/ace_demo/<run-id>.json
~~~

Follow docs/ace/operations.md for ports, isolation, credentials, warnings and cleanup. Do not run integration suites against any production user data; some suites use different embedding dimensions and must not share the same index. Do not put tokens, production data or secrets in logs, output files or Git.

**Test levels, in order:** static read and call trace → deterministic unit/contract regression → real stores integration → live provider and API/worker/agent multi-session E2E → repeatable comparative benchmarks → load/chaos/security → deployment/restore. A test may be skipped for lack of a model/service credential; record **UNVERIFIED**, not falsely green or missing.

---

## 9. Final Definition of Done — no new features, just the original goal

The overall project can be called **complete relative to the master blueprint** only when all of these are verified:

- [ ] Existing Context Graph extraction, exact-source evidence, semantic resolution, scope and lifecycle invariants remain preserved.
- [ ] User/agent/tool events are authenticated, safely queued, consumed, recoverable and reflected in new-session context without manual ingestion.
- [ ] Current effective context and project/task state are retrievable without stale/unauthorized/missing-required facts.
- [ ] Adaptive context selection combines relevant current user/project knowledge, evidence, verified progress and constraints into a bounded agent-step bundle.
- [ ] Versioned handoffs and resume use **current verified task state**, avoid old requirements and repeat no completed action.
- [ ] The independent public API/SDK works for a compatible agent/model without graph coupling.
- [ ] The demo proves **actual task completion**, not just language/citation/keyword checks.
- [ ] Comparative evaluation across multiple scenarios and baselines reports accuracy, continuity, cost, latency, uncertainty and failures honestly.
- [ ] Production identity/privacy/scope/isolation, operational failure recovery and erasure/restore obligations satisfy the chosen deployment model.
- [ ] CI, Pyright, live system integration, threat/security tests, failure/load tests and migration/recovery evidence meet the declared release gates.
- [ ] README, validation report, blueprint and this file agree on what exists, what was verified and what remains out of scope.

**If a requirement is already satisfied:** confirm with evidence → mark **CONFIRMED DONE** → **SKIP**.  
**If only partially satisfied:** implement the minimum correct missing behavior, test it, and stop.  
**If genuinely optional/out of scope:** mark **NOT REQUIRED**; do not turn it into a new feature.  
**If blocked by unavailable tests or credentials:** mark **UNVERIFIED** and record how to verify; do not claim finished.

---

## 10. Ready-to-use instruction for a new chat / coding agent

> Work in **praveen-solanki/Agent-Context-Engine**, not the original Context-Graph repository. Read REMAINING_WORK.md, CONTEXT_ENGINE_MASTER_BLUEPRINT.md, AGENTS.md, README.md, docs/ace/architecture.md and docs/ace/validation.md, then inspect the relevant current source/tests. **The product scope is frozen: finish only the originally planned Agent Context Engine; introduce no unrelated new features.** Begin by verifying each existing capability, with a source-level call-path trace and meaningful tests. If anything is already implemented and passes, mark it CONFIRMED DONE with code/test evidence and SKIP it entirely. For partial gaps, fix only missing correctness/integration/evaluation/production behavior, preserving all current features and tests. Prioritize real context selection and task-aware assembly, current-state handoff continuity, genuine end-to-end task success, rigorous benchmarks, and original production gates. Document exact tests, live outputs, changed files, compatibility and remaining limitations. Update REMAINING_WORK.md and the master blueprint after each verified milestone. Do not claim a task complete merely because the README or an old report says so; do not create new architectures, frameworks or graph products.

**Ultimate criterion:** Not "more AI features"; **a fully validated, reusable context engine whose timely, authorized, evidence-backed context helps long-running agents complete real work across sessions and can be operated safely under the documented conditions.**

### 2026-11-06 — requested design skills and UI refinement

CONFIRMED DONE within focused verification: both requested Apple design skills are
installed locally with a pinned installer; presentation/theme now use a consistent
system type scale, blue/graphite palette, distinct context inspector, mobile stacking,
visible focus and motion/contrast preference handling. All 28 workspace UI tests
pass; presentation Pyright is clean. Chromium checked 1440px/390px and accessibility
preferences. See [design evidence and limits](docs/ace/ui-design.md). No backend,
benchmark or production-readiness change is claimed.
