# Focus Web single-file downloads and previews

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-file-download.zh-CN.md`.

## Access and file contents

Authenticated Focus Web sessions may download regular files readable by the Focus service account.
This uses the instance's fully trusted collaborator model, without workspace allowlists, per-file
approval, or user ACLs. The working directory only resolves relative paths. Symlinks may resolve
outside it; directories, devices and pipes are not downloadable. There is no directory tree, editing,
or archive creation. File previews read the same file endpoint only after an explicit browser action.

- `GET /api/files/info?path=...&cwd=...` checks the path, regular-file type and readability, returning
  exact `FocusFileInfo={path,name,size}`: resolved absolute server path, filename and nonnegative byte
  count. It checks metadata/open permission without reading the content. Relative paths require an
  absolute cwd; `~` expands against the service account.
- `GET /api/files/download?path=...&filename=...` accepts an absolute path; optional filename only
  suggests the client save name. No browser document or writer authority is required, allowing native
  browser downloads with session cookies and no token in the URL. Both endpoints use existing Host,
  session and trusted-proxy audience admission, do not renew the session, and do not call app-server
  or RuntimeLoop.
- Queries reject unknown/duplicate fields, empty paths and NUL. Missing, unreadable, nonregular or
  unresolvable files fail explicitly. Error responses have no attachment header.
- File transfers use `application/octet-stream`, `Content-Disposition: attachment` and
  `Cache-Control: no-store`. Existing aiohttp FileResponse provides bounded transfer and HTTP Range
  behavior; sibling `.gz/.br` static-asset substitution is disabled. Neither server nor page buffers
  the whole file during downloads, and no runtime dependency is added. Previews buffer bounded content
  in the browser as specified below.
- Downloads read the current file, not a historical copy from when the reply was generated. Files
  may change between inspection and download, so downloads recheck availability. Concurrent in-place
  writes have no snapshot guarantee, and Range does not guarantee resumption across file versions.

## Links and saving

`Markdown.vue` delegates local links to the Focus file download dialog. External URLs and links
inside Mermaid SVGs retain their semantics. Explicit Markdown links work during streaming; automatic
plain-text path detection still waits for stable output. Local URIs, percent escapes, absolute and
relative paths and common line references are converted to file paths; line numbers are not part of
the filename. Relative paths use the conversation cwd captured at click time. Network waits and
later conversation changes cannot redirect the download.
Local image references also become explicit file download links, without fetching or embedding the
image. Consumers without a file-action callback keep their existing unavailable notice.

Opening a link loads metadata only. The dialog shows server path, size, editable save name, actual
normalized filename, and either Save As or Download according to browser capabilities. Closing it
cancels requests and writes owned by the page.

- Native saving shares `browserFileSave.ts`, invoking `showSaveFilePicker` within the confirmation
  gesture before content fetching. Cancellation ends the attempt. SecurityError/NotSupportedError
  switches to explicit browser-download instructions and requires another click; no silent fallback.
- Native saving writes response chunks with progress in received bytes. Only successful writing and
  closing reports completion. Cancellation/failure attempts to abort staged writes, never starts an
  alternative download, and never deletes the chosen file. The picker may already have created an
  empty file.
- Without the picker, Download rechecks availability then hands off to native browser download
  management without a full Blob. Location follows browser settings. Focus reports only the handoff;
  progress/cancellation subsequently belong to the browser. Errors after the precheck are handled by
  the browser in a separate tab, preserving the conversation.
- Successful native writing/closing or browser handoff automatically dismisses the download dialog
  and displays a brief status notice; handoff does not claim completion. Failure or user cancellation
  keeps the dialog available for retry. Downloads started from a preview return to that preview on
  completion or dismissal, preserving its content and scroll position without fetching it again.
- Paths, handles and download state are not persisted. No content prefetch or automatic preview occurs.
  Save names use portable characters and a UTF-8 byte budget while preserving the extension. The server
  file is never renamed or changed.

Existing Markdown/JSONL exports share only the picker selection policy, retaining complete Blob,
naming, independent document title, cancellation and fallback behavior under the
[export filename contract](focus-web-export-filenames.md). PDF printing is unchanged.

## On-demand previews

The download dialog offers a separate Preview action. Opening a link reads metadata only; loading a
conversation, scrolling past links or opening file information does not prefetch content. Previews
reuse the session-authenticated file transfer, with no new endpoint, runtime dependency or wire
version. Only one preview is retained, with no persisted content or object URLs.

- `filePreview.ts` owns preview requests, cancellation, complete contents and object URL lifetime.
  Closing, replacing or refreshing cancels previous requests and releases their contents. Refresh is
  explicit and reads the current file, without historical snapshots or automatic tracking.
- Text/code/log/JSON/HTML and similar files show complete selectable, copyable read-only text with a
  line-wrap toggle. Strict UTF-8 and BOM-marked UTF-16 are supported. Unknown formats, binary data and
  unsupported encodings offer download, never silently replacing invalid characters. Text is limited
  to 1 MiB, checked at metadata, Content-Length and actual stream bytes so file growth cannot bypass
  the limit. Oversized files show an explicit notice rather than truncated text presented as complete.
  Conversation transcript pagination and presentation are unchanged.
- Markdown up to 128 KiB defaults to rendering with a source toggle; larger documents within the text
  limit show complete source with an explanation. Line references default to the corresponding source
  line, clamped to the last line. Relative links use the resolved file's directory, independent of
  later conversation changes. Math, tables, code and Mermaid share existing Markdown facilities with
  an isolated parser configuration: images (including reference images) become explicit links and raw
  HTML remains literal text, without attachment requests. Chat and print rendering stay unchanged.
- Initial image support covers PNG/JPEG/WebP original files, without thumbnails or transcoding.
  Transfers are limited to 16 MiB. Before creating a Blob URL or letting the browser decode pixels,
  `filePreviewImage.ts` inspects headers, limiting images to 24 million pixels and 32768 pixels per
  dimension. Invalid/unsupported images fail explicitly and remain downloadable.
- `ImageViewport.vue` shares fit, 100%, zoom, drag and pinch interactions between images and Mermaid.
  Photos use browser-decoded EXIF-oriented dimensions. The viewer never changes server files.
- Desktop uses a large dialog and narrow screens use the full viewport. Closing restores conversation
  focus and scroll position. Download and refresh remain available; filename editing and native Save
  As keep their behavior. Closing a nested Mermaid viewer does not also close the file preview.
- One toolbar contains close, a shrinkable filename, download, the Markdown source/render toggle,
  content copy and refresh. Icon actions have text labels and 44px touch targets. Long names use middle
  ellipsis, retaining both ends. Tapping the name opens an independently scrollable overlay with the
  complete filename and server path, each separately copyable; desktop hover also reveals the full name.
  Tapping the name again, tapping outside or pressing Escape dismisses the overlay without resizing or
  scrolling the content; Escape closes only the current layer. Explanations such as no automatic refresh,
  source line wrapping and image gesture help live in this overlay; image zoom controls remain directly
  available. Large Markdown shown as source retains a compact source indicator with the reason in the
  overlay. Line location and copy results use temporary notices.

PDF, Office and audio/video have no embedded preview yet. Existing PDF export printing is unaffected.
