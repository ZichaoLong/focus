# Focus Web submission times and passive diagnostics

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-prompt-timing.zh-CN.md`.

## Time sources and boundaries

Before the first HTTP yield, the ordinary prompt browser entry records `Date.now()`: the original browser's submission
initiation time, not proof of delivery. This covers existing-thread input and the first prompt of a new thread.
The main view shows only the time; expanding it reveals the source labels, full local date and milliseconds. The source clock belongs to the original device;
other devices format it in their own timezone. Subtracting browser and server clocks cannot establish one-way latency.

`codexRecordedAtMs` comes from the per-userMessage `startedAtMs` supplied by app-server, falling back to that item's
`completedAtMs`. Its detail label is “Codex recorded input”; it is neither Focus/browser receipt time nor model-provider receipt.
It can stand alone when browser time is absent. Missing times stay absent. A whole turn's `startedAt` is no longer used
for user rows, so later steers do not inherit the first input's time. Assistant times keep the
[transcript window contract](./focus-web-transcript-window.md#reply-times-and-long-replies).

Focus records `service_received` after request validation and before preparation, plus stages on the actual path:
preparation, worker, metadata/goal RPC start and return, input RPC start and return, matching user-message observation,
and settlement. These are observations in Focus. RPC start is not app-server's internal receive time; RPC return does not
prove model-provider receipt. Stages carry wall-clock milliseconds and monotonic elapsed milliseconds within one trace.
Durations use only the latter. The browser also measures its wait for a result or error with a local monotonic clock.
Scheduling and RPC waits must not be presented as pure network latency.

“Focus received first output” is the local time when Focus first observes nonempty reasoning or reply text on an existing
app-server notification in RuntimeLoop. `FocusWebProjection.observe_prompt_notification` supplies an internal passive hook
before presentation coalescing, without emitting per-token diagnostic wire events. `WebPromptTimingRecorder` alone owns
the observation. Text/reasoning deltas and the first nonempty text/reasoning in live item or turn notifications qualify;
empty items, heartbeats, reasoning separators and tool stdout do not. This needs no `response.created` and is not the
model's original first-token time. Ordinary history reads never reconstruct a first receipt time.

Association requires an actually observed new `turn/started` after the input RPC began, whose first user item's exact
`clientId` matches this submission and precedes the first output. Additional inputs, native start-or-steer races, missing
start events and output preceding input must not borrow the turn's output. Only the first qualifying output is saved,
with kind, turn/item IDs, wall-clock time and monotonic elapsed within the same trace. Later tokens do not write diagnostics.
Disconnects, thread close/unload/revert, observation eviction and service stop end pending observations. Saved first output
survives subsequent disconnects and restarts. Old records show “Not recorded”; a continuing observation without output shows
“Not yet observed”; gaps show “Observation interrupted”; missing exact submission association shows “Cannot associate”;
an observed end without output shows “Not observed.” None establishes failure or permission to retry.

Default details show “Browser submitted”, “Focus received submission”, “Codex recorded input”, “Focus received first output”,
then the submission ID. Missing first-three timestamps are not invented; the fourth shows its state when no reliable time
exists. A Codex recorded timestamp hides redundant submission results; otherwise saved evidence supplies “Focus submission
result”, with the browser result only when it differs. Missing server records show “Server record: Not found.” The three
main durations, RPC durations, stage times and internal reason codes appear only in copied diagnostics. The copied JSON
contains complete server/browser evidence, available `codex_recorded_at_ms`, same-clock `durations_ms`, and
`model_upstream.collection=not_integrated`. Codex-to-base-URL request telemetry remains uncollected; the default panel omits
that constant capability status and cannot separate the sending and receiving directions of that link.

## Persistence, association and authority

Browser `createPromptTimingStore` retains the latest 64 entries in `localStorage` key `focus-web.prompt-timings.v1`:
submission UUID, thread id, submission time, browser result/error time, wait duration, event connection losses during
that wait, and local sync version. It contains no prompt text, attachments, tokens or replayable request. Storage failure
degrades to memory with a visible hint and never blocks input. Completion, connection hello and explicit refresh may sync
metadata. Incomplete attempts left by reload and records from replaced documents are also eligible. Incomplete is not
failed and does not invent a received result.

`WebPromptTimingStore` owns `data_dir/web_prompt_timing.sqlite` on the service machine solely to preserve display evidence
across pages, devices and process restarts. `WebPromptTimingRecorder` writes Focus observations on a separate bounded
worker; the Gateway sync interface writes browser fields only. Ordinary transcript reads may persist an actually
observed exact item association. Browser claims cannot establish service receipt, result, stages, epoch or association.
The first valid service observation fixes the original time and write identity; duplicate/conflicting IDs cannot overwrite it.

For existing threads the UUID equals `mutation_id`. For a new thread's first prompt the browser generates a UUID and the
server derives `client_user_message_id=focus-web:<UUID>`. Association requires that exact client id and thread, then saves
the actual `(thread_id, turn_id, item_id)` for history that omits clientId after restart. There is no matching by text,
position or nearby time, and a copied clientId in a fork does not bind the original thread.

Diagnostic schema v2 adds `first_output` JSON. An in-place v1 column migration defaults old rows to `not_recorded` without
changing original submission times or associations. Only new submissions begin observation. Reading `pending` from an old
process or lost local observation context returns `interrupted`, not a claim that observation continues. An accepted input
without an exact initial-input association in the current process shows `unassociated`; subsequent actual events may supply
the association. Reads inspect diagnostic context only, never restoring subscriptions, querying app-server or replaying input.

The database is not a durable execution ledger, idempotency guarantee or retry authority. The existing
[single-POST/result receipt contract](./focus-web-prompt-mutation-recovery.md) and Composer settlement remain authoritative.
`unconfirmed` means no settled observation; `outcome_unknown` means the observed outcome was unknown; `succeeded` means
Codex accepted input or Focus actually observed its user message; `known_no_effect` retains the established no-effect
classification. Restart does not imply an unfinished attempt is still running. Missing records and failed queries do not
prove no delivery. Details introduce no resend action.

Missing storage is created lazily. Lock contention, corruption, unknown schemas and queue overload degrade diagnostics
without blocking input or transcript installation. Failed queries return unavailable, not a misleading empty success.
Corrupt files are not automatically replaced. Manually deleting this diagnostic database loses only display evidence.
Associated message times remain until best-effort cleanup after confirmed Web thread deletion. Unassociated entries older
than 90 days are removed during subsequent metadata sync. Cleanup failure does not reverse completed deletion; another
device's unsynced local entry may later upload as a browser observation. Browser retention is independent: clearing site
data or exceeding 64 entries evicts local records.

## Wire, deferred reads and overhead

Wire v37 introduced these interfaces; v38 requires `first_output` in diagnostic records. Service and assets deploy together:

- Optional `X-Focus-Prompt-Id` and `X-Focus-Submitted-At` headers on prompt and new-thread POSTs. Existing-thread identity
  must equal the body mutation id. The prompt body and effect admission are unchanged.
- POST `/api/prompt-timings`: closed `{records:[{submission_id,thread_id,submitted_at_ms,browser}]}`, at most 32 per batch.
  Browser fields are limited to `completed_at_ms,elapsed_ms,result,disconnects`. This metadata-only route calls no runtime
  effect port, does not renew auth sessions, and uses existing document authentication and Origin/CSRF rules.
- GET `/api/prompt-timings/{submission_id}` returns `{record:PromptTimingRecord|null}`.
- `first_output.status` is `not_recorded|pending|observed|interrupted|unassociated|not_observed`.
  `observed` has exactly `status,at_ms,elapsed_ms,turn_id,item_id,kind`, where `kind=text|thinking`;
  other states have exactly `status,reason_code`. Browser sync cannot submit or overwrite this server field.
- GET `/api/threads/{thread_id}/prompt-timings` returns the latest 32 `{records:PromptTimingRecord[]}`, including attempts
  without a message. Both GETs read saved observations, require the current authenticated document, use
  `Cache-Control: no-store`, and never query app-server.
- Global `prompt_timing_changed` carries only submission id in detail, optionally with thread id. Ordinary projection
  advances coordinates without reloading the transcript. Only an expanded submission list refreshes automatically;
  individual details retain the snapshot from their last read.
- User rows may carry `clientUserMessageId`, `codexRecordedAtMs`, and `promptTiming={submissionId,submittedAtMs}`.
  Ordinary history reads attach summaries in bulk, without per-message GETs.

Details read diagnostics on expansion or explicit refresh, do not reread on milestone notifications while open, and do not
poll while closed. “Refresh” and “Copy diagnostic details” remain available. A failed refresh retains the previous snapshot
and labels the failure rather than presenting stale data as fresh. Attempts without messages remain accessible in the
initially collapsed “Submission history.” Each trace holds at most 20 stages; the writer queue holds
512 entries, memory retains 256 traces and 512 observed item keys. Repeated milestones do not write again. No tokens,
output text or individual stream deltas are recorded. First-output context retains at most 256 turns. A normal submission
emits at most four submission milestones and one first-output observation result notification.
An expanded list coalesces events for 250ms, retains 32 entries and limits its height on mobile. Existing connection
heartbeats, operator status and mutation-result queries retain their rules; no per-prompt app-server polling is added.

## Verification and upstream evidence

Core coverage is in `tests/web_runtime/test_prompt_timing.py`, `tests/web_runtime/test_prompt_first_output.py`, `web/test/focus-prompt-timing.test.ts` and
`web/test/focus-prompt-timing-browser.test.ts`, alongside existing prompt-authority, Gateway, transcript and wire guards.
It covers unavailable local storage, lost responses, F5, cross-document sync, cross-device association, duplicate identity,
fork isolation, restart, corrupt storage, distinct times within one turn, mobile expansion, deferred GETs and no replay.

Per-item time evidence is pinned to app-server `ThreadItemEntry` and user item notifications at
[`openai/codex@c248f6d48b97eb4a2aa56147a0b11b7d763278b9`](https://github.com/openai/codex/commit/c248f6d48b97eb4a2aa56147a0b11b7d763278b9).
Deployment availability follows transcript-window capability checks. This feature changes no Codex session, thread-history
storage or configuration.
