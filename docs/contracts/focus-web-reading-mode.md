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

## Reading toolbar

Wide and narrow reading toolbars offer exit, session switching, Prompt history,
available exports, runtime details and settings. Narrow layouts use that order;
wide layouts retain their reversed order. Keep a single row with 30px icon
buttons. The session title shrinks to the remaining space and truncates with an
ellipsis rather than shrinking icon buttons or overflowing the page horizontally.

Runtime details uses the existing information icon and runtime-status dot;
settings uses the gear icon. Both reuse the existing detail and settings panels.
Opening either closes the export menu, session switcher and the other panel.
Opening or closing these panels does not exit reading mode, remount the transcript
or explicitly change the reading position; closing returns to reading.

## Viewport reconciliation, compositing, and diagnostics

`web/src/focus/focusViewport.ts` owns the fixed shell's visible height and top
offset. Each reading-mode entry or exit rereads and synchronizes viewport sizing
after the DOM update, on the next animation frame, and once after a short delay.
This covers hidden chrome/composer changes and mobile browser UI animations.
Reconciliation does not remount conversation components, write transcript scroll
positions or drafts, or poll continuously. Rapid transitions and disposal cancel
stale callbacks. Zero, negative, and non-finite viewport heights fall back to
window and document height, retaining the previous size if none is valid. Visible
document and page-cache restoration also resynchronize the viewport.

Narrow reading mode uses a separate composited surface so entering the mode
updates the fixed page's compositing state; exiting or switching to a wide layout
removes it. This addresses the ArkWeb device report of a second-entry blank page
despite correct dimensions, positions, and visibility styles, recovering after
rotation. It does not depend on user-agent detection, change layout dimensions,
remount the transcript, or write scroll positions.

“Runtime details → Page layout diagnostics” defaults to recording off; expanding
the panel does not start it. “Start recording” begins layout measurements and
diagnostics, continuing after the details panel closes so the issue can be
reproduced. “Stop recording” immediately stops further sampling and retains the
results for copying or downloading; starting again clears the old records. The toggle belongs
only to this document and resets to off with empty records on reload. While off,
no diagnostic layout nodes, styles, or hit positions are read and no diagnostic
snapshots are built. Necessary viewport synchronization and reading-mode
compositing remain independent.

The panel explains that these measurements help investigate layout and viewport
issues, including blank pages, misplaced content, and display problems after
reading-mode, orientation, or keyboard changes. They do not collect network
requests, application errors, or conversation text. The UI distinguishes not yet
started, recording, and stopped with retained results; when results exist, the
start button says “Start recording again”. Sampling follows reading-mode and
viewport changes rather than a one-time check or continuous polling.

Copying or downloading includes the browser identifier, measurements at recording
start, the last six mode transitions, and the last six viewport changes. New events
replace the oldest of their kind while the initial snapshot remains. Separate
limits keep rotation from evicting transition evidence. Records contain
only known layout nodes' dimensions (including document and mount roots), scroll
offsets, visibility and compositing styles, focused tag name, and timestamps.
Toolbar and transcript center-point hit tests record the hit tag, whether it is
inside the expected region, and whether a dialog covers it. They never record hit
nodes' text, attributes, or selectors, conversation text, drafts, URLs, or credentials.
They remain in this document's memory, clear on reload, and are never uploaded
automatically. “Download JSON” saves the complete snapshot available at the click,
with the same content as copying and a timestamped filename; it is disabled until
records exist. Copying and downloading do not change the recording toggle, and
later sampling does not alter an already generated file. If the download cannot
start, the panel shows failure feedback and the results remain available to copy.
Measurements distinguish sizing and layout failures but do not
prove that pixels were painted correctly. Mobile blank-page regression checks
require normal → reading → normal → reading on the affected device; desktop
emulation alone cannot establish success.

## Export

`ReadingModeControls.vue` offers the current session's export menu in wide and
narrow layouts. The existing `export` capability enables Q&A Markdown and
Print / Save as PDF; paginated history additionally enables thread JSONL. Hide
the entry without a session or export capabilities, and disable it while loading
a conversation or fetching export content. The existing export gate still covers
the entire naming and saving flow. Close the menu when the session or capabilities
change, the session switcher opens, the viewport layout changes, or reading mode
ends. Outside pointer actions, focus leaving the menu, and Escape also close it;
Escape returns focus to the export button.

The menu emits only the current session's format selection. `FocusApp.vue` routes
it through the existing `FocusThreadActions.vue` flow without leaving reading
mode or extracting content from the reading window or chat DOM. Naming, independent
document titles, system Save As and download fallback follow the
[export filename contract](focus-web-export-filenames.md); PDF follows the
[Q&A printing contract](focus-web-summary-print.md). The session switcher remains
limited to reading navigation.

`FocusTransientNotice.vue` owns presentation and automatic cleanup of transient
feedback from user actions, including in reading mode. A failed export read must
show failure feedback. Notices appear below the reading toolbar without
intercepting pointer actions or restoring the normal mode's persistent alerts.

Performance and connection diagnostics share the default-off recorder. Manual recording retains at most 64 numeric samples of body-load duration, event bytes, close codes, buffer overflows and supported long tasks. Stop freezes samples and restart clears them. Content, thread identities, URLs and raw close reasons are excluded; see the [bounded transcript contract](./focus-web-transcript-window.md).
