# Screenshot follow-up — 7 November 2026

Baseline `685d04c`. Each screenshot report was checked independently; uncertainty
was not treated as proof that project scope or model validation should be relaxed.

| Report | Verification and disposition |
| --- | --- |
| Chat updates/recall/simple memory prompts failed; retry did not help | The same three scenario types completed with citations through a bounded isolated real-model/API/worker/graph workflow. This cloud instance also had stopped Mongo/Neo4j containers and a repeatedly restarting API/worker with `ServerSelectionTimeoutError`. Services were restored without recreating volumes, and readiness returned. This demonstrates a local dependency failure; the original failure in another runtime cannot be established from the screenshot alone. |
| Recovery navigation crashes after a failed request | Confirmed: four reproductions raised the widget-already-instantiated error. `clear_view()` now clears application data immediately but defers widget state resets until the safe boundary before rendering. Recovery, callback navigation, URL navigation, routing and cancellation use the same reset mechanism. |
| New conversation works when idle | Confirmed working and preserved; existing regression remains green. |
| Automatic routing asks for selection and leaves a request unsaved | Clarification is intentional when intent is uncertain or the provider fails. Scripted Atlas/Cedar names, aliases, approved goal hints and explicit switches resolve correctly. Low confidence, forged IDs, invalid quotes and multiple-project updates still fail closed. No name-occurrence shortcut or confidence relaxation was introduced. A live routing probe returned a valid clarification, which is not evidence of a resolver exception or a universally correct semantic decision. |

## Changes

- Database services use the same `unless-stopped` restart policy as API/worker.
  It is also applied to this instance's restored containers. It supports restart
  after an unexpected container/daemon interruption; it does not override manual
  stops, prevent cloud suspension, guarantee uptime or replace dependency health.
- Recovery no longer mutates `ace_source_mode` or other widget-owned state after
  widget construction. Starting a recovery conversation preserves durable history;
  retry keeps the original ID and frozen sources. Cancelling an unsent routing
  request preserves source choices.
- Known failure classes now receive sanitized, actionable UI messages: service
  connectivity/5xx, provider availability, model validation, timeouts, rate limits
  and terminal worker state. Raw response, URL and exception content are not shown.
- The SDK raises `EventProcessingStopped`, a backward-compatible `RuntimeError`
  subclass, for a dead-letter event. The UI explains that retrying a chat cannot
  replay stopped processing; operator review/replay remains required. No permission
  bypass, automatic replay or deletion of recorded requests is added.

## Verification

The [verification artifact](results/reported-recovery-20261107.json) lists test IDs,
source hashes, browser observations, exact capped live outcomes and limitations.
**89 distinct focused checks passed** (69 unit/UI and 20 real-Mongo workspace/API
checks); changed code/tests have zero strict Pyright errors/warnings.
Focused coverage includes all three source modes, failure/retry/navigation,
cancellation, URL project switching, prior history preservation and routing guards.
Real Mongo workspace/API checks preserve existing intake, task and SDK behavior.
Chromium clicks the actual recovery button after a synthetic failure: the session
changes, failed-request content clears, the composer is enabled and no Streamlit
exception appears. Browser fixture: zero model calls/database writes.

The first isolated live workflow passed memory update and fresh-session recall,
then reached its 24-request test cap on the simple-memory case. That cap is kept as
an incomplete observation, not a code regression. A separate simple-memory check
passed with 13 attempts. Alongside three preliminary model-only requests, 40
provider attempts were made; billing was not measured. The preliminary answer-only
probe did not reproduce the complete host prompt/branch and is not used to claim
chat failure or success. Live synthetic checks are not public benchmark accuracy.

No full suite or broad benchmark ran. Original Context-Graph remains unchanged. No synthetic test data was added to
existing application projects. To deploy matching UI/backend/restart settings after
pulling, run `./run.sh --skip-demo`.
