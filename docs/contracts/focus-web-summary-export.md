# Focus Web Q&A export ranges

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-summary-export.zh-CN.md`.

## Scope and content

All Markdown and Print / Save as PDF entries share the range dialog in
`FocusThreadActions.vue`: `all` (default), `last_turn`, or `selected`. JSONL remains
a separate whole-thread data export.

- `all` preserves the existing summary: the first user prompt and final reply of
  each turn, in history order, including questions without a reply yet.
- `last_turn` searches newest first for a turn containing a `userMessage`, skipping
  system/compaction-only turns. An unfinished, failed, interrupted or unanswered
  latest question fails explicitly, without falling back to an earlier turn.
  No question to export is also an explicit failure.
- `selected` accepts 1..100 distinct turn IDs in the same thread, combining them
  in server history order rather than click order. Any missing, foreign,
  unfinished or unanswered selected turn fails the whole export.

Last/selected exports contain all user text in each chosen turn, including steer
follow-ups separated by blank lines. Prefer the last explicit `final_answer`;
completed legacy records without an explicit final may use the last phase-null
agent message. Explicit `commentary` and `partial_answer` are never final replies.
Keep attachment-envelope projection and failure rules; exclude tools, reasoning,
hooks and non-text attachments. Number exported turns from 1 and retain complete
question/reply text. Filename and document-title rules remain independent.

## Directory and browser state

`exportTurnSelection.ts` owns dialog-local selection and `ExportTurnPicker.vue`
shows one page of turns with on-demand expanded Q&A. Group by turn, page newest
first, and read at most 20 source turns per page independently of the body window
and 200-prompt directory. System turns can yield an empty page with a continuation
cursor; an empty page does not mean the history is exhausted. Directory rows carry
only prompt/reply excerpts and status. Expansion reads the complete turn through
the same export rules.

Keep selections across pages. Show the count, clear action and Select this page,
with a 100-turn selection limit. Page selection includes only completed question
turns on that page, never unloaded history or a silent partial selection when the
limit would be exceeded. Show unfinished states and disable new selection of them.
Directory state is advisory; the server revalidates exports. Failed paging retains
the current page and selection and retries the failed target page. Errors and
unloaded states are not complete-directory evidence.

Freeze the thread ID, title and suggested filename when opening. Selection,
cursors and preview live only in dialog memory; closing/unmounting aborts reads,
clears state and rejects late results. Retain at most one full preview and clear
it on paging/closing. Selected identities survive scrolling and body eviction.
Range selection, preview and saving share the export gate. Printing asks for scope
and title, opens the preview synchronously during confirmation, then fetches the
complete chosen Markdown. A blocked popup retains the options for retry.
Cancellation does not start a download or print.

## Interface, reads and completeness

Wire v31 uses `POST /api/threads/{thread_id}/export-summary` with exact JSON
`{scope: "all"|"last_turn"|"selected", turn_ids: string[]}`. Non-selected scopes
require an empty array; selected requires 1..100 unique, nonempty, trimmed IDs of
at most 256 characters. Reject unknown fields and duplicate IDs. POST carries a
bounded ID set but remains a read-only export with no writer/navigation intent,
runtime mutation or session renewal; enforce origin, CSRF and document admission.
Do not retain the former GET as an alias.

`GET /api/threads/{thread_id}/export-turns` accepts only one optional exact cursor.
It returns `FocusExportTurnPage {thread_id, turns, next_cursor}` with
`FocusExportTurn {turn_id, prompt, answer, status}`. Excerpts are bounded to 160/240
characters; status is `completed|interrupted|failed|inProgress`. Null cursor means
no next page. Send no-store; the browser strictly decodes and checks the target.
Both operations use the staged document and service-ingress boundaries, freeze
backend generation, read outside RuntimeLoop, and reject connection replacement
at settlement.

`WebThreadSummaryExportService` owns content, directory reads and completeness;
`thread_export_selection.py` owns only selection validation and pure Q&A extraction.
Admit only exact direct, non-ephemeral, persisted-history threads. All-mode keeps
ascending summary scans; last-turn locates descending and selected IDs are checked
ascending. Paginated history uses all item pages from `thread/items/list(turnId=...)`,
retaining only Q&A. Legacy history hydrates a matching full turn page with its
original cursor and width (at most 20 turns); never change history modes or read
rollout side channels.

Each request has a total 30-second deadline. Turn scans and each selected turn's
item scan are each limited to 100 pages, at most 100 entries per paginated page.
The complete Markdown and intermediate Q&A are bounded to 32 MiB. Reject wrong
identities, repeated items/turns and non-progressing cursors; errors never return
partial attachments. Directory requests read one page only. Frozen IDs are not an
atomic upstream snapshot: concurrent rollback removing a target fails explicitly,
without substituting neighboring turns.

Upstream evidence is read-only Codex commit
`2351d9e1b608e6f9d9a3699b71d7eb39ee41cfa4`: `ThreadTurnsListParams` and
`ThreadItemsListParams` in `app-server-protocol/src/protocol/v2/thread.rs`,
`MessagePhase` in `protocol/src/models.rs`, and the legacy/full compatibility path
in `app-server/src/request_processors/thread_processor.rs`, relative to `codex-rs/`.
Source evidence does not assert deployed support; missing APIs remain explicit
unsupported errors.

## Verification

Cover all scopes, paged steer input, selection order, missing/unfinished turns,
legacy phases, limits, connection replacement and protocol rejection. Browser
checks cover wide/narrow selection, retained selection across pages, cancellation,
download content, confirmation-time popup opening and standalone preview. Narrow
desktop simulation does not replace device-level mobile saving checks.
