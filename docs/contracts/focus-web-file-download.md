# Focus Web single-file downloads

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-file-download.zh-CN.md`.

## Access and file contents

Authenticated Focus Web sessions may download regular files readable by the Focus service account.
This uses the instance's fully trusted collaborator model, without workspace allowlists, per-file
approval, or user ACLs. The working directory only resolves relative paths. Symlinks may resolve
outside it; directories, devices and pipes are not downloadable. There is no directory tree, editing,
archive creation, or file/media preview surface.

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
- Downloads use `application/octet-stream`, `Content-Disposition: attachment` and
  `Cache-Control: no-store`. Existing aiohttp FileResponse provides bounded transfer and HTTP Range
  behavior; sibling `.gz/.br` static-asset substitution is disabled. Neither server nor page buffers
  the whole file, and no runtime dependency is added.
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
- Paths, handles and download state are not persisted. No content prefetch or automatic preview occurs.
  Save names use portable characters and a UTF-8 byte budget while preserving the extension. The server
  file is never renamed or changed.

Existing Markdown/JSONL exports share only the picker selection policy, retaining complete Blob,
naming, independent document title, cancellation and fallback behavior under the
[export filename contract](focus-web-export-filenames.md). PDF printing is unchanged.
