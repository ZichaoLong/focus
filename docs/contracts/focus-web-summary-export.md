# Focus Web Q&A export ranges

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-summary-export.zh-CN.md`.

## Scope and content

All Markdown and Print / Save as PDF entries share two independent options in
`FocusThreadActions.vue`: range `all` (default), `last_turn`, or `selected`, and
content `qa` (default), `final_answers`, or `prompts`. JSONL remains a separate
whole-thread data export.

- `all` scans all visible turns in server history order.
- `last_turn` searches newest first for a turn containing a `userMessage`, skipping
  system/compaction-only turns. Never substitute the loaded browser window, last
  assistant message or last completed turn. No user turn is an explicit failure.
- `selected` accepts 1..100 distinct IDs from the same thread, in server history
  order rather than click order. Any missing or foreign ID fails the whole export.

| Content | All turns | Last / selected turns |
| --- | --- | --- |
| `qa` | Preserve the first-prompt summary, including final replies only for completed turns | All user text and the final reply; unfinished or unanswered turns fail the export |
| `final_answers` | Only final replies from completed turns; skip unavailable replies | Only the chosen final replies; unfinished or unanswered turns fail without falling back |
| `prompts` | All user text in each turn; skip turns without text prompts | All chosen user text; a turn without text prompts fails the export |

`prompts` admits existing user text from running, interrupted and failed turns.
Every range retains same-turn steer follow-ups, separated by blank lines, without
assistant text. `final_answers` must exclude prompt excerpts from headings too.
Either single-role mode fails explicitly if no body content is exportable, rather
than downloading an empty document.

Prefer the last explicit `final_answer`. Completed legacy records without an
explicit final may use the last phase-null agent message. Explicit `commentary`
and `partial_answer`, and phase-null messages in unfinished turns, are never final
replies. Missing historical phase metadata cannot be reconstructed; compatibility
selection does not prove that an explicit final marker was emitted. Keep attachment
envelope projection and failure rules. Exclude tools, reasoning, hooks and non-text
attachments. Number exported turns from 1 without truncating bodies. Filename and
document-title rules remain unchanged.

## Directory and browser state

`exportTurnSelection.ts` owns dialog-local selection and `ExportTurnPicker.vue`
shows one page of turns with on-demand content previews. Group by turn, page newest
first, and read at most 20 source turns per page independently of the body window
and 200-prompt directory. System turns can yield an empty page with a continuation
cursor; an empty page does not mean the history is exhausted. Directory rows carry
only prompt/reply excerpts and status. Expansion reads the chosen content for the complete turn through
the same export rules.

Keep selections across pages. Show the count, clear action and Select this page,
with a 100-turn selection limit. Page selection includes only turns eligible for
the current content mode, never unloaded history or a silent partial selection at
the limit. Show unfinished states; only prompts mode allows selecting them. Content
changes preserve selected IDs. If selected unfinished turns become unavailable,
show their count and block confirmation until the user deselects them or switches
back to prompts. Never silently discard selected turns.
Directory state is advisory; the server revalidates exports. Failed paging retains
the current page and selection and retries the failed target page. Errors and
unloaded states are not complete-directory evidence.

Freeze the thread ID, title and suggested filename when opening. Selection,
cursors and preview live only in dialog memory; closing/unmounting aborts reads,
clears state and rejects late results. Retain at most one full preview and clear
it on paging, content changes or closing, aborting pending reads. Preview the current content mode. Selected identities survive scrolling and body eviction.
Range selection, preview and saving share the export gate. Printing asks for scope, content
and title, opens the preview synchronously during confirmation, then fetches the
complete chosen Markdown. A blocked popup retains the options for retry.
Cancellation does not start a download or print.

## Interface, reads and completeness

Wire v32 uses `POST /api/threads/{thread_id}/export-summary` with exact JSON
`{scope: "all"|"last_turn"|"selected", turn_ids: string[], content: "qa"|"final_answers"|"prompts"}`. Non-selected scopes
require an empty array. A valid content value is required; selected requires 1..100 unique, nonempty, trimmed IDs of
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
Admit only exact direct, non-ephemeral, persisted-history threads. All Q&A/final-reply
exports scan summaries ascending; last-turn locates descending; selected turns and
all prompts scan ascending. Prompt export must hydrate follow-ups omitted by summaries. Paginated history uses all item pages from `thread/items/list(turnId=...)`,
retaining only Q&A. Legacy history hydrates a matching full turn page with its
original cursor and width (at most 20 turns); never change history modes or read
rollout side channels.

Each request has a total 30-second deadline. Turn scans and each selected turn's
item scan are each limited to 100 pages, at most 100 entries per paginated page.
The complete Markdown and intermediate Q&A are bounded to 32 MiB. The protocol decoder
rejects non-object turns and malformed cursors instead of dropping records or treating
a malformed cursor as history exhaustion. Reject wrong
identities, repeated items/turns and non-progressing cursors; errors never return
partial attachments. Directory requests read one page only. Latest refers to history visible upstream when
read; new input in running turns may appear only on a later read. Frozen IDs are not an
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

Cover three scopes × three content modes × both storage modes, role isolation in
bodies and headings, paged steer input, selection order, missing/unfinished turns,
legacy phases, limits, connection replacement and rejection through the real adapter decoder. Browser
checks cover wide/narrow selection, retained selection across pages, cancellation,
download content, confirmation-time popup opening and standalone preview. Narrow
desktop simulation does not replace device-level mobile saving checks.
