# Agent Context Engine — Master Implementation Blueprint

**Repository:** https://github.com/praveen-solanki/Context-Graph  
**Target product name:** Agent Context Engine (ACE)  
**Subtitle:** Persistent Context Management and Runtime Context Engineering for AI Agents  
**Blueprint date:** 2026-11-03  
**Document status:** Proposed future architecture and implementation specification. **It does not claim that the target system is already implemented.**  
**Current audited baseline:** the repository's `main` branch as inspected on 2026-11-03 (the most recent observed repository commits are from 2026-10-30).  
**Scope:** Extend the existing codebase into a production-oriented, end-to-end, reusable context infrastructure product. Keep the proven implementation wherever possible; the objective is **not** to build another knowledge graph or an entire new agent framework.

> **Start here in a future chat or coding session.** Read this entire document first, then `AGENTS.md`, `README.md`, the relevant source files and tests, and any original project specification the repository instructions reference. Do not assume you have access to the conversation in which this document was written. Treat the current repository code as the verified implementation baseline and this document as the owner's *requested target direction*. Confirm the live code before edits because it may have changed. Do not assert a capability is complete without testing it. Do not rewrite functioning modules merely to match a proposed directory layout. Maintain this document's progress ledger as milestones are implemented.

---

## 1. Product definition and positioning

### 1.1 One-sentence product

A reusable, secure **context engine** that continuously converts user/agent activity into accurate, temporal, evidence-backed context, selects the smallest sufficient context for the *next agent action*, and allows agents to **continue projects reliably across sessions, models and context-window boundaries**.

### 1.2 The problem

Long-lived agents accumulate chat turns, tool outputs, files, decisions, user preferences, changed requirements, and partial work. Blindly replaying everything is expensive, distracts models, can exceed token limits, mixes old and new truth, and risks exposing context across users or projects. A basic vector memory system may retrieve semantically similar statements but miss the *current actionable state*. A graph by itself does not solve selection, freshness, authority, budgeting, handoff, or evaluation.

**Primary product loop:** observe activity → derive candidate context → resolve and govern it → store provenance and life cycle → retrieve context relevant to a task/agent step → assemble a bounded, safe context package → collect feedback/new events → repeat. A session handoff preserves project state and the exact next work.

### 1.3 What this project **is**

- A **context engineering infrastructure layer** for AI agents; neither a chatbot clone nor a KG ingestion demo.
- A shared context substrate with **episodic evidence**, **semantic context**, **live task/project state**, **short-lived working context**, **explicit handoffs**, and **agent-run checkpoints**.
- A context assembly engine that treats **who can see a fact, whether it is currently true, and whether it is worth tokens** as first-class decisions.
- A provider-agnostic, typed API/SDK suitable for wrapping an agent built with an existing runtime.
- A benchmarkable software system with realistic multi-session task-continuation tests, not merely "the agent remembered my favorite color."

### 1.4 What it is **not**

- **Not** a new knowledge graph product. Neo4j can remain an internal persistence/indexing detail; consumers should not need Neo4j/Cypher or graph-specific types.
- **Not** an agent runtime/orchestrator replacement. Let the host agent execute tools; ACE supplies, governs and updates context.
- **Not** indiscriminate LLM summarization of all chats.
- **Not** blindly permanent memory. Session-scoped data, project state, temporary observations and user preferences have different validity and retention.
- **Not** reinforcement learning, autonomous credential use or model fine-tuning as an MVP requirement.
- **Not** ungrounded claims of universal SOTA, zero hallucinations, or production readiness simply because tests exist.

### 1.5 Primary users and outcomes

1. **Agent application developers:** integrate via `assemble_context` and `record_events` instead of writing custom history prompts.
2. **End users:** get consistent preferences and decisions across sessions, with visibility and controls.
3. **Teams/project agents:** continue unfinished work and honor current constraints without exposing other people's private context.
4. **Platform engineers:** observe exactly *which* context was selected, excluded or changed and *why*.

**Core success criterion:** Given the same agent, tools, model and task, ACE improves *correct multi-session task completion and current-state adherence*, while providing defensible privacy guarantees and measuring the token/latency/cost trade-off versus fair baselines.

---

## 2. Current repository: verified implementation inventory

Inspected on 2026-11-03 through the connected GitHub repository. File names and status should be checked again before coding.

### 2.1 Existing pipeline (KEEP as the foundation)

The current `src/context_graph/pipeline/orchestrator.py` coordinates:

1. Persist conversation `Session` and exact-source `Episode` evidence.
2. Segment messages into topic/size-bounded episodes.
3. Cheap relevance gate.
4. MongoDB segmentation results, extraction batches and checkpoints.
5. Token-bounded extraction batches with overlap and rolling temporary state.
6. LLM extraction to typed signals and validation/retry.
7. Embedding-based candidate lookup, deterministic identity and LLM adjudication for ambiguous concepts.
8. Governed assignment by subject and `SESSION / USER / TASK / PROJECT / TEAM / DEPARTMENT / ORGANIZATION` scope.
9. Idempotent write of context, evidence and lineage to Neo4j.
10. Supersession, revocation, promotion of permitted shared context, and run reporting.
11. Concurrent independent session ingestion, with ordering preserved *within* a session.

**Important verified behavior:**
- Two existing segmenters: default `llm_boundary` in `pipeline/segmentation.py`; optional embedding-similarity segmenter in `pipeline/similarity_segmentation.py`. Both preserve original spans; do not claim the current implementation is exclusively non-LLM.
- `SourceSpan` stores exact text slices, offsets, timestamps and speaker metadata; preserve it.
- `RollingSessionState` is **temporary extraction working state** and is explicitly *not* durable agent/task state.
- `ContextInstance`, `MemoryConcept`, `Provenance`, `Lineage` and `ContextSupport` already exist.
- Shared-team/organization statements extracted from conversations begin as candidates; conversation assertions do **not** create membership authorization edges.
- `tool.py` exposes `ContextGraphIngestion.ingest_conversation`; CLI supports files, historical and bulk sessions.
- Defaults include Python >=3.12, Pydantic, Neo4j, MongoDB, HTTPX, and OpenAI-compatible model providers (configured for NVIDIA endpoints in example settings). Preserve provider configurability; no fixed production model.
- Tests cover unit, end-to-end in-memory ingestion, UI and opt-in live integration, with Pyright strict-mode configuration. Presence of tests does **not** imply all production failure modes are currently covered.

### 2.2 Existing retrieval and demo (KEEP, then adapt)

- `retrieval_tester/retrieval.py` has read-only retrieval of currently applicable user/shared context, directory, recent sessions, historic values and evidence; standing preferences/constraints/working style are retained. It ranks against the user message.
- `retrieval_tester/context_tool.py` has a **prototype** multi-level LLM-guided, schema-validated, bounded and read-only graph traversal planner with guard/fallback and UI traces. This is an optional internal candidate retriever, **not** the product API. It is a large module (~73 KB); avoid untested wholesale refactors.
- `retrieval_tester/graph_tools.py` provides four constrained read-only directory lookups.
- `retrieval_tester/agent.py` uses retrieved context in a model prompt and can call allowed directory lookup tools.
- `retrieval_tester/chat.py` retrieves again per message and stores the session.
- `ui/streamlit_app.py`, `ui/graph_view.py` and terminal UI provide a POC demonstration and diagnostics.
- `retrieval_tester/session_store.py` saves transcripts as JSON **locally**. The retrieval tester **never ingests its own conversation automatically**. A separate CLI ingestion call is currently required. This is an integration gap, not an already-complete feedback loop.

### 2.3 Existing data and harnesses (REUSE)

- `data/convomem_demo/` and `convomem_benchmark_converter/` for multi-session input.
- `test_conversation_generator/` for synthetic scenarios, with manifests.
- `tests/e2e/test_ingestion.py` for supersession, idempotence, scope, candidate promotion, revocation, retry and other invariants.
- `src/context_graph/providers/` for model/embedding protocols and clients.
- `src/context_graph/config.py` for central typed settings; `observability.py`, `retry.py`, graph store, Mongo ledger and schema.

### 2.4 What is not complete yet — do not misrepresent

- No **public service/API or SDK** for agent runtimes that assembles policy-filtered, token-budgeted context on every agent step.
- No general-purpose **context compiler/packer** that combines short-lived working state, durable context, project progress, prior decisions, relevant evidence and compacted tool results under explicit token quotas.
- No durable, explicit **project/workflow handoff contract** with completed actions, outstanding steps, blockers, artifact references and resumability checks.
- No automatic durable **event-feedback** cycle from the demo agent's new turns/tool outcomes into the ingestion system.
- No complete **end-user governance** API (inspect/correct/delete/export data, preference approval) implemented as a secure product.
- No demonstrated independent tenant-isolation, API identity/authentication, rate limits, production tracing, migration process, SLOs, load tests or disaster-recovery runbooks.
- No controlled end-to-end **multi-session task success** comparison against full-history, summaries, vector recall and existing retriever.
- The current query-guided graph planner is a useful prototype, but is not an evidence of storage-agnostic context engineering or a production-grade agent tool.

---

## 3. Research synthesis: evidence, patterns and differentiation

Research links and dates are supplied here so a later coding session can re-check claims. Do not rely on changing GitHub star counts or vendor leaderboard numbers as proof of production usefulness.

| Source | Useful, verified takeaway | ACE consequence |
|---|---|---|
| Anthropic, [Effective context engineering for AI agents](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents) (2025) | Optimize the **set of tokens at inference**, not just prompt wording; combine relevant prefetch, just-in-time lookup and compaction. | Build explicit runtime selection, prompt packing, progressive disclosure and context-size measurement. |
| Anthropic, [Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents) (2025) | Context compaction alone does not guarantee successful work continuation; explicit progress/handoff artifacts matter. | Separate handoff state and verified tool/work outcomes from generalized memory. |
| Anthropic, [Harness design for long-running apps](https://www.anthropic.com/research/harness-design-long-running-apps) (2026) | Context resets and structured handoff can help long tasks, with orchestration trade-offs. | Support clean resumes; do not force all history into every new session. |
| OpenAI, [Context Engineering — Short-Term Memory Management with Sessions](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory) (2025) | Turn trimming and summarization offer simple practical baselines and risks. | Implement both as comparison baselines; keep whole turn/tool boundaries. |
| OpenAI, [Agents SDK sessions](https://openai.github.io/openai-agents-python/sessions/) (ongoing docs) | Sessions preserve thread history; not a replacement for selectively governed, cross-session context. | Integrate through an adapter without duplicating the host SDK's session-management responsibility. |
| LangGraph, [persistence](https://docs.langchain.com/oss/python/langgraph/persistence) and [memory](https://docs.langchain.com/oss/python/langgraph/add-memory) | Runtime checkpoints and long-term stores serve different jobs. | Separate conversation/run continuation from durable user/project context; provide optional adapter. |
| Letta, [core and archival memory](https://www.letta.com/blog/introducing-the-agent-development-environment/) and [memory architecture](https://github.com/letta-ai/skills/blob/main/letta/agent-development/references/memory-architecture.md) | Always-visible small memory plus on-demand archival recall; persistent files/blocks can be useful. | Support pinned/standing context, searchable evidence and on-demand details; do not copy implementation blindly. |
| Mem0, [open-source project](https://github.com/mem0ai/mem0) and [2026 memory research](https://mem0.ai/blog/state-of-ai-agent-memory-2026) | Multi-signal retrieval and temporal selection are important. Vendor-reported benchmark numbers depend on model and harness, and managed-platform numbers may not reproduce in OSS. | Compare normalized baselines; evaluate keyword + semantic + temporal/context signals rather than assuming embeddings alone win. |
| MCP, [tool specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools) (2026) | Standard interface for exposing tools, with host-controlled invocation and authorization requirements. | Optional narrowly scoped MCP server for context read/feedback, **not** graph query execution. |
| OWASP, [Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (released 2025) | Prompt injection, memory/context poisoning, identity and tool privilege abuses are real risks. | Treat tool outputs/agent claims as untrusted; enforce policy before ranking and after any data transformation. |
| [LongMemEval](https://arxiv.org/abs/2410.10813) (2024/2025) | Tests extraction, multi-session, temporal reasoning, updates and abstention. | Use for memory/answer-grounding benchmark. |
| [MemoryArena](https://proceedings.mlr.press/v306/he26am.html) (ICML 2026) | Good recall does not necessarily lead to successful actions across interdependent sessions. | Make multi-session task completion a primary metric. |
| [StateMemBench / evolving state](https://arxiv.org/abs/2608.19652) (Aug 2026) | Systems may recall old statements but fail to maintain the newest effective state. | Test supersession and changed project requirements as first-class outcomes. |
| [Handoff State Continuity Benchmark](https://arxiv.org/abs/2610.36523) (Oct 2026 preprint) | Structured handoff can improve recovery and continuation; evidence retrieval and execution are different tasks. | Evaluate project handoff on actual work continuation, not summary similarity alone. |
| [LoCoMo](https://arxiv.org/abs/2402.17753) (2024) | Long dialogue with temporal/multi-hop questions. | Use as an additional recall baseline; record protocol and license. |

**Practical lesson:** Conventional memory systems optimize *storage and recall*. ACE should differentiate on **context selection + state correctness + provenance/governance + resume/handoff + measured downstream agent outcomes**. Novelty claims must be limited: many systems already implement memory, vector search and graph persistence.

---

## 4. System boundaries and responsibility separation

Use these precise distinctions throughout all documentation, code and APIs:

| Concept | Meaning | Example | Retention / truth |
|---|---|---|---|
| Raw event | Authenticated append-only observation, may include user, agent or tool content | User message; tool executed | Evidence; subject to retention/deletion policy |
| Episode | Ordered, immutable group of source spans for extraction | A project-planning discussion | Evidence; preserved exactly with source references |
| Working context | Small short-lived information for current invocation | Last tool status, current cursor | Scoped to run/session, TTL; not automatically durable |
| Durable context | Canonical, scoped, reusable fact/instruction/decision | "Prefer concise reports"; budget constraint | Validity window, evidence, authority and lifecycle |
| Project/task state | Operational state, not merely user preference | Done, next step, blocked, artifacts | Updated through authorized events; must be current |
| Handoff | Versioned snapshot pointing to evidence and next work | "Tests passed, implement endpoint next" | Explicit session/run boundary; resumable, auditable |
| Context bundle | **Computed view** for one agent step | Current requirements + decisions + relevant spans | Ephemeral output, reproducible assembly trace |
| Agent run checkpoint | State needed to retry a tool/agent step safely | Tool call ID, outcome, approved continuation | Durable run control; cannot be replaced by an LLM summary |
| External knowledge | Documents/code/docs not owned by conversation | Search index or repository | Not silently copied into personal context |

**Do not treat generated summaries, model responses or tool output as authoritative user instructions.** Do not treat retrieval rank as proof of truth. ACE's authority/validity/privacy filters are deterministic, ahead of LLM relevance and after assembly transformations.

---

## 5. Target architecture (logical; reuse existing persistence)

~~~text
                User / Agent / Tools / Files / Events
                              |
                   Authenticated Event API
                              |
                    Event Log + Outbox (Mongo)
                      |                 |
             Async ingestion       Current run/session state
                      |                 |
    EXISTING: episodes -> gate -> extract -> resolve -> policy
                      |
           EXISTING: Neo4j context + evidence + lineage
                      |
      +---------------+-------------------+
      |                                   |
  Context retrieval adapters         Handoff/state store
  (current graph retriever,           (project/task/run context,
   optional hybrid candidates,         pointers and checkpoints)
   optional schema-planner)                 |
      +-------------------+---------------+
                          |
                   Context ASSEMBLER
    1. Authenticate & authorize subject, project, tenant
    2. Resolve live task and current valid state
    3. Gather semantic, keyword, recency, pinned, evidence candidates
    4. Filter policy, trust, temporal status and contradictions
    5. Deduplicate/rerank and pack under explicit token budget
    6. Emit typed ContextBundle + reasons, source refs, trace
                          |
              Agent SDK / MCP / HTTP adapter
                          |
          Existing agent runs next step or resumes
                          |
             Agent events / outcome feedback
                          |
                   Event API again
~~~

**Data plane:** ingest → persist → retrieve → assemble → deliver → feedback.  
**Control plane:** tenant/identity, policy, quotas, versioning, deletion, metrics, admin.  
**Demo plane:** one real agent + multi-session, task-continuation scenarios.  
**No default new graph engine, cache service or vector DB.** Neo4j and its current vector index are reused initially; MongoDB remains the checkpoint/event state store. Introduce new infrastructure only when measured requirements justify it.

### 5.1 Source-of-truth rules

- Immutable source transcripts/episodes remain attributable to the original actor and identity.
- Canonical active context plus validity, scope and lineage is stored behind a `ContextStore` port; initially the Neo4j implementation.
- Runtime checkpoints, in-flight event processing and outbox state have separate durable ownership; initially MongoDB collections.
- Agent or tool statements can **propose** context; no automatic elevation to policy authority. Authoritative directory/team mappings remain separate.
- Context bundles are **derived**, never authoritative; each item includes its context/evidence IDs and policy/version identifiers.
- A model must not create permissions, scopes, user identities, retention rules or access grants.

### 5.2 Transaction and delivery model

The current project spans Neo4j and MongoDB and cannot assume one atomic transaction. Require at-least-once event delivery with stable event IDs, idempotent context mutations, checkpoint only after durable outcomes, an outbox/reconciliation worker, failure replay and a written recovery procedure. Explicitly define consistency lag and whether assembled bundles are strongly or eventually consistent for newly submitted events. Prefer waiting for an ingestion watermark when the user needs read-your-writes.

---

## 6. Detailed feature requirements and acceptance criteria

### F1 — Unified event ingestion / feedback loop (**P0**)

**Goal:** Capture not just uploaded chats but the demo agent's actual turns and allowed tool outcomes automatically.

- Define typed `EventEnvelope`: event_id, tenant_id (trusted), actor identity, user_id (trusted), agent_id, session_id, project_id/task_id if applicable, run_id, causation/correlation IDs, event kind, sequence, event_time, receive_time, source trust, content/payload reference, schema_version, idempotency key.
- Support user messages, assistant responses, tool call + sanitized result + success/failure, task state transitions, user correction/forget/consent events and explicit handoff events. Tool payloads should be bounded, redacted or stored as encrypted references, not blindly embedded.
- Persist authenticated events before asynchronous processing; dedup on (tenant, event_id); order within a session; handle retries and poison messages with dead-letter processing.
- Map conversations to existing `SessionInput` and reuse the existing ingestion API. Extend input adapters; do **not** fork the extraction/resolution/writer pipeline.
- Distinguish `event recorded`, `episode persisted`, `context derived`, `context available`; never conflate enqueue success with completed ingestion.
- Support bulk historical import and incremental streaming without changing the semantic meaning of an Episode.
- **Acceptance:** chat → event → ingestion → next authorized assemble returns new valid context, without a manual CLI command; duplicate delivery does not duplicate context or evidence; failed batches are replayable.

### F2 — Context model evolution without destroying current schema (**P0/P1**)

Keep `MemoryConcept`, `ContextInstance`, `Provenance`, `Lineage`, existing scope enum and lifecycle. Add only fields/typed projections backed by real needs:

- Context origin: direct user, delegated agent, external tool, trusted organizational writer, imported source.
- Evidence and trust: exact SourceSpan refs, event and episode IDs, source type, actor, derived-vs-authoritative classification, extraction/model version, confidence **as a heuristic not a permission**.
- Time: event time, recorded time, effective_from/to, observed_at, superseded_at, expiration/TTL, optional as-of query. Make current state unambiguous; multiple competing candidate statements must not silently become simultaneous active single-valued truth.
- Scope: tenant, user, agent, session, task, project, team, department, organization; access is based on authenticated principals and trusted membership, **not user-supplied scope strings**.
- State: active/candidate/superseded/revoked/expired (expired may be computed from valid_until rather than extra status); archived evidence remains subject to privacy/deletion policy.
- Type: existing preference, goal, task, decision, constraint, working style, state, activity, event, interest, fact. Add typed task/project state *only if not expressible safely as a scoped context*.
- Change semantics: assertion, correction, explicit revocation, supersession, confirmed action, unresolved conflicts, authority override. Preserve prior values as history when permitted.
- Implement versioned migrations and old-to-new serialization compatibility; do not bulk-rename labels, properties or fingerprint logic without a migration and rollback plan.
- **Acceptance:** changes to current project requirements invalidate earlier selections; provenance is explainable; user-private data never becomes team context merely from an agent utterance.

### F3 — Context retrieval service (**P0/P1**)

Current `Neo4jContextRetriever` should become one backend adapter behind a new `ContextCandidateSource`/ `ContextRetriever` protocol with typed identity and caller context.

Candidate sources, gated by tests and relevance:
- **Always-on/pinned:** current valid standing user instructions, confirmed project constraints, explicit high-priority policies (only trusted policy can force a hard rule).
- **Semantic:** reuse current embeddings and Neo4j similarity search.
- **Lexical:** use native indexed property/text lookup or available full-text capabilities before adding Elastic/BM25 infrastructure.
- **Temporal/current state:** prefer currently effective state; support historical as-of queries only when requested and allowed.
- **Episode evidence:** source excerpts and citation IDs on demand, rather than injecting entire transcripts.
- **Project/task/run:** explicit current status, outstanding tasks, outputs and next actions from handoff/checkpoint.
- **Optional structural candidate retrieval:** retain the existing dynamic graph planner internally; compare against simpler retrieval on quality, cost, security and latency before making it the default.

**Important:** never read private user/team data then try to filter it only after scoring or prompting. Scope authorization and tenant partitioning must constrain the actual datastore query, with defensive recheck before packing. Do not trust identifiers supplied by the LLM.

### F4 — Adaptive Context Assembler / Compiler (**PRIMARY NEW FEATURE, P0/P1**)

Public conceptual operation:

~~~python
async def assemble_context(request: AssembleContextRequest) -> ContextBundle:
    ...
~~~

Minimum input contract: authenticated principal/tenant, agent_id, session_id, project_id/task_id, current user message or task-step intent, tools available, requested context purpose (answer/planning/next-action/handoff), provider/model token budget, remaining response/tool reserve, optional as_of and feature flags.

Return a **typed**, auditable `ContextBundle` with:
- current task objective and effective constraints,
- relevant verified user/project preferences and decisions,
- current task progress, completed work, pending steps and blockers,
- selected evidence excerpts/source IDs when needed,
- short recent conversation/tool context respecting turn boundaries,
- optional on-demand reference handles for larger artifacts,
- temporal/correction warnings and unresolved conflicts,
- estimated/measured tokens, bundle version, selection trace, policy decisions, retrieval watermark,
- explicit separation of trusted instructions from untrusted retrieved content.

**Assembly sequence and invariants:**

1. Validate identity and entitlement **server-side**; define project-specific access grants independent of conversational assertions.
2. Load current run/task state and allowed scopes; establish read consistency watermark.
3. Apply validity, status, revocation, tenant, principal and source-trust filters **before** reranking.
4. Gather pinned/required context and candidate facts from retrieval adapters concurrently where safe; bound top-k and latency.
5. Merge by canonical identity, remove stale or superseded states, preserve high-value contradictory evidence as *conflict* rather than arbitrarily accepting it.
6. Rank candidates using configurable signals: query/task relevance, recency, explicit priority, project/task match, reliability/evidence, state transitions and redundancy. Start with deterministic weighted features; add an LLM reranker **only if a controlled benchmark shows net improvement**.
7. Reserve tokens for system/developer instructions, tool schemas, current request, model output and safety margin. The engine owns only its allocated budget; never override the agent host's required instructions.
8. Select highest-utility nonredundant items under budget; group related decisions/constraints, keep atomic items and evidence pointers intact; use safe compaction of **tool output and older turns** separately from canonical facts.
9. Render a consistent prompt/structured bundle: hard trusted constraints, live task state, relevant knowledge, evidence, history, optional reference handles. Mark retrieved text as data, not imperative instructions.
10. Emit a decision trace with selected/excluded IDs and reasons (e.g., unauthorized, revoked, stale, duplicate, low relevance, budget).
11. Let the agent request additional scoped evidence just-in-time; reapply the same authorization and budget rules.

**Packing objectives:** maximize downstream task success under a bounded prompt budget, not simply similarity score. A shorter bundle is good only if it preserves mandatory constraints and accurate state.

**Acceptance:** no context that the actor cannot read, no revoked context, no old value silently overriding a new one; repeated identical input + pinned versions is reproducible; token budget is enforced after rendering; trace explains selection; graceful behavior with zero candidates/temporarily unavailable optional source.

### F5 — Explicit session/project handoffs (**PRIMARY NEW FEATURE, P0/P1**)

Create a versioned `HandoffArtifact`, separate from durable personalization memory:

- Who/what: tenant, agent, principal, project, task, source session/run, target session or recipient (when known).
- Goal and current user-approved requirements; immutable or pinned constraints.
- Completed actions with **verifiable result references**; distinguish claimed from tool-confirmed completion.
- Current status, open subtasks, blockers, risks, unresolved questions and next recommended actions.
- Existing artifacts and their stable locators, version/commit/hash, last validation status.
- Latest decision changes and source IDs; time/version; relevant permissions, expiration, trust.
- Last known tool/cursor state needed to resume and pending side effects/reconciliation.
- Idempotent, optimistic-concurrency-controlled updates and stale-handoff detection.

**Handoff trigger:** explicit session close, context budget pressure, checkpoint/step boundary, agent change, or recovery. Use incremental evidence/state updates; optional LLM summary is a *proposal* validated against structured state, not the sole truth.

**Resume contract:** validate identity, project membership, current artifact versions, outstanding tool operations, previous handoff version; assemble current context; show conflicting or stale work instead of pretending the next step is safe. No replay of non-idempotent tool actions without checking recorded outcomes.

**Acceptance scenario:** session A identifies research requirements; B changes a requirement and completes work; C ("continue") receives the new requirement, verified completed actions and correct next step. No old constraint resurfaces. Replaying C does not duplicate an external action.

### F6 — Runtime integration and developer experience (**P0/P1**)

- FastAPI HTTP service (recommended given Python/Pydantic codebase; add only if integration requires it), OpenAPI schemas, typed errors, auth middleware, request IDs.
- Minimal Python client adapter that calls `record_events`, `assemble_context`, `prepare_handoff`, `get_context_evidence` with timeouts, idempotency and retries.
- One functioning demo integration with a chosen existing agent SDK / simple agent loop. **Do not build a second agent execution framework.**
- Optionally add MCP adapter exposing constrained `context_get`, `context_search`, `context_feedback` and `context_handoff`. Server authenticates; do not expose arbitrary Cypher or unsandboxed file/command tools.
- Keep current Streamlit UI as a developer observability/demo tool; add per-step context preview and selected/excluded items. Make it show actual agent outputs and handoff, not just graph paths.
- Local Docker Compose development stack with Neo4j, MongoDB, API and worker plus readiness checks; CI and deployment artifacts later.
- **Acceptance:** a fresh clone can run a documented demo with configured model credentials and receive a traceable, end-to-end multi-session answer without manual ingestion; failing downstream dependencies produce typed, observable failures.

### F7 — User controls, policy, privacy and safety (**P0 security requirement**)

- Authenticated tenant/user identity from a trusted auth provider or gateway; never let `user_id` in request JSON impersonate someone else.
- Separate **view**, **assert**, **correct**, **promote**, **delete**, **admin** permissions. Team/organization promotion must rely on trusted authority and evidence. No user self-granted membership.
- End-user inspect, correct, revoke, export and delete controls, with evidence and downstream projection deletion semantics. Apply retention/TTL by category, support opt-out of durable context for sensitive sessions.
- Explicit deletion propagation through Neo4j nodes/edges, Mongo events/checkpoints, vector indexes, caches, snapshots, exports and backups according to a documented policy and achievable SLA. Clarify legal holds before claiming hard delete.
- Untrusted tool/web/file/agent text must be **data**, not system instructions. Defend against prompt injection, context poisoning, tool-result laundering, hidden prompt requests and privilege elevation. Use allowlisted rendering, trust labeling and tests.
- Prevent stale-cache retrieval and cross-tenant leakage; encrypt network and storage, rotate secrets, redact logs, never emit raw private context in general metrics, enforce per-tenant quotas.
- Provenance and human-review hooks for low-trust/high-impact context; transparent "why remembered", "why selected", "why excluded" audit.
- No graph or LLM query path is an authorization bypass. Read-only graph tool must be analyzed for enumeration risk; guard data returned to models.
- **Acceptance:** negative authorization tests across two tenants/users/teams; prompt injection cannot alter permissions; revocation/deletion stops future selection within declared consistency bounds; audit contains actor and policy decision without leaking content.

### F8 — Operational integrity, observability and efficiency (**P0 production hardening**)

- Structured request, event, batch, run and trace IDs end-to-end; OpenTelemetry spans or equivalent with safe content sampling.
- Metrics per stage: ingestion age/lag, segmentation errors, extraction validation, retry rate, candidate/active counts, promotion, selection counts, budget usage, prompt tokens, answer correctness, handoff success, latency p50/p95/p99, model calls and dollars per successful task.
- Versioned prompts/models/policies, tokenizers and schema; feature flags; replayability from source episodes; deterministic seeds for tests; config snapshot hashes.
- Rate limits, queue backpressure, bounded workers, model concurrency, cancellation/timeout strategy, circuit breakers, dead-letter/replay and alerts on failures or stuck checkpoints.
- Provider outage policy: fail closed for auth and mandatory context; optional retrieval source can degrade with explicit flag, but never silently invent or drop must-have constraints.
- Idempotent graph writes, outbox and watermarks across Mongo/Neo4j; concurrent workers test.
- Strict Pydantic input/output validation, Pyright strict, secure dependencies, secret scanning, CI, image scanning and migration checks.
- Document backup/restore, disaster recovery, zero-downtime deployment/schema migration, runbooks, and reproducible local vs production configs.
- Set SLO targets *after* baseline load tests; as initial **proposals**, API availability >=99.9%, no observed cross-tenant exposure, no known data-loss paths and bounded context assembly p95 under representative load. These are aspirations until measured; do not publish them as achieved.

---

## 7. Suggested API contracts (illustrative; refine via tests and OpenAPI)

Do not expose raw graph nodes as the main product.

| Method | Endpoint | Purpose | Auth/semantics |
|---|---|---|---|
| POST | /v1/events | Ingest one or a batch of agent/user/tool events | Authenticated identity, event_id, idempotency, 202 + event status |
| GET | /v1/events/{event_id}/status | Ingestion lifecycle status and watermark | Authorized caller |
| POST | /v1/context/assemble | ContextBundle for one next step | Policy filtered, explicit budget, trace_id |
| POST | /v1/context/search | Progressive, scoped on-demand evidence lookup | Same strict policy as assemble |
| GET | /v1/context/items | Inspect my current authorized context | Scope/time filters, pagination |
| POST | /v1/context/corrections | Authoritative user correction/revocation event | Version precondition, auditable |
| POST | /v1/handoffs | Prepare/checkpoint handoff | Stable task/run IDs, idempotency |
| POST | /v1/handoffs/{id}/resume | Validate state and assemble resume bundle | Stale-check and permissions |
| GET | /v1/context/assemblies/{id}/trace | Why selections/exclusions occurred | Privileged, redacted |
| GET | /v1/users/me/export | Data portability | Async export lifecycle |
| DELETE | /v1/users/me/context | User context deletion request | Async erasure status, scope + retention policy |
| GET | /health/live and /health/ready | Health checks | No secret detail |

Representative *shape* (not final field names):

~~~json
{
  "agent_id": "research-demo",
  "session_id": "session-C",
  "project_id": "project-42",
  "task_id": "task-7",
  "query": "Continue the research using the revised requirements",
  "purpose": "next_action",
  "budget": {
    "model_context_tokens": 128000,
    "reserved_instructions_tokens": 2000,
    "reserved_tools_tokens": 3000,
    "reserved_output_tokens": 5000,
    "max_engine_tokens": 6000
  }
}
~~~

Expected response contains `bundle_id`, `policy_version`, `retrieval_watermark`, `sections`, `items` with source IDs, `token_count`, `excluded_counts_by_reason`, `warnings` and a `trace_id`. Identity/tenant/user scope **must come from auth context**, not blindly from this body. Keep actual API contracts in Pydantic/OpenAPI and publish examples from tested fixtures.

---

## 8. Integration demo: one complete user journey

Choose a **multi-session research/project assistant** as the initial demo because it exercises context without requiring unrestricted code execution or a browser agent. The demo agent can use controlled document/search/repository-reading tools, and the same ACE API can later serve a coding agent.

**Session 1:** user defines project, goals, constraints, exclusions, output quality bar and timeline. Agent records events; ACE extracts and scopes context. Agent gathers evidence and records verified completion status. Close session → handoff created.

**Session 2:** new agent/session asks to continue. ACE validates handoff and supplies current goals, open tasks, evidence IDs and next step. User changes a requirement and revokes an earlier preference. The new value supersedes the old; system records evidence + version and reassembles.

**Session 3:** an agent using a *different provider* resumes. Context assembler injects current requirements, verified progress, remaining work and references within budget. It deliberately excludes the superseded preference, irrelevant old chat and unauthorized team data. Agent completes task and persists outcomes.

**Visible demo panels:** timeline and change history; current context preview; included/excluded reasons and token count; citations; handoff diff; multi-session task result; latency/cost; user controls. Graph visualization may remain a diagnostics tab but is not the homepage or product headline.

**Necessary demonstration comparisons:** (a) last N turns, (b) full history up to budget, (c) running summary, (d) simple embedding top-k, (e) current repo retriever, (f) ACE assembler; run same agent/model/tools and fixed scenarios.

---

## 9. Evaluation program and reproducibility

### 9.1 Datasets and scenario categories

- **Existing ConvoMem:** current raw-to-session converter and demo input. Check license and splits; no data-leakage into prompts.
- **LongMemEval:** extraction, multi-session, temporal, updates, abstention.
- **LoCoMo:** long conversations, temporal/multi-hop recall.
- **MemoryArena:** interdependent task outcomes (primary for real agent value).
- **StateMemBench:** changed requirements, current-vs-superseded facts.
- **HSC-Bench:** optional handoff continuity and repository work-state recovery; audit release and license before integration.
- **Custom deterministic multi-session agent tasks:** 3–10 sessions with evolving goals, canceled requirements, stale tool outputs, project handoffs, missing evidence, revoked memory, multiple users/tenants, explicit no-memory mode, outage and retry cases.
- **Safety adversarial tests:** injected instructions in tool output, forged organizational authority, self-claimed membership, cross-tenant probing, permission changes after session close.

### 9.2 Metrics and protocols

| Layer | Measurement |
|---|---|
| Extraction | Per-class precision/recall/F1; exact source-span attribution; false durable memory rate |
| State tracking | Effective-current-state accuracy; stale-value leakage; supersession and revocation correctness |
| Retrieval | Recall@k, nDCG/MRR when labels exist, evidence grounding and authorization error rate |
| Assembly | Mandatory-context inclusion, noise/duplication, token budget violations, evidence coverage |
| Conversation | Answer exactness or rubric score, citation correctness, abstention on insufficient evidence |
| Task continuity | End-to-end task success, valid next action, handoff recovery, wrong/duplicate action rate |
| Security | Unauthorized items emitted (**target zero** in tests), poisoning success rate, deletion regressions |
| Efficiency | Total input/output tokens incl. *ingestion*, provider calls, dollars per task, p50/p95/p99 latency, throughput and queue age |
| Reliability | Replay success, duplicate-event handling, recovery time, consistency watermark lag |

**Methodology:** freeze source snapshot, dataset split, prompt, provider model/version, tool permissions, judge rubric, token budget and sampling parameters; run repeated trials and confidence intervals where appropriate; include startup/ingestion costs and cold vs warm retrieval; report failures, not just averages. Prefer executable deterministic assertions (did the agent perform the next required action?) over LLM-only judging; human-audit a sample. Do not copy vendor self-reported benchmark scores as your results.

**Ship gate:** ACE must be measurably better on a selected multi-session task-continuation or state-correctness outcome, with transparent cost/latency trade-off, and no security regressions. If no advantage emerges, adjust the selection strategy instead of claiming success. Avoid arbitrary target percentage gains.

---

## 10. Repository implementation map — keep, modify, add

**Do not wholesale rename `context_graph` or delete Neo4j internals at the beginning.** A public-facing `agent_context` façade can conceal existing internal implementation. Rename the repository, CLI, package imports or graph schema **only after** compatibility, deployment, packaging and migration tests are in place, and only if desirable.

| Existing path/component | Action | Exact intent |
|---|---|---|
| `src/context_graph/domain/conversation.py`, `domain/context.py`, `domain/enums.py` | **KEEP + EXTEND** | Preserve Episode/SourceSpan/Context identity; add versioned event and handoff projections safely, optional scope/temporal fields as migration. |
| `pipeline/segmentation.py`, `pipeline/similarity_segmentation.py` | **KEEP** | Preserve both modes and source-offset invariants. Optimize only from measured quality/cost benchmarks. |
| `pipeline/gate.py`, `batching.py`, `extractor.py` | **KEEP + TARGETED HARDENING** | Use existing typed extraction and budgets; add event-time handling and tool-output sanitization where needed. |
| `pipeline/resolution.py`, `policy.py`, `writer.py`, `promotion.py` | **KEEP + EXTEND** | Reuse identity, validity, scope, provenance, supersession, revocation; enforce new origin/trust and user correction/erasure. |
| `pipeline/rolling_state.py` | **KEEP AS IS for ingestion** | Do not mistake this ephemeral extraction summary for persistent run/task/handoff state. Add a separate runtime-state service. |
| `pipeline/orchestrator.py`, `tool.py` | **EXTEND THROUGH ADAPTER** | Existing core processing; introduce authenticated event-to-SessionInput bridge, idempotent asynchronous feedback, watermark tracking. |
| `graph/neo4j_store.py`, `graph/schema.py`, `graph/mapping.py` | **KEEP AS BACKEND** | Introduce typed query ports, policy-scoped queries, migrations and erasure; Neo4j stays internal. |
| `ledger/mongo.py`, `ledger/models.py` | **KEEP + EXTEND OR ADJOIN** | Preserve extraction checkpoints. Add separate event/outbox/run-state collections/services, not ad-hoc ledger overloading. |
| `providers/`, `config.py`, `prompts.py`, `observability.py`, `retry.py` | **KEEP + EXTEND** | Provider independence, versioned prompts, additional telemetry and central assembly settings. |
| `retrieval_tester/retrieval.py` | **PROMOTE CAREFULLY** | Wrap as first ContextCandidateSource; migrate to new typed retrieve contract; keep existing demo working until parity. |
| `retrieval_tester/context_tool.py` | **OPTIONAL INTERNAL ADAPTER** | Preserve planner/evidence/debug; run controlled comparisons. Refactor oversized file only behind tests, not as an unrelated rewrite. |
| `retrieval_tester/graph_tools.py` | **KEEP FOR DEV ONLY** | Not the default public agent tool interface. Enforce name-based, read-only constrained operations. |
| `retrieval_tester/chat.py`, `agent.py`, `session_store.py` | **ADAPT** | Replace manual re-ingest with event feedback; make demo consume assembled bundles and handoffs. |
| `ui/`, `test_conversation_generator/`, `convomem_benchmark_converter/`, `tests/` | **EXTEND** | Keep existing coverage; add context preview, handoff, agent outcomes and benchmark fixtures. |
| `README.md`, `AGENTS.md` and any original spec | **UPDATE AFTER IMPLEMENTATION PLAN IS AGREED** | Align product description and repo directions; preserve old design constraints until intentional changes are documented. |

**Proposed new modules, subject to repo review (names are guidance, not mandated duplication):**

~~~text
src/agent_context/                 # public-facing product surface; may initially be a facade
  api/                             # FastAPI routes, auth, schemas, error mapping
  contracts/                       # versioned Event, AssembleRequest, Bundle, Handoff
  application/                     # event intake, assemble, handoff, user governance
  retrieval/                       # candidate source protocol + existing Neo4j adapter
  assembly/                        # eligibility, scoring, conflict, token packing, render, trace
  runtime/                         # task/project state, checkpoints, consistency watermarks
  integrations/                    # Python SDK, agent adapter, optional MCP
  security/                        # tenant identity, policy gates, erasure/redaction
  telemetry/                       # metrics + tracing correlation
  persistence/                     # event/outbox, run/handoff, existing store ports
workers/                           # bounded background ingestion/outbox/promotion
demo/                              # research-agent multi-session integration
benchmarks/                        # datasets, fixed baselines, evaluation harness + reports
deploy/                            # Compose, deployment manifests and runbooks
tests/                              # existing + contract/security/integration/load/golden tests
~~~

Do not introduce 20 empty packages on day one. Add modules only when a vertical feature requires them. Keep business logic in a single owned component, provider/DB code behind concrete interfaces, settings centralized and types Pyright-clean.

---

## 11. Production engineering and operational checklist

### Security / multi-tenancy

- [ ] Trusted authentication, authorization and tenant-scoped datastore queries.
- [ ] Request and service-to-service identity, least-privilege keys, secret rotation.
- [ ] Input size caps, tool-result redaction, output escaping and prompt-injection tests.
- [ ] No cross-user/tenant context in responses, traces, logs, caches or exports.
- [ ] User inspect/correct/revoke/delete/export semantics and downstream erasure.
- [ ] Trusted directory/membership writer separate from conversation claims.
- [ ] Data classification, retention/TTL, optional sensitive session exclusion.

### Correctness / quality

- [ ] Idempotent event intake, segmentation cache and extraction/writer retries.
- [ ] Exactly one effective current value where cardinality/policy demands it; conflicts surfaced.
- [ ] Correct temporal handling of out-of-order and late arriving events (**current POC assumes ordered/complete input**; must be explicitly improved or enforced at the gateway).
- [ ] Durable handoff state verified against tool outcomes, artifacts and auth changes.
- [ ] Assembly respects reserved tokens, preserves turns/tool pairing and citations.
- [ ] Rollback-safe schema and context version migration.

### Ops / deployment

- [x] Local one-command setup, model credential instructions without actual secrets (`./run.sh`; local development, not production deployment).
- [ ] API/worker startup, health/readiness, graceful shutdown, streaming backpressure.
- [ ] CI formatting/lint/type/unit/contract, optional integration, secret/dependency scan.
- [ ] Staging with isolated Neo4j/Mongo, migrations, synthetic load tests.
- [ ] Safe config/version rollout, queue replay, alerting, distributed traces.
- [ ] Recovery runbook, restore test, retention and consistency SLA.
- [ ] License/dependency audit; exact model pricing/provider caps verified at runtime.

### Observability for researchers and recruiters

- [ ] Reproducible side-by-side baseline report, not just a pretty demo.
- [ ] Architecture diagram, latency and token budget breakdown.
- [ ] Named failure modes, examples of corrected state, provenance and handoff.
- [ ] Measured benchmark numbers and limitations before writing any outcome claim on a resume.

---

## 12. Implementation roadmap — vertical slices and gates

**Planning order, not a time promise.** Each phase ends with tested working code; do not attempt a single giant refactor. Mark phases complete only after the listed evidence exists.

### Phase 0 — Baseline preservation and architecture decisions
- Re-read current main, `AGENTS.md`, existing spec and tests; record exact commit SHA.
- Run `uv sync`, offline unit/e2e/UI tests and `uv run pyright`; record baseline failures and current costs.
- Create baseline metrics for ConvoMem and one three-session changed-requirement scenario.
- Decide tenancy model, event source-of-truth, service auth, consistency policy, chosen first integration, and what data is user-deletable.
- Produce architecture decision records (ADRs) and compatibility matrix; keep current demo runnable.
- **Gate:** baseline and invariants documented; no regressions.

### Phase 1 — Typed contracts + ingest event bridge
- Add versioned EventEnvelope and API/transport models.
- Authenticated, idempotent event intake and status; adapters to existing sessions/pipeline.
- Mongo outbox/processor with checkpoint/watermark, replay and dead-letter.
- Connect current demo chat and tool events to this path; support read-your-writes option.
- **Gate:** a newly written preference or corrected constraint becomes retrievable without manual CLI; replay safe.

### Phase 2 — Stable context retrieval interface
- Introduce candidate retrieval protocol wrapping current Neo4j retriever.
- Enforce caller identity, tenant/project filtering in datastore query; valid-time/version handling.
- Add pinned state and evidence refs; lexical retrieval only if coverage benchmarks justify.
- Instrument relevance, source cost and trace; preserve old UI behavior.
- **Gate:** retrieval parity tests, authorization/scope negative tests and no stale items.

### Phase 3 — Context assembler MVP
- Implement deterministic scorer, dedup/conflict handling, token-budget packer, structured renderer and trace.
- Separate hard trusted constraints, user preferences, task progress, evidence and untrusted artifacts.
- Create `POST /v1/context/assemble` and Python SDK adapter.
- Benchmark against existing retrieval, last-N, rolling summary, vector-only and full history.
- **Gate:** real agent step uses bundle successfully; budget, freshness, policy tests pass.

### Phase 4 — Task/project state and durable handoff
- Add typed project/task status, action outcomes, artifact locators and HandoffArtifact.
- Implement create/validate/resume with optimistic concurrency, idempotency and stale checks.
- Add optional safe compaction of older conversation/tool output with references to original evidence.
- Demo three independent sessions and agent/model switch; no duplicated side effects.
- **Gate:** valid next-action/task success and evidence continuity on handoff scenarios.

### Phase 5 — Complete demo integration and developer DX
- Full authenticated API lifecycle, SDK, OpenAPI and example integration.
- Research assistant runs real research tasks with bounded read tools; event feedback and context assembly at meaningful task steps.
- Streamlit/CLI context, handoff, privacy and trace views.
- Containerized local setup + usable environment templates; clear errors and test fixtures.
- **Gate:** fresh clone runs documented E2E example after setting credentials, with no hidden manual steps.

### Phase 6 — Evaluation and optimization
- Build frozen scenarios and appropriate public benchmarks.
- Compare uniform model, datasets, budgets and tools across all baselines.
- Run ablations: no temporal filter, no handoff, no provenance, no pinned constraints, no rerank, no graph planner.
- Measure cost *including ingestion*, token savings, latency and task outcomes; optimize only real bottlenecks.
- **Gate:** reproducible metrics and a defensible value proposition. If quality fails, iterate.

### Phase 7 — Production hardening and governance
- Threat model and negative tenant/scope/injection tests.
- Corrections/forget/export, retention/erasure and audit policies; secrets and compliance controls.
- Load and chaos tests: provider outage, partial DB commit, late event, duplicate event, worker crash, cross-tenant probes, deployment rollback.
- CI/CD, migrations, telemetry/alerts, SLO evaluation and restore runbooks.
- **Gate:** deployment readiness review; explicitly state remaining limitations.

### Phase 8 — Optional differentiation (only based on evidence)
- MCP integration and host SDK adapters (OpenAI Agents SDK, LangGraph, etc.).
- Progressive on-demand citation explorer; hybrid lexical/semantic reranking; learned selection policy if justified.
- Cross-agent handoffs and project team collaboration with strict scoped sharing.
- Embedding-free deterministic paths for cheap/high-confidence constraints and cheap router to skip unnecessary LLM processing.
- Storage adapter independence tests; **do not replace Neo4j just for marketing**.
- Multi-modal context reference adapters only if validated use cases demand them.

---

## 13. Definition of Done for the *whole product*

The repo should be called a production-oriented end-to-end context engine **only when all required items below are demonstrated**:

1. **Ingest:** authenticated user/agent/tool events enter and can be replayed; original evidence and exact spans remain attributable.
2. **Derive:** current extraction/semantic resolution and governance run automatically, asynchronously and idempotently.
3. **Lifecycle:** active, changed, expired, revoked, promoted and contested context behave correctly over time.
4. **Retrieve:** user/project/tenant boundaries are enforced before returning candidates; historical/episodic evidence is available with citations.
5. **Assemble:** context for a next agent step is current, relevant, compact, budget-bounded, policy-safe and explainable.
6. **Continue:** agent can hand off/resume real project work across sessions and models using verified progress, not just previous chat summary.
7. **Observe:** requests, jobs, LLM calls, actions and selection decisions are traceable without leaking secrets.
8. **Govern:** inspect, correction, deletion, retention and role-based access are implemented and testable.
9. **Deploy:** repeatable local setup, CI, migrations, worker/API deployment, recovery and monitoring exist.
10. **Prove value:** fair multi-session baselines and task outcomes with cost/latency/security reporting are published; failures and limitations are disclosed.

### Explicit non-goals for initial release

No training a foundation model, no autonomous desktop/browser control, no unrestricted shell tools, no massive multi-agent framework, no graph-specific public API, no new vector store without demonstrated need, no mandatory expensive LLM at every read, and no vague "reasoning graph" claims.

---

## 14. Decision log and important unresolved choices

These are **real implementation decisions** to validate against the current repository and benchmarks, not reasons to stop working or ask generic clarification questions.

| Decision | Recommended starting point | When to revisit |
|---|---|---|
| Public product identity | Agent Context Engine; graph internal | After external pilot feedback |
| Primary language/framework | Python >=3.12 + existing Pydantic; FastAPI at API boundary | Only if deployment constraints force other stack |
| Canonical persistence | Existing Neo4j for context/evidence; Mongo for ledger/events/run/handoff state | Measured scaling/cost, backup or security requirements |
| Retrieval | Existing scoped retriever first; hybrid signals and planner as optional candidates | Ablation demonstrates benefit |
| Selection | Deterministic, explainable scoring/packing first | Sufficient labeled outcome data proves LLM/learned reranking helpful |
| Handoff | Structured task state + evidence + artifact handles, not summary-only | Multi-agent/team workflows need richer protocol |
| Demo host | Small research project assistant with bounded read tools | Basic E2E completed, then SDK/MCP adapters |
| UI | Developer-facing Streamlit demo retained | After validated customer UX |
| Public package rename | New facade now; keep internal names for compatibility | Tested migration and versioned release |
| Consistency | Eventual with explicit ingestion watermarks and optional read-your-writes | User-facing interactive requirements |
| Privacy | Scoped default-private, minimal retention, deletable subject context | Legal/compliance requirements in a real deployment |

**Potential compatibility traps:** existing `AGENTS.md` says an attached original Context Graph spec is source of truth. The new project direction explicitly changes the product goal, but do not casually overwrite old technical invariants. Locate the original spec if present, document each incompatible change in ADRs, update instructions/spec deliberately, and test migrations. Also do not assume every new scope/field can simply be populated by the extraction LLM.

---

## 15. Project presentation / resume wording (only after implementation)

**Current honest description:** "Agent Context Engine (Context Graph POC foundation) — conversation-to-context extraction, concept resolution, scoped lifecycle, provenance and personalized retrieval."

**Target description after demonstrated functionality:** "Agent Context Engine — production-oriented context engineering and multi-session continuity infrastructure for AI agents; adaptive context assembly, temporal/state-aware memory, evidence-backed handoffs, secure integration APIs and measured task-completion improvements."

Do not claim measured token reduction, task-success gain, p95 latency, multi-tenant safety or completed production deployment until the evaluation/report actually shows it.

---

## 16. Instructions for the next ChatGPT / Claude Code / Cursor session

**Use this exact handoff instruction in a fresh coding session (the repository remains the source):**

> Read `CONTEXT_ENGINE_MASTER_BLUEPRINT.md`, `AGENTS.md`, `README.md`, and the relevant code/tests in this repository. This is an existing Context Graph POC being evolved into an **Agent Context Engine**, not a request to rebuild it or build another graph application. First verify the live implementation against the blueprint's KEEP / EXTEND / NEW matrix and identify any differences. Preserve the ingestion, segmentation, source-span, concept-resolution, policy, provenance, lifecycle, store and test functionality unless a tested change is required. Plan and implement the next incomplete vertical slice, with clear interfaces, data flow, tests, migration implications, and evidence that it works end-to-end. Focus on authenticated event feedback, adaptive context assembly, task/session handoff, runtime integration, privacy/governance and measured multi-session agent outcomes. Do not add infrastructure or frameworks unless justified. Do not hardcode thresholds, bypass authorization, duplicate functionality, or claim features are finished without running tests and type checks. Update the blueprint's progress ledger and design decisions as you go.

**Recommended first work request:** "Implement Phase 0 audit and Phase 1 event-feedback vertical slice. Show an actual demo user correction flowing from agent event to current context retrieval, with idempotency and authorization tests. Leave all other features unchanged."

### Progress ledger (the next agent should maintain this)

2026-11-05 owner-authorized automatic project identity and concurrent bug fixes:
**CONFIRMED DONE within 79 focused checks; strict changed-code/test Pyright clean.**
The actual conversational UI now resolves owner-authorized project names, aliases,
descriptions and approved current goal hints before persistence, reuses stable IDs,
and creates private owned projects for clear new undertakings. A bounded Mongo
owner directory supplies CAS/idempotent metadata, trusted host delegation, stable
rename/alias overlays (including legacy configured IDs), export and primary erasure.
Ambiguity/multi-project messages wait; manual override and general Personal space
remain available. Existing stream bindings, task CAS and actual context assembly
are reused; cross-project switches preserve prior history in separate streams.

Concurrent fixes prevent transient stale project UI, project-origin USER memory
leakage and unsupported question/assistant-derived facts. Explicit personal scope,
source quotes and role/question guards preserve true personal preferences and real
user uncertainty. No graph-wide data migration/deletion, new database/framework,
full suite/application run or benchmark was used. The explicit
usefulness and production-readiness exclusions remain open. See
[failure matrix and limits](docs/ace/project-routing.md),
[verification](docs/ace/validation.md), and
[record](docs/ace/results/automatic-project-routing-20261105.json). Semantic model
accuracy is not established by mocked fixtures; three capped model-only probes
passed existing/multiple routing but rejected uncertain new creation, whose explicit
confirmation path is tested (no database writes from probes; billing unmeasured); unsent drafts are browser-local;
there is no automatic bulk merge/history move/verified-outcome rollback.


2026-11-05 focused constraint/recall defect correction at baseline `6f8560d`:
**CONFIRMED DONE within scoped checks**. An unchanged approved goal echoed by the
model no longer invalidates a valid new constraint. New claims still require
exact source quotes; invalid proposals receive bounded field-specific repair.
Parser prose no longer bypasses the evidence/answer host or enters it as competing
information; only fixed validation statuses are supplied. Active tasks with no
accepted next step are not labelled complete. Reused the task CAS, assembler,
SDK/host and citation repair; no new architecture or ingestion behavior.

Evidence: 38 focused checks pass and changed implementation/tests are Pyright
clean. Three before-fix reproductions and six capped synthetic model-only calls
are documented, including failed raw proposals and their successful revalidation
after the no-op fix. Revalidation is not a fresh provider execution. See
[verification](docs/ace/validation.md) and
[probe record](docs/ace/results/workspace-constraint-recall-20261105.json).
No full suite, full ingestion E2E, benchmark or production-readiness work. Past
failed updates are not silently migrated; historical answers remain history.


2026-11-05 owner-authorized conversational workspace: the first four UI/continuity
improvements are **CONFIRMED DONE within the focused verification bounds**.
Existing ingestion, task CAS, mandatory assembly, tool receipts and governance
were inspected/reused. The page now automatically records quoted conversational
task changes, distinguishes sourced user reports from verified tool execution,
restores owner/project-scoped conversations, binds new answers to current task
revisions, and exposes real evidence/correction/removal actions. New title/list
metadata lives on the existing event streams; no extra database/framework/demo
was added. The UI is neutral/teal, chat-centred, with project/conversation navigation
and an optional context inspector. Manual progress forms are removed; historical
handoff API/SDK support is preserved.

Evidence: 28 unit/UI + ten new real-Mongo API/SDK + ten affected host-grounding
+ three compatibility checks pass (51 distinct focused checks across scoped
runs); changed-code/tests strict Pyright clean. New integration tests use mocked
providers and explicitly advanced worker watermarks; they are not live extraction
or universal task-success proof. Tests cover retry after a recorded tool result,
concurrent plan changes, original-quote validation, cross-scope navigation,
legacy hash replay and interrupted exact-target correction. Existing quotas and
configured project grants remain. Historic answers expose original references but
do not invent their old selected bundles. See [workspace guide](ui/README.md),
[verification](docs/ace/validation.md), and the current increment at the top of
[remaining work](REMAINING_WORK.md).

The owner explicitly excluded usefulness/benchmark work and production-readiness
work from this increment. Those gates remain unchanged; no full suite, full
benchmark, paid model run or new production infrastructure was executed/added.
This scoped UI request overrides older console-freeze notes only for this work.


2026-11-05 reusable R08 benchmark pipeline: **CONFIRMED DONE within small-fixture
verification bounds; public benchmark results remain UNMEASURED.** The audit
confirmed/skipped 39 existing evaluation/oracle/converter checks and 82
writer/retrieval/assembly checks. New `agent_context.benchmarks` composes the
existing API/SDK, outbox/worker, ingestion, assembler, legacy retriever, providers,
retry/metering, packing and cosine components. It adds pinned/local acquisition,
streamed native LongMemEval/ConvoMem/LoCoMo and normalized QA adapters, declarative
experiments, isolated scratch-store ownership, replay clocks, six fair methods,
ground-truth scoring, bounded requests, resumable private artifacts and reproducible
JSON/Markdown/hypothesis reports. Source labels never enter generation; optional
judge results bind their exact inputs. Costs/latencies distinguish setup, query,
judge, retries, missing usage and archived attempts; no fabricated zero dollar
costs. Sampling-limit changes reuse immutable raw inputs. Normal runtime clocks,
the UI, original converter and synthetic demo remain preserved.

The user explicitly requested **no full or costly benchmark execution**. Tests
therefore use small synthetic native-format/normalized fixtures, mocked providers
and real isolated local databases, including the installed CLI/staged workflow
and zero-call resume. See [benchmark guide](docs/ace/benchmarks.md),
[validation](docs/ace/validation.md) and `REMAINING_WORK.md` for evidence and exact
limits. LoCoMo's actual case-sensitive documentation/license paths are now
verified, but no public scores were measured. LongMemEval oracle/s/m, ConvoMem
raw/premixed and LoCoMo text/captions are supported inputs; interactive
MemoryArena/StateMemBench/handoff environments and official evaluator equivalence
are not claimed. Use normalized offline exports only where their reference/data
license is supplied. Full-corpus quality, ablations, cross-provider proof and
production-system R09/R10 gates remain open. The earlier three increments were
pushed through `cec34e8` and passed GitHub CI; this new pipeline increment remains
local until separately published.
Final local verification: **537 tests passed, two paid live checks skipped, one
legacy live-UI case deselected (22.22 s), Pyright clean**. The source-fingerprinted
verification record is `docs/ace/results/benchmark-pipeline-verification-20261105.json`.

2026-11-05 R08/R09 verification increment: **PARTIAL overall**. Existing core,
R07 recommendation checks, task/CAS/mandatory packing and handoff verification
were preserved. Reproduced gaps were fixed in the existing evaluator: obsolete
source reports are rejected, all six baselines have equal source/citation repair
policies, query embeddings and summary byte budgets are correct, repeated seeded
trials and failures/usage/provenance are recorded. Final v5 reports contain
**36 answer trials across 500/4000-byte allowances; all six methods pass all
three trials at both budgets**. There is no demonstrated task-success advantage.
ACE used fewer answer prompt tokens than full history; rolling summary used
fewer than ACE, and ACE answers were slower in this probe. Worker chat usage is
separate; total embedding/dollar costs and public-data generalization remain
unmeasured. Earlier rubric/summary failures are retained. Public metadata confirms
LongMemEval is available but **NOT YET RUN**; ConvoMem's tracked converted subset
is not a versioned QA benchmark. See the exact reports and method limitations in
the new `REMAINING_WORK.md` increment and `docs/ace/validation.md`.

Security testing also reproduced a private-session project-access bypass.
Trusted project metadata is now persisted immutably on Sessions and rechecked
by retrieval, assembly and source evidence, including after grant removal.
Unknown old bindings fail closed. A versioned metadata-only dry-run/apply/rollback
tool reuses authoritative outbox identity; real-store migration/retry/rollback
and HTTP negative tests pass. Three sessions in the isolated benchmark stack
were backfilled; the user-facing database was not migrated.
Eight competing graph-binding races also pass; comparisons hold the Session node
write lock before reading binding fields. The final rebuilt worker's six-check
upgrade proof is `docs/ace/results/session-binding-upgrade-20261105.json`. This
does not close the distributed graph-fencing requirement. SDK basic calls
remain compatible with the older console API (observed 422 before, 200 after).
These bounded fixes are **CONFIRMED DONE — SKIP**, backed by **506 regression
tests passed, two opt-in live tests skipped, one legacy live-UI case deselected
(17.65 s), and clean Pyright**. Independent live upgrade evidence is recorded
separately in validation.md. Whole-project completion, public benchmarks,
cross-provider and production reliability/security/recovery gates remain open.
These earlier increments were subsequently approved, pushed through `cec34e8`
and passed GitHub CI. The newer benchmark-pipeline increment above is local and
has not yet run on remote CI.

2026-11-05 task-state increment passed end-to-end verification. Existing
handoff/host/replay primitives passed 23 focused tests and were preserved.
`WorkState`, `TaskStateService` and `TaskCandidateSource` now reuse the existing
versioned snapshot collection/CAS, bind tasks to authenticated projects/events,
protect user-approved requirements from agent changes, retain verified outcomes,
and assemble an atomic mandatory current-task section. SDK/HTTP tests verify
old-handoff rejection, latest requirements, cancellation, artifact changes,
tiny-budget failure, scope/selected-reason trace and consistency watermarks.
Final regression passed **480 tests, two opt-in live tests skipped, one legacy
live-UI test deselected (16.37s)**; Pyright clean. Separately, real API/worker
continuation passed all seven checks with Bolt E4B and Lightning 30B: latest
Spanish requirements, X/Y verified completion, cancelled-step exclusion, correct
next audit, receipt recovery without repeat execution, unknown-outcome refusal
and expired-handoff refusal. See `continuation-c404a96f34ed.json` (55.00s pytest)
and the actual changed-artifact refusal in `artifact-check-2eed7ca74225.json`
(9.09s). The first Mistral account-404 attempt is retained as a failed report.
The bounded private state/packing/resume/independent-host behaviors are
**CONFIRMED DONE — SKIP**. Cross-provider, broad comparative utility and
distributed production/crash/restore gates remain open. No UI expansion or
arbitrary external exactly-once transaction guarantee is implied.

2026-11-05 R01/R05 increment after inspecting `6c76b13`: existing private
scope/lifecycle/packing behavior was confirmed (26 focused real-store tests)
and skipped. The search alias and missing evidence span/trust fields were
reproduced before changes. Runtime now combines native authorized lexical and
semantic scoring using the existing embedding provider/vectors, distinct
paginated search, effective-time history, and bounded exact source excerpts.
History never becomes current instruction; privacy fences apply to every page.
Current conflicts remain withheld even across the source candidate limit.
The first full regression passed 474 tests with one legacy live-UI case
deselected and Pyright clean; later conflict checks passed 29 focused tests.
The isolated real API/worker/NVIDIA path passed record → availability →
new-session semantic search → source spans → assembly; see
`docs/ace/results/retrieval-live-20261105.json` and `REMAINING_WORK.md` for exact
evidence/limits. These tested behaviors are **CONFIRMED DONE — SKIP**;
R01/R05 remain partial for task/current-state integration and broader scope/load
gates. No shared-database or production-performance claim is made.

2026-11-04 evidence-first audit at `e55fb5a`: existing core/event/private-scope/
packing/handoff/API/primary-privacy paths were traced and their unit/real-store
tests passed. They are **CONFIRMED DONE** only within those existing boundaries
and are skipped; see `REMAINING_WORK.md` for exact commands and open gates. The
baseline found a fake-launcher readiness race (test-only fix) and confirmed the
saved demo's keyword-based success oracle could accept a refusal. R07 now adds
typed recommendation assessment with independent quote/choice/source checks.
Fresh real-service verification at `9ad2d52` delivers the actual final decision;
the current verifier also rejects the preserved refusal. See the new verified
and negative reports in `docs/ace/results/`. The pre-limit literal-retrieval
starvation defect is reproduced and fixed; semantic/task/history/search parity
remains open. No production or full task-state completion is inferred from the
historical six-flag reports.

| Phase | Current known status as of blueprint | PR/commit, tests, evidence |
|---|---|---|
| 0 — baseline audit / ADRs | Baseline preserved at `3e2454e09deb12aa68c90e76a4948c221d7974b2`; ADRs recorded; comparative model metrics still pending | `docs/ace/architecture.md`; original 292 offline tests and Pyright passed |
| 1 — authenticated event intake + feedback | Live NVIDIA event-to-context feedback verified; immutable derivation consent, trust-separated evidence and recovery tests added | `docs/ace/validation.md`; live host and Compose functional probes |
| 2 — retrieval adapter/guardrails | Private lexical/semantic ranking before LIMIT, effective-history search and bounded exact evidence verified; physical isolation required; task-state and broader shared-scope/load gates pending | `agent_context/retrieval.py`, `assembly.py`, `governance.py`; real-store retrieval/search/privacy tests; `retrieval-live-20261105.json` |
| 3 — context assembler | Private lexical/semantic candidates plus mandatory current task state, deterministic conflict/budget safety, selected reasons, auth scope and watermark verified; comparative utility still pending | `assembly.py`, required `TaskCandidateSource`; real-store/HTTP tests; `continuation-c404a96f34ed.json` |
| 4 — handoff/task state | Canonical bounded task revisions, user-approved changes/cancellations, verified progress, stale/reconciled handoffs and artifact refusal demonstrated with an independent two-model host; cross-provider/distributed guarantees pending | `task_state.py`, `handoff.py`; `continuation-c404a96f34ed.json`, `artifact-check-2eed7ca74225.json`; failed attempt preserved |
| 5 — SDK/API/live demo | Research host, new console, local initializer, Compose stack, CI and `run.sh` local bootstrap implemented; production deployment remains pending | `docs/ace/operations.md`; launcher configuration/orchestration tests and fresh-stack verification recorded in `docs/ace/validation.md` |
| 6 — reproducible comparative evaluations | Six-baseline, one-scenario live probe recorded; no superiority claim; public datasets, multiple trials, ablations and total billing remain pending | `evaluation.py`; `docs/ace/results/baseline-probe.json` preserves the first-pass citation failure |
| 7 — production hardening/governance | Revocation replay fences, derivation consent, export, lease-aware scoped primary erasure, safe logs and auth-source isolation implemented/tested; distributed guarantees, backup retention, TLS deployment and load/chaos gates remain pending | `privacy.py`, `governance.py`; `docs/ace/operations.md` and validation evidence |
| 8 — optional adapters/research | Not started | To record |

Optional web search is now wired into the research console through a bounded
Brave Search adapter. It is disabled with clear setup guidance when no key is
configured, and leaves the sample-document workflow available. Search snippets,
public source links and citations use the existing authenticated event/read
pipeline. Provider/UI/replay behavior is tested with mocked search responses;
live Brave validation is explicitly deferred until `BRAVE_SEARCH_API_KEY` is set.

Project identity fix: event-to-session bridging now carries the immutable,
authorized stream project ID as a tenant-scoped host binding. Writer policy v2
uses that binding for every ACE PROJECT write; model labels never select graph
identity. Extraction-v4 keeps project facts project-scoped. Unbound project cues
fail closed, while legacy imports retain their existing scope resolution. This
does not rewrite previously mis-scoped contexts; reassert them after updating.

Host answers can cite authorized assembled memory using `memory:<context-id>`
with evidence episode IDs, independently of document reads. Citation validation,
bounded repair and cached-answer checks reject invented or no-longer-current
memory sources; web-required research still needs a verified document citation.
New UI sessions clear prior input/result/context/search state while retaining an
explicit saved handoff. Focused unit and UI checks cover these paths; this does
not assert universal model answer correctness.

**Maintenance rule:** When a phase is finished, link the code diff/PR, tests executed, benchmark artifact, migration notes and remaining caveats. Correct "verified existing" facts if the repository changes. Update this document alongside code rather than keeping implementation history exclusively in chat memory.

---

## 17. Primary references and repository entry points

### Existing repository
- [GitHub repository](https://github.com/praveen-solanki/Context-Graph)
- [Existing README / setup / ingestion and retrieval](https://github.com/praveen-solanki/Context-Graph/blob/main/README.md)
- [Repository coding rules](https://github.com/praveen-solanki/Context-Graph/blob/main/AGENTS.md)
- [Ingestion pipeline](https://github.com/praveen-solanki/Context-Graph/blob/main/src/context_graph/pipeline/orchestrator.py)
- [Conversation spans and Episodes](https://github.com/praveen-solanki/Context-Graph/blob/main/src/context_graph/domain/conversation.py)
- [Context models and provenance](https://github.com/praveen-solanki/Context-Graph/blob/main/src/context_graph/domain/context.py)
- [Concept resolution](https://github.com/praveen-solanki/Context-Graph/blob/main/src/context_graph/pipeline/resolution.py)
- [Writer scope and authority policy](https://github.com/praveen-solanki/Context-Graph/blob/main/src/context_graph/pipeline/policy.py)
- [Retrieval tester](https://github.com/praveen-solanki/Context-Graph/blob/main/retrieval_tester/retrieval.py)
- [Schema-planned graph retrieval prototype](https://github.com/praveen-solanki/Context-Graph/blob/main/retrieval_tester/context_tool.py)
- [Session chat orchestration](https://github.com/praveen-solanki/Context-Graph/blob/main/retrieval_tester/chat.py)
- [End-to-end ingestion tests](https://github.com/praveen-solanki/Context-Graph/blob/main/tests/e2e/test_ingestion.py)

### External research / specifications
- [Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)
- [Anthropic — Effective harnesses for long-running agents](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents)
- [Anthropic — Harness design for long-running apps](https://www.anthropic.com/research/harness-design-long-running-apps)
- [OpenAI — Context engineering with sessions](https://developers.openai.com/cookbook/examples/agents_sdk/session_memory)
- [OpenAI Agents SDK — Sessions](https://openai.github.io/openai-agents-python/sessions/)
- [LangGraph — Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [Letta — Agent memory architecture](https://www.letta.com/blog/introducing-the-agent-development-environment/)
- [Mem0 — GitHub](https://github.com/mem0ai/mem0)
- [Model Context Protocol — Server tools spec](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [OWASP — Agentic Top 10 for 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [LoCoMo](https://arxiv.org/abs/2402.17753)
- [LongMemEval](https://arxiv.org/abs/2410.10813)
- [MemoryArena (ICML 2026)](https://proceedings.mlr.press/v306/he26am.html)
- [StateMemBench (2026)](https://arxiv.org/abs/2608.19652)
- [Handoff State Continuity Benchmark (2026)](https://arxiv.org/abs/2610.36523)

**Final design principle:** the graph is replaceable infrastructure. The product is the quality, correctness, safety and measurable utility of the **context supplied to an agent at the moment it needs to act**.

2026-11-06 presentation-only increment: requested HIG/motion design skills installed
with pinned provenance; existing conversational UI refined without replacing its
workflow. CONFIRMED DONE within 28 focused UI checks, strict presentation typing,
and desktop/mobile Chromium inspection. [Design evidence](docs/ace/ui-design.md).
