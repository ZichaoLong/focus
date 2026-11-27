# Focus Web Q&A printing and PDF saving contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-summary-print.zh-CN.md`.

## Scope and entry points

The desktop conversation menu, sidebar session menu, narrow top export menu,
narrow session switcher and reading-mode export menu at every viewport size offer
both Export Q&A Markdown and Save PDF or print
when the existing `export` capability is available. Printing shares the busy
gate with Markdown and thread-data exports.
Filename dialogs and PDF default suggestions follow the
[export filename contract](focus-web-export-filenames.md).

`createFocusThreadActions` first asks for [export range](focus-web-summary-export.md) and title,
then obtains the complete selected Markdown through the existing
authenticated `exportThreadSummary` operation. Content and limits belong to
`POST /api/threads/{thread_id}/export-summary` in the [Web wire contract](focus-web-wire.md).
Never export a subset from the chat DOM, loaded history window or reading mode.
Keep the exclusions for tool activity, reasoning and non-text attachments.
The PDF consumer adds no PDF endpoint, server browser dependency, external conversion service or PDF-specific wire DTO.

## Completeness and rendering

`SummaryPrintApp.vue` owns the standalone document; `summaryPrintMarkdown.ts`
owns static rendering and `summaryPrintPreparation.ts` prepares diagrams, images
and fonts. Preview the entire export without chat virtualization, progressive
batches, code folding or head/tail diff truncation. Code retains every line and
can wrap and span pages. Tables wrap cells, span pages and repeat headers.
The native print layout hides controls and instructions.

CJK punctuation emphasis and bold font fallback follow the shared
[prose rendering contract](focus-web-markdown-rendering.md).

The document title is independent of the filename. A preview input replaces only
the exporter-generated first heading and displays user input as plain text. Edits
update the printed H1 without re-rendering Q&A or reloading images, math or diagrams;
the input is hidden in print. Top-level rendering failure retains the normalized
title and complete Q&A source.

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

## Direct PDF saving

Once the preview is ready, Save PDF directly generates an A4 document on the client from the complete selection and the current document title. The browser uses the shared file picker or download, and mobile hosts use their existing `save` file protocol. The click chooses the destination first. Cancelling leaves the preview available. Duplicate submissions are disabled during saving. Closing the preview releases its worker and staged mobile file. The UI distinguishes a completed write from handing a file to the browser download flow.

The shared Web client loads the layout worker, WebAssembly and the font subsets used by this document from the instance on demand. Chinese prose is selectable and searchable. Code spans pages and tables repeat their headers. Formulas and Mermaid diagrams use the prepared preview graphics, and images use pixels already loaded by the preview. A failed graphic conversion retains its source or address and shows a notice. Missing glyphs produce a PDF with a visible placeholder notice. Desktop and mobile use the same path. Linux hosts provide the existing Q&A export and static assets.

## Printing and lifecycle

`summaryPrintWindow.ts` synchronously opens the same-origin `?print=summary`
page during the range dialog's confirmation click, avoiding popup blocking caused by waiting for history
first. A blocked popup retains the options and prompts the user to allow popups and retry, without
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

The System print button calls native `window.print()`. The browser owns printing, PDF saving,
paper, scale and headers/footers. Neither its return nor `afterprint` proves a
file was saved; cancelling permits retry. Provide instructions for desktop Save
as PDF, Android Chrome Share → Print and iPhone Safari Share → Markup. Actual
menus vary with platform and browser version; do not promise universal mobile
one-click downloads. Users can adjust landscape or scale for wide tables and
long formulas; fonts and browsers need not produce identical pixels.

With the negotiated mobile `save` or `print` capability, Web hands the complete export to `SummaryPrintApp` in the current document's memory. The preview occupies the visible and printable layout. Hosts offering `print` use the WebView's system print adapter for System print. Closing the preview or going back returns to the conversation. A reload requires a new export. [Mobile host contract](focus-mobile.md)

Print diagnostics in the mobile preview start disabled. Once enabled by the user, the preview records the reported app and engine versions, print button taps, host bridge replies, host pause/resume signals, page visibility and window focus changes in memory. It retains the latest 40 events with elapsed times, the total number of taps and a count of discarded events. A bridge reply and visibility changes each describe a limited observation. The user confirms whether a panel appeared or a file was saved.

Stopping, copying, saving or a five-minute timeout ends recording. Copy and save freeze the same JSON for inspection, clipboard export or saving through the negotiated system file picker. Starting again replaces the report. Closing or reloading the preview clears it. Only predefined fields and events are collected. Document content, titles, filenames, URLs, credentials, raw errors and unrecognized host reply text are excluded. Reports remain local.

When the host negotiates `print-diagnostics` and recording has started, the preview also offers “Print one test page”. On stop, the `native` field in the same report identifies conversation and native test requests by tap number. It includes host results and the system's start, layout, write and finish calls into each adapter. Web and native elapsed times use separate clocks and share the tap numbers. A callback records a requested stage. Panel visibility and the saved PDF require separate confirmation. An expired or invalidated native session without a readable snapshot is marked unavailable. Hosts offering only `print` keep the existing Web diagnostics.

With `print-job-diagnostics`, the preview asks the user to wait about 35 seconds after the last tap before copying. The separate `native.observations` field contains system UI launch calls, Focus window and Activity changes, and timed samples for the matching job. Each row carries native elapsed time, tap number and source. A `job-not-listed` sample means the query did not find this job. Its final outcome is unknown from that sample. Missing or malformed observations leave the adapter callbacks available.

## Verification boundaries

Unit tests cover complete code, math grammar and fallback, safe escaping, full
export calls, popup blocking, busy gates, origin-checked transfer and cleanup.
Browser verification covers wide/narrow menus, standalone preview, actual PDF
pagination and text, retry after cancellation, Markdown downloads and export
failure. Desktop Chromium and narrow viewport simulation cannot substitute for
physical Safari and Android Chrome system save workflow tests.
