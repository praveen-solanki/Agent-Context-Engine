# Validation evidence — 2026-11-03

Copied baseline: `3e2454e09deb12aa68c90e76a4948c221d7974b2`.
Python 3.12.14; dependencies resolved in `uv.lock`; MongoDB 7.0 and Neo4j 5.26.

The original Context-Graph checkout remains clean. The new GitHub repository was
confirmed private through GitHub's API. Code and history were copied without
rewriting the source repository or history.

## Executed checks

- Baseline: 292 offline tests passed; 7 live-service tests skipped; Pyright clean.
- Final combined suite: 355 passed, 1 deselected. Command:

  ```sh
  CG_INTEGRATION=1 CG_NEO4J__URI=bolt://127.0.0.1:7690 \
    CG_MONGO__DATABASE=ace_baseline_test .venv/bin/pytest \
    -k 'not test_the_ui_runs_the_tool_and_shows_the_result'
  ```

- Strict Pyright: zero errors/warnings.
- Ruff formatting applied to the new modules and touched Python files.
- Git whitespace check clean.
- 22 database/API integration tests passed: real Mongo concurrency, event
  idempotency, identity/scope rejection, lease recovery/fencing, append during
  processing, dead-letter replay, automatic correction feedback, real Neo4j
  lifecycle/scope query restrictions, handoff concurrency/evidence/stale resume,
  authenticated HTTP+SDK requests, readiness and application lifespan.
- 19 focused assembler tests cover budget accounting after rendering, atomic
  packing, required-policy failures, active-state conflicts, expired/revoked
  facts, source failures, reproducibility and defensive isolation.
- Incremental ingestion tests verify immutable prior episode identity,
  supersession, retry idempotency, rejected source edits and canonical JSON
  metadata fingerprints.

## Explicit limitations

The deselected original UI integration test requires live model credentials and
specific seeded user/team data. Neither is available. No live-model extraction,
answer quality, model-switch demo, cost/latency benchmark or comparative task
success claim is made. The in-memory pipeline feedback tests use scripted
providers and are identified as such.

The complete blueprint is not finished. Remaining required work includes the
credentialed research-agent feedback demo and original UI adaptation, complete
shared/task/historical retrieval parity, authoritative external artifact
verification, governance/erasure/retention controls, distributed write fencing and
quotas, comparative evaluations, containerized deployment/CI and production
recovery/load/chaos gates. See the maintained blueprint ledger. Physical database
isolation per tenant/user trust partition remains mandatory.
