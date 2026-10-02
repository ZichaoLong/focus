# Focus Web bounded transcript window

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-transcript-window.zh-CN.md`.

## Scope and owners

This contract applies to saved `history_mode=paginated` threads. Legacy threads retain
existing compatibility reads, without migration, indexing, or performance work.
Ephemeral subagent threads retain their existing detail projection.

`WebThreadOpenCoordinator` owns selection and control state. `WebThreadInspectionService`
owns document, selection, backend generation and observation admission. `transcript_window.py`
reads frozen inputs and projects items. `createFocusTranscript` owns the sole browser body
window; `createFocusHistoryNavigation` retains the Prompt outline. `TranscriptRow.vue`
owns visibility and measured heights, never history or sending authority.

## Control state and body reads

Opening/resuming a paginated thread requests `itemsView=summary`. Snapshot `turns`
contain bounded first-user Prompt summaries, alongside active-turn identity, pending
requests, settings and selection receipts. A separate authenticated
`GET /api/threads/{thread_id}/transcript` loads the body. Body loading/failure does not
revoke confirmed Composer scope. Sending requires server `hello`, not WebSocket `open`.
A proven pre-effect `web_writer_disconnected` refusal reconnects while retaining the
draft, without replaying the prompt. Unknown outcomes follow the prompt recovery contract.

The closed query permits optional `turn_id`, opaque `cursor`, `direction=asc|desc`,
`item_id` and `full=true|false`. Values must be unique, nonempty, trimmed and at most
4096 characters. An item requires a turn and excludes cursor; full requires an item.
Default reads return the latest 40 thread items in chronological display order.
Paging uses upstream cursors, never synthetic offsets. Prompt navigation reads a turn's
start; search navigation reads the exact item. Subsequent targeted paging stays within
that turn; the outline and recent-message action provide navigation beyond it.

The response is `{runtime_epoch, revision, thread_id, turn_id, turns, older_cursor,
newer_cursor, full_text}`. Rows carry stable `rawTurnId`, `itemId`, and
`id=<turn>:item:<item>:<segment>`. Ordinary reads contain at most 40 source items and
2 MiB encoded data. Source presentation trees retain up to 16384 text characters,
1024 nodes and depth 12. Projections above 32 KiB become shorter plain-text previews.
Clipped content must carry `contentDeferred=true`, never parse incomplete Markdown or
pretend to be full text. Existing trusted tool omission/deferral metadata retains its
separate output budget.

“View full content” uses the upstream item anchor to read one predecessor and then the
exact target: two bounded positioning requests. A missing/mismatched item fails rather
than substituting a neighbor. Full reads return empty `turns` and uncropped `full_text`:
user/assistant text, complete visible reasoning, or source JSON for other items.
The separate selectable text view copies from the source string. Closing, identity,
epoch/access changes and disposal clear its content and request intent. This explicit
large read has transfer and memory costs proportional to the selected item.

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
`codex-rs/app-server/src/request_processors/thread_processor.rs`. Upstream storage and legacy
formats are unchanged.
