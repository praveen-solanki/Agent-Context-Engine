# Automatic project routing: design, failure handling and verification

Owner-authorized scope: identify existing personal projects across conversations,
create a private owned project only for a clear new undertaking, preserve stable
IDs and current context, and retain explicit user control. Existing event streams
remain immutable and project-bound. No benchmark or production-readiness expansion.

Before implementation, the audit confirmed that project grants, scoped event
streams, current task CAS, evidence, private retrieval and manual navigation already
exist. Reuse them. Missing: an owned project directory, safe creation/delegation,
semantic routing before persistence, ambiguity handling, and aliases/renaming.

## Failure cases and implemented handling

| Failure case | Handling and verification target |
|---|---|
| Same project in a fresh chat, nickname or paraphrase | Resolve against authorized names/aliases/descriptions; reuse the stable ID and current task/memory. |
| Case, whitespace or Unicode presentation differences | Normalize names with Unicode NFKC/casefold/space normalization for identity collision detection; retain display text. No automatic fuzzy merging. |
| Two projects with similar or identical generic names | Ask which project; do not choose on a weak score. Distinct new projects need a distinguishing name. |
| A new title already exists, including a concurrent create | Atomic directory revision and idempotency checks; refresh and resolve against the new directory, never silently overwrite/duplicate. |
| Two concurrent differently named descriptions of the same undertaking | CAS rejects the stale create; bounded resolver retry sees the winner. Semantic identity is still model-dependent, so ambiguous cases require selection. |
| Hypothetical, example, quoted instruction, greeting or general preference | Do not create a project. Use Personal space for an unbound general chat, or retain the current conversation for nonproject follow-up. |
| New conversation begins with “continue” and several possible projects | Ask; a previously viewed sidebar project is not evidence of user intent. |
| Explicit project switch within a bound conversation | Open a new bound conversation and retain the old history; never change the identity of an existing stream. |
| One message updates several projects or mixes unrelated project facts | Ask the user to choose/split the message before any event, extraction, task or tool execution. No partial assignment. |
| Low confidence, missing evidence quote, invented project ID or malformed proposal | Reject/clarify without event or memory writes. Model output cannot grant access. |
| Model/provider unavailable, timeout, over-budget input or oversized directory | Keep the unsent request for retry/manual selection. No fallback to a guessed project. Bound model calls and creation retries. |
| Explicit manual selection | Bypass semantic routing and clearly label the override; the user can return to Automatic. Memory corrections stay locked to their actual source project. |
| Rename, alias changes and alias collisions | Preserve ID, retain previous title as an alias; CAS/version and normalized alias collision checks prevent hijacking. Bound alias count; do not silently drop names. |
| Cross-user/tenant name collision or guessed ID | Directory, lookup, membership and writes bind the authenticated tenant/user. Never search another owner's metadata. |
| Agent tries to create projects or choose another user | Deny. Only an authenticated user can create private projects; delegate only to a known configured host actor in the same trust partition. |
| Read-only user/token or removed host grant | Existing VIEW/ASSERT/CORRECT checks still apply. Missing permissions fail before allocation or ingestion. |
| Retry, double submit, refresh or network failure after creation | Creation idempotency keys and a frozen browser routing choice prevent duplicate creates/wrong-session retries. Once recorded, the server stream preserves the binding. Unsent drafts are not durable across a full browser reload. |
| User leaves an interrupted request or changes projects | Keep requests bound to their original owner/project/session; never replay into the newly selected project. |
| Incorrect association discovered after persistence | Do not rewrite immutable history or pretend moving the UI moved memory. Show the actual project; start the corrected conversation and use existing evidence/correct/remove controls on the old context. Automatic bulk moves/merges are deliberately unavailable. |
| Existing data was already misclassified | Do not silently migrate/delete it. Existing project-binding repair and evidence/correction paths remain explicit. |
| Project metadata persists after erasure/export | Include the new owner directory in primary-data export/erasure; privacy quarantine denies routing/creation immediately. |
| Project-specific facts stored as USER memory or a question saved as a fact | Parallel scoped fixes verify source-project provenance and asserted evidence while retaining true personal preferences. |
| Project registry quota, alias quota or immutable session cap | Return a clear bounded failure/manual alternative; never truncate the directory or silently lose facts. |

This matrix covers identified failure classes, not a claim that every possible
semantic ambiguity is automatically decidable. Verification evidence and remaining
limits are recorded below as each slice passes. No full suite/full ingestion run.

## Verification status

**CONFIRMED DONE within the tested bounds.** Runtime wires the owner directory
into the existing API; the SDK and actual Streamlit page resolve before event
recording. A successful scope switch opens a separate bound stream. Corrections
and Add to plan remain explicitly bound to their displayed project. Research
sources selected for a request are frozen through routing/retries.

**79 distinct focused checks passed across scoped runs:** 38 unit checks for new
routing/assertion guards and affected extractor/project-binding behavior, 23
real-Mongo/Neo4j API/store/scope checks, and 18 affected/new UI checks. Strict
Pyright on changed code/tests is clean. A four-second delayed-load Chromium check
also verifies stale heading/chat/task content stays hidden during a project
switch. Tests use disposable stores and mocked providers. No full suite, full
application run or public dataset evaluation was performed.
See [verification record](results/automatic-project-routing-20261105.json).


A separate capped probe made three live model-only requests with no database writes.
Existing-project and multi-project proposals matched expectations. The new-project
proposal failed the conservative ID/confidence guards; explicit **Create and use
project** confirmation is implemented and tested without weakening those guards.
Billing was not measured. This is not a semantic accuracy benchmark.

## Use and configuration

Update API, worker and UI together with `./run.sh --skip-demo`.
**Automatic** is the default project-routing mode. A clear active new project
creates a private directory entry; existing names, aliases and semantic matches
reuse the existing ID. General unbound conversation uses **Personal**, which does
not create a task. A project-less owner can bootstrap Personal when a trusted host
is configured. **Selected project** bypasses matching, and choosing a project in
the sidebar enables this override until Automatic is selected again.

Ambiguity presents authorized choices, rephrasing and cancellation before any
conversation/memory writes. For an uncertain new undertaking, copy its exact name
from the message and select **Create and use project**. A multi-project update requires rephrasing one project
at a time. Provider failure offers manual choice without discarding the unsent
text. Owned projects support explicit conversational renaming and a **Project name
and aliases** form; renaming preserves the ID and old title as an alias.
Configured legacy projects keep their original grants and IDs. Their approved
current goal is available as an identity hint (expired/revoked hints are excluded).
Editing a legacy display name/aliases creates an owner metadata overlay; it never
changes the configured ID, event binding or task identity. Names/aliases cannot claim another
project's name/ID. Personal and the internal `ace-` creation-key namespace are reserved.

`ACE_PROJECT_ROUTING_MATCH_CONFIDENCE` (default 0.9),
`ACE_PROJECT_ROUTING_CREATE_CONFIDENCE` (0.95),
`ACE_PROJECT_ROUTING_MAX_INPUT_BYTES` (16000),
`ACE_PROJECT_ROUTING_RESPONSE_TOKENS` (1400), and
`ACE_PROJECT_ROUTING_DIRECTORY_RETRIES` (2) bound matching and retries. Directory
capacity is 64 owned entries (including Personal); aliases are limited to eight.
Oversized directories/low confidence require manual selection rather than silent
truncation. Model confidence is a heuristic, not a correctness guarantee.

## Authority, compatibility and remaining limits

The sole new collection is `ace_projects_v1` in the existing owner database. Only
an authenticated user with VIEW/ASSERT can create a private owned project;
CORRECT is required to edit it. The server validates a delegated host against its
configured agent principals for the same tenant/user. Other agents and other
owners gain no access. Dynamic membership augments existing grants only for the
owner and selected configured delegate. Existing permission checks, physical
trust partitions, immutable event bindings and canonical task CAS are retained.
Directory metadata participates in owner export, quarantine and primary erasure.
This is not a new multi-tenant deployment guarantee.

Project-origin USER memory with unclear personal applicability is now restricted
to its source project. Proven `personal_scope=True` traits/preferences/constraints
and unbound legacy personal memory remain usable across projects. No old records
are deleted or guessed into new scopes: reassert an old preference explicitly as
personal if it was previously saved without this distinction. Existing false
unknown facts remain inspectable/removable; new extraction requires asserted
source evidence and rejects question/assistant-refusal support. Explicit user
statements of pending/unknown status remain valid.

Semantic routing and extraction can still be mistaken. Correct the selection
before saving where possible. After recording, existing history is immutable;
start the correct conversation and use evidence/correction/removal on old memory
(and the existing task update/reconciliation API for a wrongly updated plan).
There is no automatic bulk project merge, transcript move or rollback of verified
tool history. A browser/server restart can lose an **unsent** routing draft and
unread research selections; already-recorded pending turns recover their frozen
binding from the server. The directory matches names/aliases/descriptions rather
than embedding an unlimited chat history. Statistical live-model accuracy, load,
backup/restore and production gates remain unmeasured and unchanged.

