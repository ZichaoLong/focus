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
Web history editing uses the same public `thread/revert`, without the experimental `thread/fork.beforeTurnId` or a version-string
allowlist for edit forks. Unsupported methods fail without fork/rollback fallback. The current semantic baseline was verified on
0.164.0 and 0.165.0. The complete schema baseline is 0.164.0; only this feature's subset is verified against 0.165.0.

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

## Web revert and edit

The chat action keeps the current thread ID, replaces its effective history with the prefix before the selected turn, and restores
that prompt for editing. That turn and all later turns leave the current history. Other frontends on the same thread observe the change;
a running ordinary turn can be interrupted. File changes and goal state keep upstream semantics. Full fork in the session list remains
an independent operation that preserves the source history.

First GET `/api/threads/{thread_id}/history-prompt?turn_id=...&item_id=...`. The server reads the selected turn's first userMessage through
generation-pinned `thread/items/list`, checks the actual item ID, and returns `{thread_id,turn_id,item_id,text}`. The read is limited to
five seconds and advancing cursors. Never infer coordinates or original text from display numbers, synthetic IDs or clipped previews.
Preparation does not mutate history or introduce a persistent prepare token, journal or history copy.

The browser validates all coordinates and retains the full original in document memory before sending exactly one
POST `/api/threads/{thread_id}/revert {turn_id}`. Navigation or a changed scope during preparation cancels an unsent revert.
The server reuses direct-root admission, the control writer gate and the process-local unknown registry. It calls
`thread/revert {threadId,beforeTurnId}` on the exact connection captured before dispatch, without another lock or a foreign-lease bypass.
Success is `{accepted:true,thread_id}` for the same ID. Upstream atomically decides boundary validity; a concurrently removed turn
remains a rejection, never a guessed cutoff or a fallback fork.

Web restoration supports the first plain-text prompt in each persistent paginated turn, including first, older and inherited turns.
Reverting before the first turn may leave empty history. Preparation refuses legacy, absent/mismatched coordinates, supplemental inputs,
attachments/non-text inputs, nonempty text elements, incomplete reads, empty text and over 1 MiB UTF-8. Join plain-text pieces with
newlines; never silently strip structured content.

After confirmed revert success, installation of the corresponding snapshot, and validation of the operation's original navigation state,
use existing Composer recovery's exact scope and empty-input gate to restore an unsent draft automatically. If the refresh installs no
snapshot, fails, or navigation changes, retain the original with an explicit restore action available on returning to that thread.
Preserve newer text, attachments and navigation. Show ordinary refresh errors only while the initiating navigation state remains current;
authentication or document invalidation still follows global handling. Do not start another edit while an original is awaiting handoff.
Sending remains an explicit user action through the ordinary prompt path.

Preserve native validation/unsupported errors -32600/-32601/-32602. Other revert errors may follow a durable commit and settle as
unknown through the existing control registry. Transport loss, timeout and malformed results never authorize automatic replay or fork
fallback. Because the browser retains the original before mutation, even a lost HTTP response leaves it available for manual recovery.
Refresh history on uncertainty and do not automatically load the composer. Pending memory-only originals do not survive F5.

Full fork accepts only an empty HTTP body and no longer returns `edit_prompt`. Naming and list-visibility notes belong only to full fork.

## History notifications and caches

Canonical `thread/reverted`, plus confirmed or uncertain Web revert responses, advance the existing observation fence, forgets the exact thread's Web history/token usage and pending
transcript projection, and publishes `thread_invalidated`. Existing forks are unaffected. After event epoch/revision admission, the browser
clears that thread's transcript, prompt navigation, full/tool details and search cache, cancels stale reads, and uses ordinary projection
refresh. A full projection reload after reconnect or an event gap also clears these caches, since the revert notification may have been missed.
Late reads or old events cannot reinstall removed history.

## Verification

Cover exact boundaries, same IDs, inherited history, empty first-turn history, attachment/supplement refusal, original retention before
mutation, navigation and draft safety, foreign leases, unknown/disconnect without replay, and history cache invalidation.
Existing upstream isolation evidence is recorded in `../verification/history-prompt-edit-2026-10-28.zh-CN.md`. The current Web path is
covered by `test_history_prompt_edit.py`, `test_history_edit_gateway.py`, `test_codex_thread_revert.py` and `focus-history-edit*.test.ts`.
