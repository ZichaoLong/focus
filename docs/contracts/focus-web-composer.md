# Focus Web composer

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-composer.zh-CN.md`.

## Presentation state and ownership

`ConversationPane.vue` owns compact, expanded and hidden presentation through `setComposerSurfaceMode`, including both
new-conversation and existing-thread entry points. `Composer.vue` requests transitions through events; `ChatDock.vue`
forwards state and actions. `useComposerDraft` continues to own the same input, scoped draft and persistence boundaries.
Presentation changes create no second draft, neither remount nor move the textarea, and do not change shortcuts, submission or receipts.

The narrow compact input remains approximately four lines with internal overflow and explicit expansion. Wide expansion
keeps the existing approximately 70vh editor. Presentation is not persisted; changing conversation or crossing the narrow/wide
layout boundary returns to compact, while drafts retain their existing conversation scope.

## Keyboard editing and page boundaries

PgUp and PgDn retain native caret movement and text scrolling in both compact and expanded inputs. They must not scroll
the application frame horizontally, move the thread sidebar outside the viewport or change the draft text. The fixed
application frame only clips overflow; each inner panel owns its own scrolling range.

`ConversationToc.vue` retains its navigation node and position measurement when space is insufficient, but hidden content
and hover targets must not widen the application frame. A wider window reveals the same navigation node again, preserving
access to Prompt history. Wide-table occlusion retains the original rail dimensions for the existing overlap checks.

## Narrow expanded editing

Expansion uses the visible page: temporarily hide thread navigation, submission history and transcript, retaining a short
conversation title ("New conversation" for a draft), a clear Collapse button and the original input toolbar. Keep transcript
owners mounted but invisible and inert; do not unload history, reread the thread or replace the reading anchor. Hide the
new-conversation welcome area and workspace picker while expanded.

The editor fills remaining height independently of text length, without the 280px or 34dvh cap. Reuse the visible height and
top offset owned by `createFocusViewport` in `focusViewport.ts`: keyboard and browser-chrome changes resize the editor while
keeping its toolbar visible. Long text scrolls inside the textarea; attachments have bounded overflow and slash/file menus
open inside the editing area. Browser chrome and the system keyboard remain browser-managed.

Expansion/collapse retains the same textarea, draft, selection and IME state. Collapsing does not force a dismissed keyboard
back open. The existing transcript scroll owner preserves reading position; new user intent such as sending may follow the
tail under existing rules. Late layout callbacks cannot restore another thread's old anchor after navigation.

`FocusApp.vue` consumes only the pane-derived presentation state to hide navigation. Error, connection and access notices
remain visible. Pending questions and approvals take visual priority and temporarily release the expanded layout while
retaining the composer owner and draft; expanded editing may resume after the interaction. Confirmed non-submission
(`known_no_effect`) retains text and expansion. Collapse only when the current draft's receipt permits clearing. Unknown
outcomes retain the identity, receipt and recovery boundaries in [Prompt mutation recovery](./focus-web-prompt-mutation-recovery.md);
layout changes must not reauthorize sending the same content.

## Verification

Browser regressions cover narrow available space, visual viewport height/offset changes, selection, IME submission guards,
textarea identity, draft and transcript position, failed/successful submission, new conversations and narrow/wide transitions.
Desktop regressions cover native PgUp/PgDn in compact/expanded inputs, sidebar position and navigation hiding/recovery.
Desktop narrow viewports and simulated keyboard sizing do not replace real HarmonyOS or other device IME, keyboard animation
and browser-paint verification.
