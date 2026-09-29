# Focus Web export filename contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-export-filenames.zh-CN.md`.

## Naming and downloading

Browser Q&A Markdown and current-thread JSONL exports ask for a filename before
reading the complete content. `FocusThreadActions.vue` owns the dialog, selected
thread title lookup and cancellation; `createFocusThreadActions` owns the fixed
export target, mutual exclusion, system file selection and Blob saving; `exportFilename.ts` provides
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
  The filename only sets the system save dialog's `suggestedName` or the browser's
  `download` attribute. The separate document
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
or append a collision suffix. System Save As is an optional enhancement with no
new backend or deployment dependencies:

- In a secure context with `showSaveFilePicker`, the naming dialog's confirmation
  gesture opens the system save dialog before any export fetch. Supply the format's
  suggested name and file type; users can choose a client-device directory and
  change the final filename there. The document title stays independent. Focus
  neither persists file handles or paths nor sends them to the server, and does
  not request directory access.
- If the API is absent, the context is insecure, or invocation is unavailable with
  `SecurityError` / `NotSupportedError`, use the existing Blob download and browser
  download settings. Detect capabilities, not OS or browser names.
- Cancelling the system dialog (`AbortError`) ends the export without fetching,
  fallback downloads or success notifications. Other selection or save failures
  show an error without silently downloading another copy or claiming success;
  a later action can retry.
- Naming, the system dialog, fetching and file writing share the export gate and
  cannot retarget the selected thread while waiting. Open a writable stream only
  after the complete Blob, including any Markdown title replacement, is ready.
  Report completion only after both writing and closing succeed. Attempt to abort
  the stream on write or close failure. Failed reads do not overwrite existing
  files; the system dialog may already have created a new empty file. Focus does
  not automatically delete the user's selected file.

## PDF suggestion

Printing adds no naming dialog and still opens the preview synchronously on click.
The selected thread's `.pdf` suggestion travels with the full Markdown in memory.
The print page sets `document.title` to the suggestion without the extension for
browsers to use as a default save name. The preview has an editable document title,
defaulting to the clicked thread's title, that immediately updates the printed H1
through plain text binding. It leaves the suggested filename in `document.title`
independent. Browsers need not adopt that name; users can rename in the system save UI. Lifecycle and device limits follow the [Q&A print contract](focus-web-summary-print.md).
