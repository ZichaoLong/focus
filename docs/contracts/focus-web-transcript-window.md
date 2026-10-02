# Focus Web bounded transcript window

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-transcript-window.zh-CN.md`.

## Scope and owners

This contract applies to saved `history_mode=paginated` threads. Legacy threads retain
existing compatibility reads, without migration, indexing, or performance work.
Ephemeral subagent threads retain their existing detail projection.

`WebThreadOpenCoordinator` owns selection and control state. `WebThreadInspectionService`
owns document, selection, backend generation and observation admission. `transcript_window.py`
reads frozen inputs and projects items. `createFocusTranscript` owns the sole browser body
window; `createFocusPromptHistory` owns the paginated Prompt directory, while
`createFocusHistoryNavigation` retains legacy summary navigation. `TranscriptRow.vue`
owns visibility and measured heights, never history or sending authority.

## Control state and body reads

Opening/resuming a paginated thread requests `itemsView=summary`. Snapshot `turns`
contain bounded first-user Prompt summaries, alongside active-turn identity, pending
requests, settings and selection receipts. A separate authenticated
`GET /api/threads/{thread_id}/transcript` loads the body. Body loading/failure does not
revoke confirmed Composer scope. Sending requires server `hello`, not WebSocket `open`.
A proven pre-effect `web_writer_disconnected` refusal reconnects while retaining the
draft, without replaying the prompt. Unknown outcomes follow the prompt recovery contract.

The closed query permits `turn_id`, opaque `cursor`, `direction=asc|desc`, `item_id`,
`full=true|false`, `view=transcript|prompts`, and `source_cursor`. Values must be unique,
nonempty, trimmed and at most 4096 characters. An item requires a turn; full requires an
item. Source cursors require full and exclude cursor. Default reads return the latest
40 thread items chronologically. Paging uses upstream cursors, never synthetic offsets.
Prompt and search navigation target the exact item, including additional messages in the
same turn. Subsequent targeted paging stays within that turn.

Responses contain `{runtime_epoch, revision, thread_id, turn_id, view, target_pending,
turns, older_cursor, newer_cursor, full_text}`. Rows carry stable `rawTurnId`, `itemId`,
and `id=<turn>:item:<item>:<segment>`. Ordinary reads project at most 40 source items and
2 MiB encoded data. Source trees retain up to 16384 text characters, 1024 nodes and depth
12. Per-item byte allowance is the page budget minus 64 KiB, divided by 40; oversized
projections become shorter plain-text previews. Clipped content carries `contentDeferred=true`,
never parsing incomplete Markdown as full content. Terminal command/file outputs with an
exact detail locator are excluded before generic clipping: deferred output/diffs must not
consume the command, path or semantic card budget. Detailed commandActions are
also deferred to exact inspection, so repeated/quoted scripts cannot exhaust the card
budget. Full details retain the original action DTO.
Other content remains bounded.

Opening/using the Prompt directory reads `view=prompts` backwards through all userMessage
items, including additional/steer messages. Responses contain only titles of at most 160
characters plus a truncation marker. This view allows only descending, whole-thread cursor
paging. Each HTTP request reads at most four sequential pages of 100 items, returning as
soon as a page has user messages; empty pages still advance the cursor. The browser keeps
at most 200 prompts and explicitly marks this limit. Loading is visible; closing pauses,
reopening resumes. Errors preserve partial results and allow retry. Thread, epoch/access
changes and disposal cancel reads. Directory scanning never blocks opening/sending or
transfers tool/reasoning/assistant bodies to the browser; it uses no SQLite/rollout bypass.
Directory and target-scan cursor guards retain only the latest 256 cursors.
Control snapshots retain observed user titles with exact item identities. Live additions
are deduplicated by ID and survive body eviction. Legacy summary navigation is unchanged.

Rows may carry `sourceCursor`, an envelope around the upstream inclusive backwards cursor,
original turn scope, direction and page size. It grants no authority and never synthesizes
an upstream cursor. Full reads prefer rereading that exact source page and checking item/turn
identity. Without a locator, positioning uses the upstream item anchor to read a predecessor
and the target. Only an explicit old-server object-cursor rejection (`expected a string`)
falls back to bounded string-cursor pages within the turn. `target_pending=true` requests
cancellable continuation; unrelated errors never trigger compatibility fallback. Missing
items fail rather than substituting nearby content.

Successful full reads return empty `turns` and uncropped `full_text`: user/assistant text,
complete visible reasoning, or source JSON for other items. A separate selectable text view
copies the source string. Closing, identity, epoch/access changes and disposal clear content
and intent. Stale reads retry the same request once; other errors display their reason.
Explicit full-read transfer/memory costs depend on the chosen item and its bounded source page.

Reads use the staged document boundary, without holding the document lock over upstream
I/O. Settlement requires matching document, selection, backend generation, runtime epoch
and this thread's read observation. Unrelated global revisions do not invalidate the page;
concurrent same-thread changes still fence stale reads. The browser checks identity again
and replays only ordered events strictly newer than the page revision. Old intents cannot
overwrite newer navigation. Pages never populate the server live cache or grant writer authority.

## Live updates, budgets and resynchronization

The live model retains at most 20 raw turns, with at most 80 bounded items per paginated
turn. Control-summary refreshes preserve already observed items. Prompt preparation reads
cached active-turn identity without deep-copying the transcript.

The worker projects bounded items; the coordinator emits only changed `item_turns` plus
bounded `item_order`. Each thread has one projection flight and one latest successor.
Settlement checks observation/epoch, and successors freeze fresh cache inputs when admitted.
Stream deltas update their matching item. The browser retains at most 80 live rows; paging
replaces the history window, and newly arriving live items do not pull it to the tail.
Lifecycle and epoch changes clear comparison caches. The comparison cache retains at most
16 recently published threads; eviction only repeats bounded rows on the next publication.
Control refreshes preserve observed collaboration tasks in the bounded cache; cold opens
do not scan historical body content to rebuild all previous tasks.

Socket queues retain the existing default 128-event limit and a 2 MiB byte budget.
Overflow queues one small `socket_backpressure` invalidation, not a replay of large data;
it does not itself mean disconnection or prompt failure. Browser control-snapshot buffers
are capped at 256 events/1 MiB estimated bytes; body-read buffers at 256/512 KiB. Overflow
discards incomplete buffers and refreshes bounded state. Stream presentation batches flush
early at 256/512 KiB. Body recovery permits at most three automatic attempts after 1/2/4
seconds, then retains an error/manual retry. No tight retry loop, full-thread fallback or
automatic prompt replay is allowed.

## Reading, copying, exports and diagnostics

Rows mount within about 900px above/below the internal viewport, retaining measured-height
placeholders elsewhere. Rows holding focus or selection endpoints stay mounted. Environments
without IntersectionObserver render the bounded window. No root `content-visibility` workaround
or whole reading-mode remount is used. Verify repeated mode switches, resizing, delayed Markdown/
image layout, follow scrolling and Prompt/search navigation.

Paginated copy actions copy a single complete message; previews cannot masquerade as full
copy or Composer refill. Native browser find and cross-offscreen selection cover only mounted
content. Application Prompt/final-response search, explicit full text and Markdown/PDF exports
use source data. Exports never concatenate virtual DOM or previews; their existing scope and
completeness limits remain unchanged.

Page diagnostics remain off by default. Manual recording adds at most 64 payload-free performance
samples: body-read duration, received event bytes, socket close code, backpressure/buffer overflow
and supported browser long-task durations. Stop freezes evidence; restarting clears it. No prompts,
responses, thread IDs, URLs, cookies or arbitrary close-reason strings are recorded.

## Upstream evidence

The implementation uses Codex commit `c248f6d48b97eb4a2aa56147a0b11b7d763278b9`:
`ThreadTurnsListParams`, `ThreadItemsListParams`, `ThreadItemsListAnchor` and `ThreadResumeParams`
in `codex-rs/app-server-protocol/src/protocol/v2/thread.rs`, and the indexed anchor mapping in
`codex-rs/app-server/src/request_processors/thread_processor.rs`, plus inclusive backwards
cursors in `codex-rs/thread-store/src/local/thread_history/segment_paging.rs`. Item anchors
were introduced by `de9e78e3e7caed0fdd75d20ae617faa646dfef3c`. Deployed npm 0.156.1 accepts
only strings; 0.160.0 has been verified to accept item anchors. Development source does not
prove deployed capabilities. Upstream storage and legacy formats are unchanged.
