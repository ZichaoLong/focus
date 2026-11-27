# Focus Web Q&A printing and PDF saving contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-summary-print.zh-CN.md`.

## Scope and entry points

The desktop conversation menu, sidebar session menu, narrow top export menu,
narrow session switcher and reading-mode export menu at every viewport size offer
both Export Q&A Markdown and Print preview
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
Print exports may request a short-lived server snapshot. Ordinary Markdown exports retain their existing response.

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

## Server PDF download

Tapping Download PDF and confirming the destination starts a server job using the authorized Markdown snapshot, selected turns and edited plain-text title. Focus tries a locally installed Chromium-family browser first. A missing, failed or timed-out browser (25 seconds) selects the built-in renderer. Both paths use fonts, formula assets and print styles delivered at installation. Export works without outbound network access. Preparing main uses the existing build and locked Python dependency installation. Browser availability is checked at export time.

The built-in renderer embeds Chinese text, mathematical symbols and formula graphics, paginates long code and expands wide tables into labeled rows. Only available embedded images are loaded. Other images retain their address or alternative text. Unrenderable formulas and diagrams retain their source. Detected missing glyphs are identified by Unicode code point. Rich layout failure triggers an attempt to preserve the complete source. The result names the engine, detected issues and affected turns where known. Resource exhaustion, timeout and write errors are reported.

An installation data root runs one renderer at a time. Snapshots expire after one hour and completed files after fifteen minutes, subject to count and space bounds. Creation, status and file delivery require the matching session and snapshot. Creation also requires same-origin CSRF admission. Repeated submissions with the original job identifier reuse the result. A short disconnection resumes polling the same job. The preview reports queuing, formula counts, pagination, transfer and elapsed time. It distinguishes a completed file write from handing a file to the browser download manager.

## Printing and lifecycle

Print invokes the browser print interface or the current mobile WebView's system print adapter. An explicit rejection shows the reason immediately. When the preview stays in the foreground for about three seconds after a job receipt, it offers “Didn’t see a print dialog?” with the download action. Users can retry printing. Cancellation preserves the selection, title and preview. Only a completed file write confirms a save. Mobile Back or closing the preview returns to the original conversation. [Mobile host contract](focus-mobile.md)

The selection dialog opens the same-origin print window during its confirmation gesture. A blocked popup preserves the options for retry. Sender and receiver verify origin, exact window and a one-time rendezvous ID before transferring content and download credentials in memory. Only the rendezvous ID appears in the URL. Successful handoff removes the listeners and detaches the opener. The preview renders independently without registering a second active document. Reloading requires a new export.

## Verification boundaries

Unit tests cover complete code, math grammar and fallback, safe escaping, full
export calls, popup blocking, busy gates, origin-checked transfer and cleanup.
Browser verification covers wide/narrow menus, standalone preview, actual PDF
pagination and text, retry after cancellation, Markdown downloads and export
failure. Desktop Chromium and narrow viewport simulation cannot substitute for
physical Safari and Android Chrome system save workflow tests.
