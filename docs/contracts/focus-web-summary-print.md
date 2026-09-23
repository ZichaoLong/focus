# Focus Web Q&A printing and PDF saving contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-summary-print.zh-CN.md`.

## Scope and entry points

The desktop conversation menu, sidebar session menu, narrow top export menu and
narrow session switcher offer both Export Q&A Markdown and Print / Save as PDF
when the existing `export` capability is available. Printing shares the busy
gate with Markdown and thread-data exports.

`createFocusThreadActions` obtains the complete Markdown through the existing
authenticated `exportThreadSummary` operation. Content and limits belong to
`GET /api/threads/{thread_id}/export-summary` in the [Web wire contract](focus-web-wire.md).
Never export a subset from the chat DOM, loaded history window or reading mode.
Keep the exclusions for tool activity, reasoning and non-text attachments.
No PDF endpoint, server browser dependency, external conversion service or wire DTO is added.

## Completeness and rendering

`SummaryPrintApp.vue` owns the standalone document; `summaryPrintMarkdown.ts`
owns static rendering and `summaryPrintPreparation.ts` prepares diagrams, images
and fonts. Preview the entire export without chat virtualization, progressive
batches, code folding or head/tail diff truncation. Code retains every line and
can wrap and span pages. Tables wrap cells, span pages and repeat headers.
The native print layout hides controls and instructions.

- Math reuses the exact grammar from `markdownMath.ts`: same-line `\(...\)` and
  block-position `\[...\]` or `$$...$$`. Do not guess single-dollar, unclosed or
  prose-position block math. Unrecognized content remains text; KaTeX failures
  retain source including delimiters. Trusted HTML/URL extensions are disabled.
- Raw Markdown HTML does not execute. Code and fallback source are escaped;
  links retain the parser's safe URL validation. Images attempt only HTTP(S) or
  embedded common raster formats, without reading local paths or adding Focus
  authentication headers. Images blocked by site CSP or failing to load retain
  their Markdown URL and alternative text.
- Mermaid uses the existing dependency in strict mode with sanitized SVG;
  failures retain the complete fence content.
- Images and fonts have bounded waits. Failed preparation retains source or
  URLs and tells users to review the preview. Top-level parsing or preparation
  exceptions fall back to the entire original Markdown. An export read failure
  shows an error and never enables the print button.

## Printing and lifecycle

`summaryPrintWindow.ts` synchronously opens the same-origin `?print=summary`
page during the click, avoiding popup blocking caused by waiting for history
first. A blocked popup prompts the user to allow popups and retry, without
starting an export. The preview accepts content only from the exact opener,
origin and one-use rendezvous ID; the sender validates the exact child, origin
and ID as well. Transfer content only in memory, never in URLs, localStorage or
server files. The page URL carries neither conversation content nor authentication
parameters. Successful delivery removes listeners and detaches the opener;
closure, timeout and read failures have cleanup/error paths. Reloading, directly
opening or sharing the preview URL does not restore its content.

The print entry never mounts `FocusApp` or registers a second active document.
Keep the original tab open until content arrives, after which the preview can
be used independently and printed repeatedly. Enable printing only after
rendering and resource preparation finish.

The button calls native `window.print()`. The browser owns printing, PDF saving,
paper, scale and headers/footers. Neither its return nor `afterprint` proves a
file was saved; cancelling permits retry. Provide instructions for desktop Save
as PDF, Android Chrome Share → Print and iPhone Safari Share → Markup. Actual
menus vary with platform and browser version; do not promise universal mobile
one-click downloads. Users can adjust landscape or scale for wide tables and
long formulas; fonts and browsers need not produce identical pixels.

## Verification boundaries

Unit tests cover complete code, math grammar and fallback, safe escaping, full
export calls, popup blocking, busy gates, origin-checked transfer and cleanup.
Browser verification covers wide/narrow menus, standalone preview, actual PDF
pagination and text, retry after cancellation, Markdown downloads and export
failure. Desktop Chromium and narrow viewport simulation cannot substitute for
physical Safari and Android Chrome system save workflow tests.
