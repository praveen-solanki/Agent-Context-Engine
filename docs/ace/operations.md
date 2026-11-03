# Development and recovery runbook

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
excludes `.env`, Git metadata, datasets, logs and tests. Only the worker receives
the NVIDIA credential; raw console tokens are not copied into service environments.
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
