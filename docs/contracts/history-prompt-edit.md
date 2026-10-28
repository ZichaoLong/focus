# Historical prompt editing

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/history-prompt-edit.zh-CN.md`.

## Authority and protocol

Codex owns threads, durable history and inventory. Focus does not scan or modify its private database, create a durable thread index,
keep history copies or persist an edit journal. Existing Composer storage owns unsent drafts; pending handoff text lives only in the current document.

The reviewed source is Codex 0.164.0,
[`fe3b29455488c2e189e43ad5526a107900c5e1b7`](https://github.com/openai/codex/commit/fe3b29455488c2e189e43ad5526a107900c5e1b7).
Schemas exported from the actual 0.164.0 and 0.165.0 binaries expose `thread/revert {threadId,beforeTurnId}`,
`thread/reverted {threadId}` and `thread/fork.beforeTurnId`. Revert changes the existing thread; fork creates a new ID.
Both exclude the selected turn and every later turn. Neither version exposes the old `thread/rollback`; Focus performs no rename or fork fallback.
Web history forks require a ready initialize identity for 0.164.0 or 0.165.0 and the exact generation used to read the original prompt.
Unreviewed versions refuse only this feature. Startup, ordinary creation and conversation remain available.
The complete schema baseline is 0.164.0; only this feature's subset is verified against 0.165.0.

Pinned implementation: [TUI selection](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/tui/src/app_backtrack.rs),
[TUI settlement](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/tui/src/app/event_dispatch.rs),
[server implementation](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/app-server/src/request_processors/thread_processor.rs),
[revert tests](https://github.com/openai/codex/blob/fe3b29455488c2e189e43ad5526a107900c5e1b7/codex-rs/app-server/tests/suite/v2/thread_revert.rs).

## Native fcodex revert

The native protocol supports persistent paginated threads only. Preserve upstream rejection of legacy/ephemeral histories without fallback.

Forward the native TUI's exact `threadId + beforeTurnId` unchanged, with no extra fields. Require an authoritative direct root,
a live attached connection, and the existing control writer gate. A foreign exclusive/autonomous lease still refuses the action.
Use ordinary tracked-request settlement; create no writer, history owner or retry ledger. Success must name the admitted thread.
Wrong identity, transport loss or malformed responses remain unknown. Preserve validation/unsupported errors -32600/-32601/-32602;
other errors may follow a committed history mutation and settle as unknown. Forward the original error to the TUI and never resend.

Upstream revert stops the runtime, possibly interrupting its current turn, replaces history and reloads the same ID with subscriptions.
It does not revert file changes. Ordinary Web/fcodex input has no exclusive lease; Focus adds no global lock or guarantee that another
frontend cannot be running. Native TUI rejects an in-progress selected turn, but a later current turn may still be interrupted.

The native TUI hydrates and validates actual history coordinates; Focus transports the final IDs without a display-ordinal mapping.
Native TUI refuses independent edits of same-turn supplemental inputs. Its image, text-element and mention-binding restoration remains
owned by that TUI version; Focus neither strips it nor applies Web's plain-text restriction to native input.
The internal revert reload does not invoke resume's idle-goal continuation. Focus does not clear goal state; subsequent explicit resume/start
continues to use existing goal/owner semantics. Revert does not promise to cancel the goal.

## Web edit and fork

The historical action posts exactly `{turn_id,item_id}` to the existing fork endpoint; ordinary full-history fork keeps an empty body.
Read the first userMessage from that exact turn through generation-pinned `thread/items/list`, match its real item ID, and retain full input.
The read is limited to five seconds and advancing cursors. Never use display numbers, synthetic row IDs or clipped preview text.
Only then use `ThreadCreateTransaction` to send one native fork with `beforeTurnId`, persistent metadata-only output and
`deferGoalContinuation:false`. Do not revert the source, move its selection/owner/binding, inherit its goal or submit a prompt.

Support the first plain-text user prompt in each paginated turn, including first, older and inherited turns. Forking before the first turn
may yield empty history. Explicitly refuse legacy history, missing/mismatched coordinates, supplemental inputs, attachments/non-text
inputs, nonempty text elements, incomplete reads, empty text and input over 1 MiB UTF-8 before creation. Join multiple plain-text pieces
with newlines while retaining their text. Do not strip structured content. Upstream decides concurrent boundary validity; never substitute
another turn or fall back to a full fork.

Every success contains `edit_prompt=null|{turn_id,item_id,text}`. Verify the exact coordinates again in the browser. Restore only into the
new branch through existing Composer recovery's exact scope and empty-input gate. Preserve navigation made while the request was pending.
If handoff cannot finish, retain the original with a visible restore action; delete the memory record after handoff. Never overwrite newer
text or attachments. Sending requires another explicit user gesture and uses the ordinary single-POST receipt protocol. Creation or send
uncertainty never authorizes replay. Pending memory-only handoffs do not survive F5; preserve known branch IDs for manual reopening.

Naming, bounded visibility checks and dismissible notes follow the [creation contract](thread-create-local-commit.md).
One missed page is not proof of directory absence, and restart does not guarantee discovery of all empty-preview branches.

## History notifications and caches

Canonical `thread/reverted` advances the existing observation fence, forgets the exact thread's Web history/token usage and pending
transcript projection, and publishes `thread_invalidated`. Existing forks are unaffected. After event epoch/revision admission, the browser
clears that thread's transcript, prompt navigation, full/tool details and search cache, cancels stale reads, and uses ordinary projection
refresh. A full projection reload after reconnect or an event gap also clears these caches, since the revert notification may have been missed.
Late reads or old events cannot reinstall removed history.

## Verification

Cover exact boundaries, unchanged source and inherited history, empty first-turn fork, explicit attachment/supplement refusal,
navigation and draft safety, native same-ID revert, foreign leases, unknown/disconnect without replay, and history cache invalidation.
Version-specific isolated and browser evidence is recorded in `../verification/history-prompt-edit-2026-10-28.zh-CN.md`.
