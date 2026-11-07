# Agent Context Engine implementation decisions

Baseline: `3e2454e09deb12aa68c90e76a4948c221d7974b2`, copied with history from
Context-Graph. The original repository is not a development target.

## Compatibility

Keep the existing `context_graph` package, command, graph schema, providers and
test behavior. The public `agent_context` facade is additive. No original
specification attachment was present in the checkout; the blueprint and existing
tests establish the preserved invariants. Do not claim unspecified compatibility.

## Event consistency and recovery

MongoDB owns event streams and outbox status in one atomic document. Bounded
sessions (128 events, 16KB UTF-8 per event by default) avoid a distributed
transaction or an unbounded 16MB document. Sequence gaps, retroactive edits,
changed idempotency keys, forged identities and late timestamps are rejected.
Start another session after the cap. Historical import is not yet implemented.

An acknowledged append means **recorded**, not available. The worker leases a
session, calls the existing ingestion pipeline, and advances availability only
after successful batch outcomes. A crash leaves an expiring claim. Use a stable
deployment run ID to reuse extraction, segmentation and checkpoints. Failed
streams become dead letters after bounded attempts; privileged replay resets the
attempt count. Stale lease tokens cannot advance the Mongo watermark. Graph and
Mongo are not a single transaction: idempotent graph writes reconcile a crash
between graph commit and watermark advancement. Multi-process Neo4j write fencing
and crash-during-driver-commit chaos testing remain required before production.

Incremental ingestion finalizes the current segmentation boundary. An append
segments only the new tail; existing episodes and exact spans remain immutable.
New episode ordinals follow previous ordinals. Input fingerprints reject edits
before graph mutation; legacy segmentation records are verified against source
spans and upgraded on use. No destructive graph migration is required. Rolling
back the optional fingerprint field preserves serialization compatibility, but
old code must not resume incrementally extended sessions because it can regroup.

The conversational UI separates the request path from extraction/planning.
Durable pending first-party inputs provide bounded working context while the
existing worker derives graph memory and applies quote-validated project changes.
Only complete successful work advances availability; answers do not wait on it.
Canonical task snapshot authority is independent of graph availability when
explicitly requested. Original/current actor grants, privacy fences, CAS and
authenticated receipts remain required. See [background processing](background-processing.md)
for ordering, bounds, retry/deployment behavior and verification limits.

## Identity and isolation

Event input cannot carry tenant, user or trust fields. A trusted transport must
construct `Principal`; constructing one from arbitrary request JSON is forbidden.
Projects require independently configured grants. Agents cannot assert user
messages or corrections; users cannot attest agent/tool results. Correct and
admin permissions are separate. Namespace ingestion IDs with a length-framed
SHA-256 digest, preserving original external event IDs in provenance metadata.

Namespace IDs are not complete multi-tenant isolation. The existing pipeline's
global concept-resolution queries require physical tenant database isolation
or a separately tested query migration. Do not expose the legacy demo/graph
planner as a multi-tenant service. The legacy demo remains a local development
tool; no existing membership assertions are promoted into new permissions.

## Verification and outstanding gates

- Original baseline: 292 offline tests passed; 7 live tests skipped; Pyright clean.
- Event stage: 22 new contract/incremental unit tests and 6 live Mongo tests.
- A real Mongo outbox drives the original in-memory pipeline with deterministic
  scripted providers; a changed requirement supersedes its predecessor and replay
  does not duplicate episodes or context. This is not a live-model quality claim.
- The original combined vector integration suite had an equal-score fixture
  collision. The copied tests now include tied candidates and verify the target
  score and maximum score rather than relying on undefined ordering of ties.
- Live NVIDIA extraction, embedding, UI and three-session demo validation now pass.
  No production-readiness or complete-blueprint claim is made. See validation.md.
- The additive API uses SHA-256 bearer-token bindings to server-owned principals,
  bounded request bodies, request IDs and sanitized errors. The deployable runtime
  enforces one tenant/user trust partition per database deployment. Scoped private
  datastore retrieval, deterministic assembly and durable handoffs have real
  database tests; full historical/shared/task parity is still pending.
- The bounded credentialed research demo and primary governance primitives have
  recorded verification. Canonical live task state, independent host/provider
  portability, distributed fencing/quotas, full deployment/recovery and fair
  comparative benchmarks remain required gates. No data deletion SLA is claimed. External
  artifact references fail closed without an authoritative host verifier.

The later implementation adds trusted artifact versions, immediate revocation fences, derivation opt-out, streaming export and lease-aware primary erasure. Privacy controls quarantine subjects before deletion, retain minimal tombstones, and report external backup responsibilities explicitly. See operations.md for the supported lifecycle and remaining gates.

The 2026-11-04 completion audit preserves and skips verified base functionality.
The original six-flag demo could accept a refusal; current task verification uses
typed output assessment and independent quote/choice/source checks. Failed and
passing runs remain separate artifacts. Authorized literal relevance is now
applied before candidate LIMIT, with consistent snake_case tokenization in
assembly (`ace-assembly-v2`); no storage/schema migration is required. This does
not close semantic/state/evidence-search/temporal parity or production gates.
See REMAINING_WORK.md and validation.md for exact source revisions and commands.


## Owned projects and pre-record routing

Owner-authorized automatic project resolution adds a bounded Mongo owner directory,
not a second graph or agent framework. Stable IDs, CAS revisions and create
idempotency prevent destructive rebinding/lost updates. The application verifies
same-owner configured delegates and augments membership only for the owner and
that delegate. Static grants and physical trust partition remain unchanged.
Semantic proposals precede event/tool/task writes; ambiguity does not guess a scope.
A project switch starts a new immutable stream. Personal general chat skips task
creation. Source-project provenance limits incorrectly USER-scoped legacy project
facts before candidate ranking; explicit personal applicability preserves true
cross-project preferences. Quote/role/question guards prevent unsupported new
assertions. See [design/failure matrix](project-routing.md) for tested bounds,
manual correction and remaining semantic/draft limitations.
