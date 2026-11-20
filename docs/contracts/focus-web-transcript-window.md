# Focus Web bounded transcript window

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-transcript-window.zh-CN.md`.

## Scope and owners

This contract applies to saved `history_mode=paginated` threads. Legacy threads retain
existing compatibility reads, without migration, indexing, or performance work.
Ephemeral subagent threads retain their existing detail projection.

`WebThreadOpenCoordinator` owns selection and control state. `WebThreadInspectionService`
owns document, selection, backend generation and observation admission. `transcript_window.py`
reads frozen inputs and projects items. `createFocusTranscript`, through `TranscriptPageWindow`, owns the sole browser body
window; `createFocusPromptHistory` owns the paginated Prompt directory, while
`createFocusHistoryNavigation` retains legacy summary navigation. `TranscriptRow.vue`
owns visibility and measured heights, never history or sending authority.
`toolGroupPresentation.ts` derives tool groups and browser-local expansion choices without
changing source rows in the transcript window.

## Control state and body reads

Opening/resuming a paginated thread requests `itemsView=summary`. Snapshot `turns`
contain bounded first-user Prompt summaries, alongside active-turn identity, pending
requests, settings and selection receipts. A separate authenticated
`GET /api/threads/{thread_id}/transcript` loads the body. Body loading/failure does not
revoke confirmed Composer scope. Sending requires server `hello`, not WebSocket `open`.
A proven pre-effect `web_writer_disconnected` refusal reconnects while retaining the
draft, without replaying the prompt. Unknown outcomes follow the prompt recovery contract.

The closed query permits `turn_id`, opaque `cursor`, `direction=asc|desc`, `item_id`,
`full=true|false`, `view=transcript|prompts`, `source_cursor`, and optional `fill=true`.
A fill accepts only a whole-thread older `cursor` and optional `direction=desc`. Values must be unique,
nonempty, trimmed and at most 4096 characters. An item requires a turn; full requires an
item. Source cursors require full and exclude cursor. Default reads return the latest
40 thread items chronologically. Paging uses upstream cursors, never synthetic offsets.
Prompt and search navigation target the exact item, including additional messages in the
same turn. Locating scans only the known `turn_id`; subsequent browsing covers the entire
thread and omits the turn filter. Indexed navigation
reads the target's inclusive string cursor, then uses it for a thread-wide page, without
decoding or synthesizing upstream cursors.

Responses contain `{runtime_epoch, revision, thread_id, turn_id, view, target_pending,
turns, older_cursor, newer_cursor, full_text}`. Rows carry stable `rawTurnId`, `itemId`,
and `id=<turn>:item:<item>:<segment>`. Ordinary reads start at 40 source items. Prompt,
steer, assistant commentary/final replies and visible reasoning retain complete text;
characters, nodes, paragraphs and combined fields never turn prose into a preview.
The 2 MiB serialized page target controls how many complete items to load: reread the same
upstream anchor/cursor with a smaller limit and use its real returned edge cursors.
Admit a single oversized item intact, without clipping, skipping, retry loops or cursor gaps.
Its transfer/parse cost remains proportional to its size. These budgets are not model limits.

Every tool, including a running one, projects a single name/status/invocation summary row
with `contentDeferred=true` and one frameless “View detail” action. Name and argument summaries
are at most 512 characters each; output, diffs, media bodies and detailed commandActions are
absent. The source-tree 16384-character, 1024-node and depth-12 budgets apply only to tool
summaries, prioritizing identity/invocation fields, never prose. A multi-file source item has
one file-count row and reads the whole record. Existing projection still owns tool naming.
Prose has no `contentDeferred` or long-preview/manual-full-text intermediate state.

Terminal commands and single-file changes use specialized detail, requesting `view=full` on
the first click without a preview read. Other and running tools use exact-item `full=true`
source JSON. Both prefer item anchors over whole source-page rereads. Failures offer explicit
rereading; close, replacement, thread/epoch/access changes cancel reads and clear the sole
selected slot. Running generic detail explicitly represents this read, allows manual rereading,
and refreshes once on that tool's completion only while open. Unopened tools are not polled.
Unsaved upstream data cannot be represented as complete persisted output.

First opening/using the Prompt directory reads `view=prompts` backwards through userMessage
items, including additional/steer messages. Responses contain only titles of at most 160
characters plus a truncation marker. This view allows only descending, whole-thread cursor
paging. Each HTTP request reads at most four sequential pages of 100 items, returning as
soon as a page has user messages; empty pages still advance the cursor. The browser keeps
at most 200 prompts and explicitly marks this limit. First use automatically reads one batch;
each batch stops after about 20 new titles (without splitting a server page) or eight requests.
Further reading uses “Load more prompts” from the saved cursor; reopening or refocusing does
not restart scanning. Displayed entries stay in place within a batch, publishing collected
titles once on completion, failure or pause. Loading is visible; closing or selecting pauses
the scan. Target selection shows progress, and existing titles remain selectable.
Errors preserve partial results and allow retry. Thread, epoch/access
changes and disposal cancel reads. Directory scanning never blocks opening/sending or
transfers tool/reasoning/assistant bodies to the browser; it uses no SQLite/rollout bypass.
Directory and target-scan cursor guards retain only the latest 256 cursors.
Control snapshots retain observed user titles with exact item identities. Live additions
are deduplicated by ID and survive body eviction. Legacy summary navigation is unchanged.

Rows may carry `sourceCursor`, wrapping the upstream inclusive backwards cursor, original
turn scope, direction and actual page size (1..100). It grants no authority and never synthesizes
cursors. Explicit requests carrying it reread that page and check exact item/turn identity.
The official browser prefers predecessor/target item anchors; specialized full-tool reads
reuse the same anchor owner. Only an explicit old-server object-cursor rejection (`expected a string`)
falls back to bounded string-cursor pages within the target turn for both full reads and
body navigation. `target_pending=true` requests cancellable continuation. Once found, body
navigation reopens a thread-wide page from the scoped page's inclusive cursor for cross-turn
browsing. Unrelated errors never trigger compatibility fallback. Missing
items fail rather than substituting nearby content.

Successful full reads return empty `turns` and uncropped `full_text`: user/assistant text,
complete visible reasoning, or source JSON for other items. A separate selectable text view
copies the source string. Closing, identity, epoch/access changes and disposal clear content
and intent. Focus-generated live-only plan/turn-diff records are frozen by exact turn/item
from the existing live read model, with the same document/epoch/observation settlement and no
persisted-history scan or parallel durable cache. They leave with the live cache lifecycle.
Stale reads retry the same request once; other errors display their reason.
Tool source-JSON detail also displays the selected tool's name and invocation summary. This
context is captured with the request, retained during loading/errors and cleared with the
content. Old requests cannot replace a newer tool's content or title.
Explicit full-read transfer/memory costs depend on the chosen item and its bounded source page.

## Tool group presentation

Consecutive tool-summary rows within one `rawTurnId` form a presentation group. Blank
text/reasoning placeholders do not break a group; nonempty replies, visible reasoning,
user messages and other semantic items do. Groups stay within a source turn. A single tool already starts a collapsed group. Incoming members update its count and status. Running status can appear with a failure count. The next group after a reply or other semantic boundary starts collapsed.

Tool grouping and transcript rows share the same blank-assistant-content predicate.
Items containing only blank text/reasoning retain their source-row identity for later
stream deltas, but mount no content and occupy no height, margins or offscreen placeholder
space. Metadata such as timestamps does not make an empty item visible. Real content
restores presentation and measurement under the same identity. Clearing content discards
its old measurement; folding tools still retains valid measurements. User messages, tools
and other semantic items are not hidden based on blank prose.

Explicit expansion/collapse overrides the default. Retain choices by stable source-row
identity across prepends, leader changes, splits and merges. The most recent choice wins
when differently toggled groups join and propagates to new members. Choices survive page eviction, same-tab thread changes and warm instance switches. Each retained document keeps choices for recently used threads up to the thread preference, with at most 2,048 member identities per thread. Document replacement and choice eviction restore the collapsed default. Headers support keyboard operation. Automatic updates preserve reader focus and selection. Legacy whole-turn groups identify members by turn and tool and keep inline media results visible.

Presentation groups never replace, reparent or merge source rows. Each tool keeps its own
`TranscriptRow` and exact-item detail action. Folding unmounts member tool components,
retaining source-row shells and a separate header. Expansion still virtualizes each row
within the existing approximately 900px overscan, without mounting an entire large group.
Zero heights caused by folding must not overwrite valid row measurements.

Resolve header anchors through a retained source member, so prepending an earlier leader
does not invalidate an anchor. When folding hides an anchored source row, the existing
transcript scroll owner resolves it to the current header containing that member and
preserves the reading position. Layout corrections continue to preserve touch/inertia,
without adding another scroll owner. Grouping does not change DTOs, cursors, page budgets,
source copy/export or exact turn/item detail reads.
If paging replaces a header during its click pin, release the detached DOM pin and hand
position keeping back to the same source-member anchor.

## User submission times

User rows never substitute whole-turn `startedAt`. Optional `codexRecordedAtMs` is the native userMessage item time;
`clientUserMessageId` and `promptTiming={submissionId,submittedAtMs}` associate exact browser submissions.
Sources, storage, deferred details and missing observations follow the [submission time contract](./focus-web-prompt-timing.md).

## Reply times and long replies

`agentMessage` rows and text blocks carry `reply={state, startedAtMs?, completedAtMs?}`.
State is `unknown|generating|complete`. Times are source item Unix milliseconds: nonnegative
integers within the JavaScript Date range. History uses nullable `ThreadItemEntry` fields.
The read model retains top-level notification times from `item/started` and `item/completed`,
preserving the start through completion and later snapshots of the same item. History without
a completion time stays unknown. Never substitute turn, browser arrival or page-open time.
Tool cards do not gain time labels.

Each intermediate/final text reply displays a subtle local time, preferring completion.
If only the start is known, display it; explicitly observed generation adds a generating label.
Clicking expands the full date, available start/completion times and their ordered duration.
This is separate from whole-turn duration. Untimed historical replies have no invented label.
Intermediate and final replies share a left-aligned, borderless footer for the timestamp and
whole-message copy icon, in normal/reading modes and desktop/mobile layouts. They appear side
by side by default. Expanded time details occupy a separate row below, leaving the compact
time label and copy control in place. Untimed replies retain only their existing copy action.
Generating timestamps continue updating; copy availability follows its existing conditions.

Prose loads whole with its page, without a separate reply-full request or reply LRU. Live text
continues appending to the same item past 16384 characters, without waiting for item completion.
Visible reasoning is fully expanded in the main scroll container, without a five-line inner
window or automatic folding. Legacy presentation is unchanged. Copy/refill use complete loaded
prose, while timestamps continue to follow actual per-item lifecycle metadata.

Complete Markdown of at least 16384 characters is parsed once with shared configuration, then grouped by whole top-level
structures (target 12000 characters, at most 24 top-level nodes) for viewport mounting. One
table, list, formula or code block may exceed this target rather than split its grammar.
Document-wide references remain available; diff fences show every original addition/deletion.
Offscreen groups use measured heights retained by the bounded transcript row. Visible groups
participate in the existing scroll anchor, whose single owner preserves touch/inertia motion.
Without IntersectionObserver, the complete reply renders.

Transcript rows and long-reply chunks share intersection delivery in `transcriptVisibility.ts`.
For each target, the newest timestamp in a notification batch determines visibility. While
the document is hidden, retain mounted content instead of replacing it with placeholders.
On foreground or back/forward-cache restoration, reobserve existing targets on the next
frame and discard pre-restoration notifications. Coalesce recovery events into one pass per
document; remove listeners and pending callbacks when its final target unmounts. Rechecks
preserve offscreen virtualization without page reloads, conversation remounts, scroll/draft
writes, transcript requests or polling. Existing components still own focus/selection
pinning, folding and height measurement.

Reads use the staged document boundary, without holding the document lock over upstream
I/O. Settlement requires matching document, selection, backend generation, runtime epoch
and this thread's read observation. Unrelated global revisions do not invalidate the page;
concurrent same-thread changes still fence stale reads. The browser checks identity again
and tracks revisions for the rows actually read, replaying only ordered events newer than
each row's read. Reading an older page must not swallow pending deltas for other retained
pages. A confirmed tail read also fences old additions already covered by that read but
absent from the window. Row revisions leave with cache eviction and identity changes. Old intents cannot
overwrite newer navigation. Pages never populate the server live cache or grant writer authority.

## Live updates, budgets and resynchronization

The live model retains at most 20 raw turns and 80 items per paginated turn, with an 8 MiB
residency target estimated from twice source string length plus structure overhead. Evict
whole old items; admit the latest item even above the target, without clipping prose. Control-summary refreshes preserve already observed items. Prompt preparation reads
cached active-turn identity without deep-copying the transcript.

The worker projects bounded items; the coordinator emits only changed `item_turns` plus
bounded `item_order`. Each thread has one projection flight and one latest successor.
Settlement checks observation/epoch, and successors freeze fresh cache inputs when admitted.
Control snapshot revisions cover control state, not independently loaded body events.
Apply complete `item_turns` by item, including new final replies carried by coalesced
`turn/completed` notifications, without requiring another body request based on the method.
Stream presentation batches about once per second; non-stream events such as completion
flush pending presentation deltas first.
Prose deltas update their matching item. Command/file output, MCP progress and plan text
deltas are not published into the ordinary transcript; tool start/completion and status remain
live. Subagent task overviews carry identity/status, without duplicating prompt/progress/result/output. The browser accumulates up to 10 adjacent source pages on demand, with an 8 MiB data
budget estimated as twice each presentation row's serialized JSON length. Evict whole
pages from the distant edge when either limit is reached. A single current page may exceed
the byte target: oversized prose stays readable and leaves with its page, without repeated resync. Do not prefetch ten pages or
retain a separate full-thread cache. Reversing within cached content makes no request.
Deduplicate and refresh inclusive cursor anchors by stable ID; retain actual edge cursors
without gaps. A late page must not evict the reader's visible anchor page; discard the
new distant page instead when necessary. When only the anchor page and one adjacent page
remain, temporarily allow their combined bytes above the target so the reader can scroll
out of a large item; moving the anchor permits eviction. The live tail page retains at most 80 rows before
bounded head resynchronization. New live items never pull a historical viewport to the tail.
Scrolling and body reception are independent: while the cache still includes the tail,
slight upward scrolling or reading adjacent older pages does not stop new replies. Control
refreshes and event-gap recovery reread the bounded latest body. While not following, merge
overlapping rows, preserving the reader's anchor and adjacent pages. If the latest page has
no overlap, retain the window and expose the real gap for contiguous boundary paging;
never concatenate disjoint pages. If limiting the live tail would evict the visible anchor,
stop extending that page and expose its newer boundary instead of displacing the reader.

Reconnection or composite control-state recovery immediately retires old cursors, revision evidence, prompt-index and
detail reads, but may retain rendered body rows to avoid emptying the DOM and exiting reading mode. After control recovery,
a reader away from the tail rereads and verifies the visible exact turn/item anchor; the existing scroll owner preserves
its pixel offset. A following reader reloads the bounded tail. If the user starts scrolling and stops following while that
recovery read is pending, reread and verify the current reading anchor instead. Never merge the response into the retired,
empty page cache and publish an empty transcript, including when the latest page no longer overlaps the reading position.
Failed reads retain a synchronization error, never treating
old body content as proof of current state. If an authoritative result no longer contains the anchor, discard old body rows
and load the current tail rather than restoring reverted content. Thread, epoch/access changes and explicit history
invalidation still clear the old window; late recovery cannot overwrite a new target.

Clicking “Latest messages” rereads the server's latest page. Keep the already-read prefix only when the new page
has an older cursor and its initial row IDs match the cached suffix in order, with no duplicate in the retained prefix.
Install the entire fresh page. A gap, order conflict or retired cache uses just the new page. A split source page
can resume toward newer history from its exact last item. Retained rows keep their own read revisions.
While following the tail, ordinary control refreshes preserve adjacent pages under the same continuity rule.
Reconnection still retires the old window.

Clicking “Latest messages” or returning to an instance in a host that negotiated `tabs` can request extra context.
An instance return, including reopening its saved thread in a rebuilt document, first completes the authoritative
read of the selected thread. Use that result for extra context only if the reader is following the tail when the
read starts and finishes, and the confirmed tail has an older cursor. If another control refresh is already
queued, wait for its confirmed cursor. Restore historical positions from their item anchor.
Parked instances make no fill requests. After rendering, normal and reading modes measure the gap
from the end of all content, including activity and queued prompts, to the transcript viewport bottom. When the content
fits and the gap is at least both 96 CSS pixels and 20% of that viewport, load one older page and measure again.
Each return allows two additional reads at most. Each complete successful fill response is limited to 128 KiB
of serialized JSON before HTTP compression. The gateway returns a small `transcript_fill_limit` refusal for a larger page.
A failure, full cache or reader taking control ends the fill. Keep the live tail and the manual paging control.
Scroll input, Prompt navigation, thread changes, hiding the page or parking the instance cancel a pending
return. Manual reads still admit a whole oversized item.

During ordinary browsing both directions require actual user movement toward the respective edge, within
about 300px of the scroll container boundary. When content fits within one screen and the scroll
position cannot move, upward or downward wheel input can still load the adjacent older or newer page.
Normal browsing supports wheel, touch and edge buttons.
Allow only one body request at a time. Consume
scroll intent on admission, without chaining reads from observers, layout changes, Prompt
navigation or pages shorter than the viewport; input during loading cannot queue another
automatic read. Errors retain content and block automatic retries; edge buttons allow manual
retry. Preserve the first visible item's ID and pixel offset during prepend, append and
remote-edge eviction, including virtual-row measurement changes. The application anchor is the
sole layout correction owner for continuous transcripts; disable native anchoring on that
container. Compensate only movement in content coordinates, preserving touch and subsequent
inertial scrolling. Refresh the visible anchor on scroll rather than repeatedly restoring the
old paging position. New input, Prompt navigation
and thread switches supersede older scroll intents. Resume following only at the real thread
tail, never at a historical page bottom; downward loading catches up unseen live items in
an actual historical window.
Lifecycle and epoch changes clear comparison caches. The comparison cache retains at most
16 recently published threads; eviction only repeats bounded rows on the next publication.
Control refreshes preserve observed collaboration tasks in the bounded cache; cold opens
do not scan historical body content to rebuild all previous tasks.

`useComposerDraft` owns input autosizing. Preserve the input row's occupied space
during measurement so a temporary collapse cannot resize the transcript viewport
or displace its historical reading position. Apply only the final measured height,
allowing deletion and mode changes to shrink the input normally. Draft editing does
not resume following in a historical window; when already following the live tail,
the existing transcript scroll owner handles the final height change.

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
Markdown renderers inside these rows disable their own `content-visibility:auto` and intrinsic
placeholder sizes, avoiding duplicate height estimation. A remounted short message must not
become a 600px placeholder and repeatedly unmount/remount as intersection changes.

Paginated copy actions copy a single complete message. Native browser find and cross-offscreen selection cover only mounted
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

Per-item timing evidence is `ThreadItemEntry` (`v2/thread.rs`) and `ItemStartedNotification` /
`ItemCompletedNotification` (`v2/item.rs`) at the same pinned commit, introduced by
`772abc9425d4bf4c2802456365785378811e7d3d`. Local npm 0.160.0 has been verified to return
these fields. Times not recorded by older producers may remain null.
