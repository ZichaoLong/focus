# Focus mobile containers

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-mobile.zh-CN.md`.

## Entry and authentication

An entry stores its name, origin, random instance ID and optional web-login mode. Only the selected business page runs.
Remote entries require platform-validated TLS. Local Focus authorization also accepts HTTP on phone loopback (`localhost`, `127.0.0.1`, `[::1]`). Basic credentials require HTTPS. Native Basic authentication uses a dedicated script-disabled top-level GET of
`/focus-connect.txt`. Subresources and redirects cannot solicit stored credentials. The exact origin and Basic challenge realm
must match. The engine owns subsequent HTTP and WebSocket Upgrade authentication within that protection space.
A rejected credential requires user correction. A timeout preserves credentials. This version supports a site-wide Basic
protection space. The entry can be reverified when the live page encounters a challenge. Focus cookies, registration,
trusted proxy proof and mutation admission follow the external-access and wire contracts.

## Host protocol v1

The `focusApp` URL query asks the root page to wait briefly for negotiation. The host checks its exact top-level origin,
root path and `meta[name=focus-mobile-contract][content="1"]`. It installs a per-document random ticket, instance ID,
protocol version and feature list and dispatches `focus-host-ready`. Unknown versions and missing offers use browser defaults.

- `wake` accepts `focus-host-resume` and `focus-host-pause`. Foreground uses the transport wake check. Background flushes text and reading coordinates.
- `thread` accepts the last thread hint from the root document using the ticket-bound `thread` operation (up to 256 characters, empty for a workspace). The shell encodes it into the next root URL. Web must confirm that target through existing server navigation.
- `resume` identifies a single recoverable window per instance. Web persists client hints, GET locators, existing writer-bound recovery records,
  last thread and text drafts. Each new document registers. Unsent text and verifiable reading anchors use the instance and confirmed thread or workspace.
  Attachments, approvals and send scopes still require the acknowledged writer.
- `save` uses `prompt("focus/1/<ticket>/<op>", value)` to await a native picker or write.
  `choose` accepts a filename. The user chooses the destination. `write` acknowledges Base64 chunks of at most 24 KiB of bytes.
  `finish` copies the staged file to the selected destination. `abort` releases staging. Success returns `ok`.
  Cancellation or failure stops the write. Existing authenticated Web reads supply the contents. HTML uploads use the system picker and the existing Web uploader.
- `print` accepts a ticket-bound print request with a job name up to 255 characters. Web lays out the prepared, complete Q&A preview. The shell passes the current WebView to the system print service. The content stays in document memory.

Navigation, instance switching and teardown revoke the ticket. External documents and sandboxed HTML previews receive no bridge.
The protocol accepts no arbitrary URLs, paths, scripts or business retries. Push registration, notification permissions and native updates
require separate capabilities.

## Usage and verification

[Build, install and verify](../../mobile/README.md)
