# Answer generation and background context updates

The conversational UI no longer waits for extraction or project planning. This
uses the existing Mongo event/outbox document, ingestion pipeline, task snapshots
and worker. No Redis, alternate queue, database, dependency or detached browser
task is introduced.

## Request and worker paths

1. The existing project router resolves an authorized project. The user message
   is durably recorded with its original ID and `background_updates=true`.
2. Explicit targeted corrections apply the existing revocation fence before
   answering. Ordinary extraction and planning are deferred.
3. The host reads bounded pending user assertions for this owner/project, then
   assembles saved context. Reading pending inputs first avoids a gap when the
   worker advances availability during assembly. The current message is already
   in the request and is not duplicated in the pending payload.
4. The existing answer/tool/citation loop produces and durably records the answer.
   It does not call the task planner or wait for either event's availability.
   Pending assertions are data, never system instructions; later corrections
   take precedence. Used assertions have inspectable `event:` citations.
5. Independently, the worker claims the durable stream, runs original extraction,
   and calls `ProjectMaintenance`. The latter reuses the existing quote-validated
   `plan_task`, TaskStateService CAS, idempotency and tool-outcome verifier. Only
   successful extraction and maintenance advance the availability watermark.
6. A quiet UI fragment polls durable status while work is pending and refreshes
   the project panel. Polling failure or dead-letter state does not disable chat.
   Failure notices remain available; the app does not pretend a failed update
   succeeded or restart terminal work without operator authorization.

The model response, source reads, safety checks and durable appends still take
time. This change does not stream answer tokens, guarantee a response deadline,
reduce total model work or establish a measured latency improvement. Project
routing and ordinary model/tool work remain on the request path.

## Authority, ordering and bounded context

- Pending input lookup requires VIEW and exact tenant/user/project identity.
  Only authenticated user messages and corrections above the availability
  watermark are included. Assistant prose and tool results cannot become user
  assertions. Derivation opt-out is respected across conversations.
- The default pending payload is 2,000 serialized item bytes and 20 events;
  the service bounds it to 16 pending streams, 64 events and 16,000 item bytes.
  Hosts configure `DemoSettings.recent_context_bytes` (256–8,000). Complete
  rendered requests still obey the existing conservative model token budget.
  Processed streams cannot crowd pending streams out of the window.
- Oversized newer inputs are not replaced with older facts. Incomplete windows
  carry `truncated=true`; the host is instructed to ask when missing context
  could invalidate a saved fact. This is bounded working context, not a promise
  of exhaustive recall under an arbitrarily large backlog.
- Intake snapshots the actor's permissions and privacy revision in internal
  event metadata. The worker intersects original permissions with current
  configured grants and reauthorizes project access. A later stronger token
  cannot elevate an old event. There is no client-supplied authority field.
- Pending inputs recorded before a privacy revision are conservatively withheld
  from automatic answer context, with truncation disclosed. Their source history
  remains inspectable. This prevents raw pending text from bypassing a derived
  memory revocation; unrelated old pending inputs can also be withheld. Reassert
  needed facts after the privacy change. Quarantine and mid-read privacy changes
  fail closed.
- Canonical recorded task state can be assembled before graph availability only
  when the host explicitly requests `include_recorded_task`. Source, ownership,
  evidence, expiry, revocation and required-item budget checks still apply.
  Answers record the task revision actually assembled even if maintenance races
  the host's initial task read.
- Worker user-intent ordering follows server receipt times from bounded existing
  task revision history. Later tool receipts cannot reorder user requirements.
  An overtaken older request is retained as memory rather than overwriting a
  newer accepted plan. Disjoint changes from out-of-order conversations are not
  automatically semantically merged; restate an unapplied change if necessary.
- Only authenticated agent tool receipts update verified completion, including
  receipts arriving after the user event was processed. Retry reuses existing
  intent revisions/receipts; no second answer or external action is generated.

## Deployment and integration

Update API, worker and UI together, then restart/rebuild with the existing
launcher:

```sh
./run.sh --skip-demo
```

The existing model, auth bindings, Mongo and Neo4j settings are sufficient.
`WorkspaceAssistant(background_updates=True)` enables the fast host path; the UI
selects it automatically. Legacy SDK/host calls retain synchronous defaults.
Lower-level answer adapters can use `DemoSettings(background_memory=True)`;
project-maintenance events must also be flagged explicitly. Pending lookup is
`POST /v1/context/recent` (`RecentRequest` → `RecentContext`), exposed as
`AgentContextClient.recent_context`. Persisted answers carry only the pending
event references they actually cite, so evidence links survive refresh/retry.

The worker must remain running for durable context to converge. Closing the page
does not discard already recorded work. Unsent browser drafts and interrupted
answer generation are not server background jobs; use the existing recorded-turn
retry. Existing leases, bounded attempts, privileged dead-letter replay and task
revision/session quotas remain in force. No historical migration is required:
old unflagged events are not retroactively replanned, and missing original grant
snapshots do not confer new maintenance authority. Distributed graph fencing,
global provider quotas and production-readiness gates remain unchanged.

## Verification

Before changes, focused reproductions failed because pending lookup did not exist
and the host had no background mode. New focused checks use disposable local
Mongo databases, the real API/SDK/task/outbox services and deterministic providers.
They cover a blocked worker, immediate cross-chat corrections, citation/history
recovery, no-planner/no-wait answers, maintenance failure, authority snapshots,
late receipts, ordering/replay, task-revision races, bounds and privacy fences.
Streamlit AppTest covers event evidence and successful/failed quiet refresh.

See [the verification record](results/background-processing-20261107.json) for
exact commands/counts. No full suite, live model calls, statistical benchmark or
live-provider latency measurement is claimed by this increment.
