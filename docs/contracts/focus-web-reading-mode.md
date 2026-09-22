# Focus Web reading mode

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-reading-mode.zh-CN.md`.

## Entry and loading

Reading mode belongs to the current browser page. It is not stored in a session
or a persistent preference. With valid document access and a selected session,
the desktop conversation header and narrow top bar offer reading mode whenever
the conversation is loading or has readable content. Switching sessions must not
hide the entry while waiting for content.

Selecting reading mode during loading immediately shows the reading layout with
the selected conversation's loading state. Exit and session switching remain
available. Content appears in that layout when it arrives, without another click.
The initial connection screen can still record a page-local reading intent and
consume it when the selected conversation becomes eligible for reading mode.

## State boundaries

- A new-chat page with no selected session does not offer reading mode.
- Reading mode survives session switches; temporary absence of content during
  loading does not cause an exit.
- A settled empty conversation returns to normal mode instead of an empty
  reading page.
- Opening a new-chat page, requesting input, or losing document access exits
  reading mode.
- The user may exit during loading; arriving content must not re-enter the mode.

`web/src/focus/FocusApp.vue` owns entry eligibility, while
`web/src/focus/focusReadingMode.ts` owns the page's presentation mode and pending
initial connection intent. Existing client owners retain session selection and
loading responsibility.
