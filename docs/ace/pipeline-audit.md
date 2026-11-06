# Pipeline integrity audit — 6 November 2026

Baseline: `0689c5a`. Scope: preserve the Agent Context Engine's original evidence,
identity, lifecycle and continuation contracts while applying the useful parts of
[the research report](../../outputs/agent-context-engine-research.md). This is a
bounded adversarial audit and improvement increment, not a bug-free certification.

## Method and ownership

Six independent slices inspected actual code and existing checks before editing:
ingestion, retrieval/assembly, provider boundaries, state/privacy, workspace/host,
and benchmarks. A coordinating slice reviewed integration, logging and tooling.
Each verified defect has a reproducing input/interleaving and a regression. A passing
fixture is workflow evidence, not measured semantic accuracy. Only new/affected
checks ran; no full suite, public dataset evaluation or live provider requests.

The audit follows data through intake → event/outbox → episode/chunk → extraction
proposal → governed graph context → retrieval → assembly → host answer → task/handoff.
It checks partial failure and invalid output at boundaries, not only happy paths.

## Reproduced defects and changes

| Boundary | Failure and resulting behavior | Executable protection |
| --- | --- | --- |
| Chunking | Whole-episode token density hid oversized Unicode/code chunks. Each temporary chunk is now individually bounded while exact character coverage is preserved; an impossible character budget fails explicitly. | `tests/unit/test_ingestion_adversarial.py` |
| Batch completion | A successful chunk acknowledged an episode whose other chunk failed, permanently skipping work. Completion now requires all batches for that episode to succeed; retry retains the failed work. | Same file; real in-memory pipeline and first/last chunk failures |
| Extraction budget | Full-prompt counts were compared against an already-reserved content allowance, and large instructions could bypass checks for short input. Full request allowance is now used. | Same file; exact boundary/count cases |
| Embedding response | Duplicate/missing indices and invalid vectors could be misassociated or fail unpredictably. Exact mapping, dimensions, numeric/finite/nonzero values and malformed envelopes are validated. | `tests/unit/test_provider_adversarial.py` |
| Chat response/repair | Bad envelopes raised untyped exceptions; errors echoed upstream bodies; repair omitted the failed response. Boundaries now fail with sanitized provider errors and repair sees the output being repaired. | Same file |
| Retry | Retry-After was ignored and jitter exceeded the local ceiling. Seconds/date hints are respected; a hint above the configured maximum stops local retries rather than retrying too early. Cancellation propagates. | Same file; mocked waits/HTTP |
| Provider selection | Substring matching could classify an unrelated endpoint as NVIDIA. Payload detection now checks the actual hostname. | Same file |
| Retrieval scope | An explicitly project-bound USER candidate could pass the assembler's defensive scope check. Both search and assembly now enforce its binding; actual personal context remains shared. | `tests/unit/test_retrieval_adversarial.py` |
| Retrieval time | Future observations could suppress current facts as conflicts or occupy candidate limits. Observation-time restrictions apply before LIMIT and to competing values. | Same unit file and `tests/integration/test_ace_retrieval.py` |
| Lifecycle disagreement | An inactive/revoked duplicate was filtered before comparing sources, allowing an active copy to escape. Authorized contradictory copies now fail closed. | Retrieval adversarial cases, both source orders |
| Web evidence URLs | Known signed/cloud credential parameters and OAuth fragments passed validation. Those credential forms are rejected before publishing snapshots. | Retrieval adversarial cases; ordinary source URLs preserved |
| Privacy reads | Event, artifact and handoff reads could return a captured value after quarantine began during the read. A final privacy fence now denies it. | `tests/integration/test_state_adversarial.py`, real Mongo interleavings |
| Privacy writes | A write delayed past purge could recreate primary content. Post-write quarantine checks remove only that owner's late collection records; idempotent-return paths recheck privacy. | Same file; foreign owners retained |
| Directory hints | Revocation during goal-hint lookup could expose the old goal to routing. Changed privacy revision now rejects the result. | `tests/unit/test_workspace_adversarial.py` |
| Restored history | Unknown/non-user/future causation could attach answers to unrelated user messages and hide pending work. Explicit links now require an earlier user/correction; legacy absent-causation fallback is preserved. | Same file |
| Host retries | Same ID/text with a changed correction kind/target or project binding could replay different work. Retry identity now checks the full relevant contract before side effects. | Same file and affected host integration |
| ConvoMem adapter | Premixed outer-only history crashed through eager evaluation of a missing inner key. Explicit source selection preserves outer distractors. | `tests/unit/test_benchmark_adversarial.py` |
| Benchmark inputs | Blank question/reference strings admitted meaningless scores. Preparation now rejects them. | Same file |
| Benchmark fixture | Scripted extraction quoted a rendering prefix rather than original source text. The fixture now follows the actual evidence contract; production validation remains strict. | Same file plus four-format/six-method real-store workflow |
| Failure accounting | Retrieval evidence disappeared when answer generation failed. It is computed before generation; reports separately count context, ingestion, answering and judging failures. | Same file; old artifacts remain readable |
| Logging | Nested private fields/credentials escaped shallow redaction; metadata could replace envelope fields. Redaction is recursive, case-normalized and bounded; reserved envelope fields remain authoritative. | `tests/unit/test_observability_adversarial.py` |

## Research benefits implemented

- **Impact-aware, minimal changes:** selected Ponytail implementation/review/audit
  and ECC change-impact, regression, verification and bounded optimization guidance.
  `./scripts/install-skills.sh engineering` installs the seven instruction-only
  skills locally at pinned commits. No observer, hook runtime, MCP server, hosted
  service, alternate memory backend or automatic code-changing loop is enabled.
  The original design installer remains compatible through a shared installer.
- **Stage diagnosis:** context-local correlation isolates concurrent requests;
  server request IDs, route-template timings and stage outcomes identify API work.
  Hashed stream/event IDs link intake to worker processing without raw source text.
  Worker timings distinguish thrown errors from returned failed ingestion reports.
  Uvicorn raw URL access logs are disabled in the supplied runtime in favor of the
  structured route-template event. This is local structured telemetry, not a
  deployed distributed tracing/dashboard service or a global quota mechanism.
- **Separate retrieval and answer assessment:** existing benchmark reports add
  evidence precision when exact mappings and nonempty gold labels exist, and
  phase/error counters. Missing evidence labels remain null. These labels measure
  overlap, not semantic support or universal relevance; gold annotations may be incomplete.
- **Adversarial scenarios:** Unicode density, failed chunk retries, temporal
  conflicts, competing lifecycle copies, malformed provider envelopes, rate hints,
  privacy interleavings, forged causation, changed retry payloads, fixture/live
  contract drift and missing measurement metadata now have explicit regressions.

## Verified existing behavior: preserve and skip

The audit preserves typed records, exact source spans, source validation, scoped
Neo4j retrieval, canonical task CAS, atomic mandatory packing, Mongo outbox/leases,
replay, immutable streams, existing APIs/SDK, evidence controls and the six-method
benchmark architecture. In particular, malformed/missing embedding usage metadata
already remains unknown without discarding valid vectors; six additional tests
confirm this. Explicit zero usage remains distinct. No production fix was needed.

## Deliberately not added

Redis/Kafka, another memory store, generic agent orchestration, automatic learned
policy, blind prompt caching, smaller-model routing and unconditional iterative
retrieval/reranking have no demonstrated benefit for this workload. They remain
experiments, not defaults. Existing retrieval and cache logic is reused. Relevant
ECC examples are guidance, not provider-specific NVIDIA compatibility evidence.
Full-suite/coverage defaults in optional skills do not override the user's scoped
verification instruction.

## Evidence and remaining gaps

See the [machine-readable verification record](results/pipeline-integrity-20261106.json)
and [validation ledger](validation.md) for final scoped counts and commands.
The tiny real-store benchmark matrix uses mocked models; it proves wiring, scoring,
reporting and resume, not real dataset accuracy or superiority over baselines.
Earlier live-model observations are separate historical evidence and were not rerun.

Open gates remain: statistically reliable real-data evaluation; cross-provider
quality; global RPM/quotas; complete capture/stale/scope-error metrics where gold
labels are missing; shared-database multi-tenancy; distributed graph write fencing;
crash-during-commit and backup/restore proof; external backup erasure; deployment
security/identity and historically exposed credential revocation confirmation.
Post-read/write checks reduce defined races but are not cross-database transactions
or a universal guarantee against crashes between every operation. Known signed URL
forms are blocked, not arbitrary secret detection. No latency/accuracy improvement
percentage or zero-bug claim follows from these checks.
