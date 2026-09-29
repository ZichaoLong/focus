# Focus Web export filename contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-export-filenames.zh-CN.md`.

## Naming and downloading

Browser Q&A Markdown and current-thread JSONL exports ask for a filename before
reading the complete content. `FocusThreadActions.vue` owns the dialog, selected
thread title lookup and cancellation; `createFocusThreadActions` owns the fixed
export target, mutual exclusion and Blob download; `exportFilename.ts` provides
suggestions and normalization. Defaults use the clicked thread's title, including
non-active sidebar sessions. Unavailable names fall back to
`codex-conversation-summary.md` or `codex-thread-data.jsonl`.

- The input displays the complete filename, adds the format's extension and
  collapses repeated matching extensions. Normalize to Unicode NFC, replace path
  separators, unsupported and control characters, trim edge dots and spaces,
  avoid Windows device names, and truncate at Unicode code point boundaries to
  at most 200 UTF-8 bytes including the extension. Always preview the name sent to
  the browser below the input. Empty names cannot be confirmed.
- Cancel, close, overlay click, Escape and host component unmount cancel the
  pending naming request without reading or downloading export content. Never
  persist the entered name, send it to the server or include it in URLs.
- Markdown, JSONL and printing share a gate while the dialog or export is active.
  Check the client's export state again after confirmation. Capture the target
  thread ID and suggested name before waiting; navigation cannot retarget them.
- Confirmation reads the complete Blob through the existing authenticated API.
  The filename only sets the browser's `download` attribute. The separate document
  title replaces only the exporter's generated leading heading, preserving Q&A
  text, JSONL data and the endpoint's default
  `Content-Disposition`. Content scope remains in the [Web wire contract](focus-web-wire.md).

The Markdown dialog also offers an independent document title, defaulting to the
clicked thread's title. Missing or blank titles use `Codex conversation summary`.
`summaryDocumentTitle.ts` normalizes it to a single line of plain text and escapes
Markdown syntax. Only the known generated leading heading is replaced; unfamiliar
openings and headings inside Q&A remain intact. Editing this title does not rename
the session or track filename edits. It stays in memory, out of URLs and server
requests. JSONL has no document title field.

The browser owns the final name and location and may further sanitize characters
or append a collision suffix. No `showSaveFilePicker`, backend or deployment
dependency is required.

## PDF suggestion

Printing adds no naming dialog and still opens the preview synchronously on click.
The selected thread's `.pdf` suggestion travels with the full Markdown in memory.
The print page sets `document.title` to the suggestion without the extension for
browsers to use as a default save name. The preview has an editable document title,
defaulting to the clicked thread's title, that immediately updates the printed H1
through plain text binding. It leaves the suggested filename in `document.title`
independent. Browsers need not adopt that name; users can rename in the system save UI. Lifecycle and device limits follow the [Q&A print contract](focus-web-summary-print.md).
