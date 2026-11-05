# Reusable memory benchmark pipeline

The `agent-context-benchmark` command acquires pinned data, prepares QA cases,
ingests history through ACE, prepares comparison contexts, generates answers,
scores them and writes reproducible reports. It reuses the production API,
SDK, outbox, worker, ingestion pipeline, assembler, legacy retriever and existing
provider/retry/metering components. It does not change the UI or launch a second
demo application. The older `agent-context-evaluate` synthetic probe is preserved.

**Verification is fixture-based. No full public benchmark or paid model
evaluation was run for this implementation.** Test-generated answers and token
counts are mocked; they are workflow evidence, not measured model quality.

## Supported inputs

| Dataset | Input and acquisition | Evaluation support |
| --- | --- | --- |
| LongMemEval cleaned | Pinned Hugging Face oracle, s and m JSON arrays | Native questions, references, categories, abstention IDs, question/session dates and turn/session evidence |
| ConvoMem | Pinned Hugging Face tree/pattern or local files/directories | Native `evidence_items` and premixed `evidenceItems`; preserves outer distractor conversations and QA/evidence labels |
| LoCoMo | Pinned `locomo10.json`, or a local copy | Native conversation sessions, QA categories/evidence, supplied image captions and category-5 abstention; no image fetching or vision calls |
| Normalized QA/next-action cases | Versioned local JSON/JSONL or pinned HTTPS files | Same ingestion/baselines/scoring for supplied histories, questions, expected answers and evidence |
| MemoryArena, StateMemBench, handoff continuity datasets named in the blueprint | No verified native dataset/schema/license integration is asserted | A licensed offline QA/next-action export can use the normalized schema. Interactive environment execution and official task-success scoring are not implemented by this QA pipeline |

The checked-in [public configuration](../../benchmarks/configs/public.json)
contains five dataset IDs: `longmemeval-oracle`, `longmemeval-s`,
`longmemeval-m`, `convomem`, `locomo`. The exact upstream commits are recorded in
that file. LongMemEval's dataset card advertises MIT. ConvoMem and LoCoMo advertise
**CC-BY-NC-4.0**; use their data under those terms. Data is not redistributed here.
LoCoMo's actual upstream files are `README.MD` and `LICENSE.txt`; earlier 404s for
different filenames did not establish unavailability.

The existing 60-session `data/convomem_demo/` conversion drops QA ground truth.
It remains valid ingestion input, **not** a substitute for the raw QA benchmark.
The original converter is unchanged.

## Install and inspect without model calls

From this repository:

```sh
uv sync --frozen
uv run --frozen agent-context-benchmark plan --config benchmarks/configs/public.json --dataset longmemeval-s --limit 3
uv run --frozen agent-context-benchmark schema > /tmp/ace-benchmark.schema.json
```

`plan` and `run` without `--execute` make no model, storage or acquisition calls.
The plan shows selection, methods, byte allowance and the request ceiling; it
does not invent a dollar estimate. Paths in JSON configuration resolve relative
to that configuration file, not the current working directory.

## Acquire and prepare

```sh
uv run --frozen agent-context-benchmark acquire --config benchmarks/configs/public.json --dataset longmemeval-oracle
uv run --frozen agent-context-benchmark prepare --config benchmarks/configs/public.json --dataset longmemeval-oracle --limit 3
```

These stages require no model key or databases. `prepare` also acquires missing
inputs. Public HTTPS follows normal proxy/CA settings with TLS verification.
Remote inputs require a full commit digest or an explicit expected SHA-256;
Hugging Face tree discovery requires a full commit digest and follows
pagination and retains LFS SHA-256 values. Other pinned files get an observed
SHA-256 on first acquisition. Completed files have individual origin checkpoints;
partial downloads never become valid cache entries. Cached bytes are verified
before reuse and preparation. Changing a sample limit reuses raw inputs; changing
the actual upstream source identity requires a separate dataset ID/cache.

`--limit` limits **selected cases**, not download size. For example, s/m files are
approximately 277 MB / 2.7 GB; a broad ConvoMem pattern can fetch many large files.
Use the oracle, a narrower file pattern or a local subset for small experiments.
JSON arrays/JSONL stream one bounded record at a time. Source-file count, file
bytes and individual-record bytes have configurable limits.

To use an existing local ConvoMem corpus, replace its acquisition settings in a
copy of the configuration with:

```json
"local": {"directory": "../../data/convomem/core_benchmark/evidence_questions", "pattern": "**/*.json"}
```

Remove `hub` from that dataset entry. For premixed experiments use a distinct
dataset ID, `split` label and a pattern such as
`core_benchmark/pre_mixed_testcases/user_evidence/1_evidence/*.json`.
`context_sizes: [10, 50]` filters premixed `contextSize` values. `categories` filters
normalized categories. Sampling is a deterministic seeded hash ranking; omitted
`limit` defaults to three, and `--all-cases` selects every matching case.

## Dedicated stores and model configuration

ACE's resolver requires one isolated trust partition. The benchmark therefore
claims **empty, exclusive scratch stores**, reusing them serially between different
histories. It refuses populated stores and requires a Mongo database name starting
with `ace_benchmark_` plus `exclusive_scratch_stores: true`. Never attach another
worker, UI or application to these stores. Exact matching histories for the same
subject can reuse their ingestion; different subjects/histories are reset.

Reuse the repository's Compose store definitions in a separate project:

```sh
docker compose -p ace-benchmark -f compose.yaml -f benchmarks/compose.override.yaml up -d neo4j mongo
export CG_NEO4J__URI=bolt://127.0.0.1:7695
export CG_MONGO__URI=mongodb://127.0.0.1:27019
export CG_MONGO__DATABASE=ace_benchmark_work
```

The normal ignored `.env` supplies the matching Neo4j password and model settings;
Compose validates the existing file's required variables even when only stores
are selected. The benchmark uses its own in-process authenticated API and worker;
do not start the normal API/worker in this project. The override adds only store
ports, not another infrastructure implementation. `ACE_BENCHMARK_NEO4J_PORT` and
`ACE_BENCHMARK_MONGO_PORT` can change them; update client URIs correspondingly.

Providers use the existing configuration: `NVIDIA_API_KEY` or `LLM_API_KEY`,
`LLM_BASE_URL`, `LLM_MODEL`, `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`,
`EMBEDDING_MODEL` and `EMBEDDING_DIMENSION`. Set `CG_LLM__CONTEXT_LIMIT_TOKENS` to
the actual supported model window. Optional `answer_model`, `ingestion_model` and
`judge_model` in the experiment choose role-specific model IDs. Endpoint/auth,
retry and structured-output settings remain in the existing provider config;
secrets are not copied into benchmark configuration/reports.

## Run one dataset or the configured suite

After reviewing the plan, explicitly enable provider calls:

```sh
uv run --frozen agent-context-benchmark run --config benchmarks/configs/public.json --dataset longmemeval-oracle --limit 3 --execute
uv run --frozen agent-context-benchmark run --config benchmarks/configs/public.json --dataset convomem --limit 3 --execute
# All configured datasets, each with its configured sample limit:
uv run --frozen agent-context-benchmark run --config benchmarks/configs/public.json --execute
# A later deliberately full evaluation; size the request allowance for its workload:
uv run --frozen agent-context-benchmark run --config benchmarks/configs/public.json --dataset longmemeval-s --all-cases --max-requests 100000 --execute
```

`run` includes acquisition and preparation. The shared hard request limit covers
chat, extraction, judge, embedding, repair and retry attempts, and stops before
the next request. It is a **per-invocation request count**, not a dollar or token
ceiling. The default 200 is intentionally a small-run allowance; a large job may
stop incomplete and retain its checkpoints. No current command implicitly runs
the full benchmark.

Configure any subset of the six methods in `methods`, together with `trials`,
`seed`, `context_bytes`, `last_n`, `top_k`, `summary_input_bytes`,
`max_output_tokens`, `scoring`, `prices` and acquisition limits. The four raw-history
methods can run without stores if ACE and the existing retriever are omitted.

## Resume, scoring and reports

The command prints a run directory beneath `data/benchmarks/.../runs/`:

```sh
uv run --frozen agent-context-benchmark run --config benchmarks/configs/public.json --dataset longmemeval-oracle --limit 3 --resume data/benchmarks/public-memory/runs/<run-id> --execute
uv run --frozen agent-context-benchmark score data/benchmarks/public-memory/runs/<run-id>
uv run --frozen agent-context-benchmark report data/benchmarks/public-memory/runs/<run-id>
```

Resume requires matching inputs, selected cases, config, models, prompts and source
revision/hashes. Completed cases make no new provider calls. Incomplete cases
restart with the old attempt archived; usage remains visible in all-attempt
totals. `score` recomputes lexical metrics from saved answers and validates any
saved judge's exact input hash/version. It does not make new judge calls. To run
semantic judging initially, set `scoring: "judge"` and optionally `judge_model`.

Outputs include:

- `run.json`: exact configuration, raw/prepared input hashes, model and embedding
  IDs, provider/pipeline parameters, dependency versions, code/prompt fingerprints
  and completion state.
- One private `case-*.json`: source history, references, input contexts, answers,
  per-trial scores/errors and stage latency/usage; reference labels never enter
  ingestion, summaries, retrieval or answer prompts.
- `summary.json` and `report.md`: attempted/failed counts, category metrics,
  setup and answer/judge time/cost, current/all-attempt stage totals, source recall
  where exact mappings exist, clustered intervals and sample-limited percentiles.
- `exports/<dataset>-<method>-trial-<n>.jsonl`: `question_id` / `hypothesis` records,
  compatible with LongMemEval's external official QA evaluator input shape.
- Checksum-verified summary and passage-vector caches. Indexing is measured on
  creation; later questions reuse it. Corrupt or incomplete cache data is not
  silently accepted.

`completed=true` means the workflow accounted for its scheduled trials, not that
answers are correct. Preparation, ingestion, provider and judge failures remain
in denominators. A failed graph ingestion does not suppress the other baselines.

Graceful shutdown releases both store claims and removes benchmark data. After
an abrupt kill, stop the process and inspect the run before explicitly cleaning
its matching claims:

```sh
uv run --frozen agent-context-benchmark clean --config benchmarks/configs/public.json --run-id '<run-id>' --execute
```

Cleanup requires matching run IDs in both stores. It does not adopt populated
unclaimed databases. Then resume using the same configuration. Keep reports and
checkpoints; they contain the spend history and are not deleted by store cleanup.

## Fairness, metrics and limits

Every method receives the same question/date, answer model, instructions, schema,
output allowance and context-byte budget. There is no gold-label access or extra
research document supplied to one method. Whole-record packing for full history
and last-N follows the existing evaluator: oversized records can be omitted;
selected source IDs make that policy inspectable. Rolling summary is incremental
and bounded; a record that cannot fit its safe input window is an explicit method
failure. Vector top-k uses passage/query embedding modes. ACE and legacy share
the same indexed/extracted history and both receive setup-cost attribution.

By default a replay clock follows session/question dates across writes and
retrieval. Normal runtime defaults still use UTC wall time. ConvoMem lacks trusted
dates in these inputs, so a recorded `missing_time_origin` generates ordering
timestamps; this is not a real-world elapsed-time claim. UTF-8-safe event chunks
preserve long text and obey the existing stream limits. Unsupported/malformed
schemas, unknown roles, future history and duplicate IDs fail preparation.

Lexical normalized EM/F1 and declared abstention are diagnostic metrics. Optional
category-aware judging follows LongMemEval-style criteria, but its model and
structured protocol differ from an official evaluator: **no official leaderboard
equivalence is claimed**. Use exported hypotheses with the upstream evaluator
for official scoring. Same-model judging is not independent semantic proof.

Rates in `prices` are user-supplied USD per million input/output tokens, keyed by
exact model ID. Missing/null/invalid usage, failed requests or missing prices make
stage dollar cost **unknown**, not zero. Reported usage is not complete billing
when a provider omits it. Global stage totals charge shared work once; method
attribution separately shows the setup each method needs. Setup-inclusive trial
ratios amortize only these measured trials, not future production traffic.

Bootstrap intervals use subjects/conversations when identified and cases otherwise;
repeated generations are not independent task samples. Fewer than ten clusters
produce no interval; p95/p99 require at least 20/100 answer-latency samples.
These are descriptive statistics, not SLOs. Summary/legacy source recall is null
when exact source mapping is unavailable. ACE evidence mapping inherits the
existing endpoint's bounds. Retrieval provenance is not universal entailment.

## Verification

The audit first confirmed/skipped 39 existing evaluator/oracle/converter checks
and 82 writer/retriever/assembler checks. New tests use synthetic schema fixtures,
mock HTTP acquisition/providers and real isolated MongoDB/Neo4j. The CI workflow
runs the dedicated benchmark fixture tests before the general tests while its
graph is empty; no model key or paid calls are required.

```sh
uv run --frozen pytest tests/unit/test_benchmark_datasets.py tests/unit/test_benchmark_runner.py -q
# Set an explicitly empty dedicated fixture graph; models are mocked:
CG_INTEGRATION=1 ACE_BENCHMARK_TEST_NEO4J_URI=bolt://127.0.0.1:7693 uv run --frozen pytest tests/integration/test_benchmark_pipeline.py -q
uv run --frozen pyright
```

The integration tests also use the repository's standard MongoDB fixture at
`127.0.0.1:27017`; this is separate from the sample benchmark deployment's 27019.

See [validation evidence](validation.md) for executed commands/counts and
[the remaining-work ledger](../../REMAINING_WORK.md) for open full-scale evaluation,
interactive dataset and production-system gates. Native full datasets, official
scores, paid provider interoperability at scale, public benchmark benefits and
real dollar totals remain unmeasured by this fixture-only implementation.
