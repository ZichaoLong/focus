# Shared Backend and Resume Safety

See also:

- `docs/architecture/fcodex-shared-backend-runtime.md` for the current shared-backend and
  wrapper runtime model
- `docs/contracts/runtime-control-surface.md` for the shared state vocabulary used by
  `/status`, `/detach`, and the local admin surface
- `docs/contracts/thread-profile-semantics.md` for exact command and wrapper semantics
- `docs/architecture/feishu-codex-design.md` for architecture and repository boundaries

## 1. Upstream Baseline

- Upstream project: [`openai/codex`](https://github.com/openai/codex.git)
- Current local validation baseline: `codex-cli 0.118.0`, resolved locally to
  upstream tag `rust-v0.118.0`
  (`b630ce9a4e754d35a1f33e4366ba638d18626142`) and checked on 2026-04-03
- If this document later needs specific upstream source references, prefer
  commit-pinned `openai/codex` permalinks against that baseline instead of
  developer-local checkout paths
- This document focuses on safety and `/resume` semantics. It intentionally does
  not restate most wrapper/runtime details; those belong in
  `fcodex-shared-backend-runtime`.

## 2. Problem Statement

Two frontends are safe only when they write the same thread through the same
app-server backend.

If they resume the same persisted thread through different app-server processes,
they can each materialize their own live in-memory thread and append
conflicting state later.

After multi-instance support, this rule must be read more explicitly:

- multiple instances may share `CODEX_HOME` and the persisted thread namespace
- but at any moment, one thread may have live runtime residency in only one
  instance backend
- bare `codex` running its own isolated backend is still fully outside that
  coordination path

This document defines the current safety model for:

- shared backend operation
- `/resume` for threads not loaded in the current backend
- Feishu multi-chat behavior for the same thread

## 3. Verified Constraints

### 3.1 Hard facts we can rely on

- Within one app-server process, resuming an already-loaded thread reuses the
  loaded thread and subscriber model rather than creating a second live copy.
- `thread/loaded/list`, `thread/list.status`, and `thread/read.status` only
  describe the current app-server process.
- `thread/read` is a stored-history read and does not create a live thread.
- `thread/resume` loads the thread into the current app-server as a live thread.

### 3.2 Facts we cannot rely on

- We cannot reliably detect whether another stock TUI process is currently
  writing the same thread.
- `source` and `service_name` are provenance hints, not live ownership or lock
  signals.
- We cannot force another stock TUI process to stop writing.
- We cannot auto-attach to a stock TUI embedded app-server with current public
  mechanisms.

## 4. Core Safety Rule

Use one rule everywhere:

- One thread should be written through one backend.

If the user wants Feishu and local TUI to operate on the same live thread
safely, both must connect to the same app-server backend.

In this repository, that now splits into two layers:

- **within one instance**: Feishu and `fcodex` may safely share that instance backend
- **across instances**: a machine-level `ThreadRuntimeLease` prevents one
  thread from being live-attached by two instance backends at the same time

## 5. Backend Safety Boundary

### 5.1 Shared backend within one instance

This is the recommended safe path.

Properties:

- Feishu and local TUI write through the same app-server backend
- the same loaded thread state is shared
- multiple local TUI windows can attach to that backend without creating
  cross-process divergence

How the current runtime and `fcodex` wrapper make that work is documented in
`docs/architecture/fcodex-shared-backend-runtime.md`.

### 5.2 Another `feishu-codex` instance backend

This is the new boundary introduced by multi-instance support.

Properties:

- multiple instances share the persisted thread namespace
- each instance has its own live backend
- before cross-instance attach / continue, the system first checks whether
  another running instance still reports that thread as `loaded`
- after the loaded gate passes, the machine-level `ThreadRuntimeLease` is still
  claimed atomically to prevent resume races
- if another instance still holds the loaded runtime, or the loaded fact cannot
  be verified safely, the write attempt must reject clearly instead of trying
  to take the runtime away

So this is neither "one shared backend" nor "two backends that may dual-write".
It is a coordinated path with a shared persisted namespace but strictly
single-owner live runtime.

### 5.3 Bare `codex` isolated backend

This is what happens when the user runs stock TUI outside the shared backend.

Properties:

- `feishu-codex` cannot know whether that local TUI is idle, closed, or about
  to write
- `feishu-codex` cannot safely assume exclusive ownership of such a thread
- local continuation of the same live thread should use `fcodex` and the same
  instance shared backend instead
- continuing to write the same thread through bare `codex` on another backend
  is outside the supported safe path

## 6. `/resume` Safety Model

### 6.1 Classification

After matching the target thread, classify it using only hard facts:

1. `loaded-in-current-backend`
2. `not-loaded-in-current-backend`

Do not add a third "probably safe" class based on cached ownership heuristics.

### 6.2 Loaded in current backend

If the target thread is already loaded in the current `feishu-codex` backend:

- resume directly
- bind the current Feishu chat to that thread
- do not show a risk card
- `resume` does not use this path to rewrite the live runtime's profile or
  provider

This is safe because the thread already lives in the same backend.
`resume` still does not reinterpret the loaded thread through an extra
project-owned profile/provider slice.

### 6.3 Not loaded in current backend

If the target thread is not loaded in the current backend, this repository's
safety decision is to call `thread/resume` directly.

Behavior:

- resume the target thread immediately
- bind the current Feishu chat to that thread
- if the user later attaches through `fcodex` on the same instance shared backend,
  Feishu and `fcodex` can continue operating on the same live thread safely
- if another running instance still keeps that thread loaded, the loaded gate
  rejects fail-closed
- if the loaded gate passes but another instance wins the atomic lease claim
  first, the write attempt still rejects fail-closed and routes the operator
  back to the loaded owner or to `reset-backend`
- `resume` does not replay any extra project-owned thread-wise
  profile/memory/provider slice

This path assumes:

- local continuation of the same thread uses `fcodex`
- bare `codex` is not also writing that thread through another backend

One detail should be recorded explicitly: the common semantics are now narrower
than the older profile-restore model.

- neither Feishu nor `fcodex` replays a project-owned thread-level
  profile/memory slice on resume
- the backend startup baseline comes from the instance backend that is actually
  running
- turn-time overrides remain frontend-owned rather than thread-owned
- Feishu may still carry admission-related binding settings needed for the
  immediately following turn, but that does not create thread-level persisted
  truth

One implementation detail now needs to be recorded explicitly: ordinary
unloaded-thread `/resume` still resumes directly, but unloaded + persisted
`goal=active` is no longer treated as an ordinary direct-resume case. The
current UI shows a confirm card because there are two materially different
behaviors:

- `Direct resume`
  - call `thread/resume` directly
  - then patch loaded-thread settings via `thread/settings/update`
  - if app-server auto-continues the active goal immediately, the first
    autonomous goal turn is only guaranteed to see whatever loaded-thread
    settings were already effective in backend
- `Resume with current settings and keep paused`
  - first pause the persisted goal
  - then cold-resume the thread while carrying the small resume-time override
    slice that upstream accepts
  - then queue loaded-thread settings synchronization
  - but keep the goal paused instead of auto-resuming it

Avoiding dual-backend writes for such threads is still an operational rule, not
a broad UI-enforced guard.

Multi-instance mode no longer adds a separate thread-admission filter:

- all instances resolve persisted threads from the same shared namespace
- Feishu `/threads` and `feishu-codexctl thread list --scope cwd` are
  current-directory views over that namespace
- once a path actually wants live runtime residency, all of them still obey
  the same `ThreadRuntimeLease`

### 6.4 Current command-state matrix

The current repository behavior around `/resume` and `/goal resume` depends on
four axes:

1. whether the thread is already loaded in the current backend
2. whether the upstream goals feature is enabled
3. the persisted goal status
4. whether the current Feishu binding is attached or detached

The most important distinction is between:

- `cold overrides`
  - fields carried on `thread/resume`
  - currently: `model`, `approval_policy`, `permissions_profile_id`,
    `reasoning_effort`
- `queued loaded-thread sync`
  - `thread/settings/update`
  - includes `collaboration_mode`, but upstream only acknowledges that this
    update was queued

#### `/resume`

| Pre-state | UI path | Effective sequence | Automatic goal continuation | Settings guaranteed before the first resumed goal turn |
| --- | --- | --- | --- | --- |
| loaded, any goal state | no confirm | `thread/resume -> bind -> thread/settings/update` | no extra continuation triggered by wrapper | none beyond whatever was already loaded; sync is queued |
| unloaded, goals disabled | no confirm | `thread/resume(cold overrides) -> bind -> thread/settings/update` | no goal path available | cold overrides only |
| unloaded, no goal | no confirm | `thread/resume(cold overrides) -> bind -> thread/settings/update` | none | cold overrides only |
| unloaded, goal paused | no confirm | `thread/resume(cold overrides) -> bind -> thread/settings/update` | none; goal stays paused | cold overrides only |
| unloaded, goal active, direct resume | confirm: direct resume | `thread/resume -> bind -> thread/settings/update` | app-server may continue immediately | no wrapper guarantee that current binding settings won the race |
| unloaded, goal active, keep paused | confirm: keep paused | `thread/goal/set(paused) -> thread/resume(cold overrides) -> bind -> thread/settings/update` | none; goal remains paused | cold overrides only |

#### `/goal resume`

| Pre-state | Effective sequence | What actually triggers continued execution | Settings guaranteed before continuation |
| --- | --- | --- | --- |
| no bound thread | fail closed | none | n/a |
| goals disabled | fail closed | none | n/a |
| bound thread, no goal | fail closed | none | n/a |
| loaded, goal paused | `thread/settings/update -> thread/goal/set(active)` | the final `set(active)` | none beyond already-loaded backend state; sync is queued |
| loaded, goal active | `thread/settings/update` | no new trigger; backend keeps current state | none beyond already-loaded backend state; sync is queued |
| unloaded, goal paused | `thread/resume(cold overrides) -> [bind if requested] -> thread/settings/update -> thread/goal/set(active)` | the final `set(active)` | cold overrides only |
| unloaded, goal active | `thread/goal/set(paused) -> thread/resume(cold overrides) -> [bind if requested] -> thread/settings/update -> thread/goal/set(active)` | the final `set(active)` | cold overrides only |

Current rollback scope is intentionally narrow:

- if a pause-first resume path fails after pausing the goal, the wrapper tries
  to restore `goal=active`
- it does not roll back an already materialized `thread/resume`
- it does not retract an already queued `thread/settings/update`
- it does not clear an already rebound Feishu binding

### 6.5 Attach vs loaded

`binding attached` and `backend loaded` are still separate state axes.

They are related, but not identical:

- `attached`
  - says the Feishu binding should receive live thread events when the service
    has a live subscription path
- `loaded`
  - says the thread currently has runtime residency inside the app-server

So the formal model is still orthogonal, not "attached implies loaded forever".

Why an `attached + unloaded` pre-state can still appear:

- upstream may unload or close the backend thread independently of the local
  bookmark
- the wrapper intentionally keeps the logical binding bookmark instead of
  clearing the chat's current thread
- `thread/closed` settles execution state, but it does not erase the binding
  bookmark or forcibly clear the attached/detached user intent

That said, the explicit `attach` operation in the current implementation is a
composite operation, not a pure flag flip:

- control-plane attach uses `thread/resume`
- then it re-binds the Feishu chat to that live thread

So:

- after a successful explicit `attach`, the thread is expected to be loaded at
  that moment
- but `attached` still does not mean the backend can never become unloaded
  later

## 7. Provenance and Symmetric Risk

Expose provenance metadata as informational UI only:

- `source`
- `service_name` when available

Use cases:

- help users understand where a thread came from
- make shared vs external threads easier to reason about

Do not use provenance alone as an automatic safety decision.

The risk is symmetric:

- if Feishu resumes an external thread into its own backend, divergence is
  possible
- if a user later resumes a Feishu-active thread through bare `codex` on
  another backend, the same risk exists

`feishu-codex` cannot eliminate that risk. This repository chooses a more direct
`/resume` path, so the safety boundary relies on one operational rule: if
multiple clients should continue the same live thread, keep them on the shared
backend via `fcodex`, and do not mix in bare `codex`.

## 8. Feishu Multi-Chat Boundary

Safety and UX are different concerns.

### 8.1 Safety

All Feishu chats in one instance already share one backend
process, so they do not create separate app-server processes per chat.

Therefore, they do not suffer from the same cross-process dual-live-thread
divergence that exists between Feishu and bare TUI.

### 8.2 Current UX / ownership decision

The current model is no longer the older "one primary notification binding per
`thread_id`" model.

The more accurate description now is:

- one `thread_id` may have multiple Feishu subscribers / bindings at the same
  time
- those subscribers share one backend thread, so this remains backend-safe
- execution-driving and interaction-driving routing still follows explicit
  owner / lease state, not "who bound last"

Concretely:

- Same-instance Feishu / `fcodex` write admission, approvals, user-input requests, and interrupts are controlled by the `interaction owner`
- when a thread has no explicit owner but exactly one Feishu subscriber, the
  runtime may fall back to that sole subscriber for routing; once multiple
  subscribers exist, routing must depend on explicit owner state rather than
  any "last binding wins" guess

The user-visible consequence is:

- non-owner Feishu chats may still keep their binding and observe shared thread facts
- subscribed Feishu chats receive ordinary execution streams, terminal execution cards, and terminal result carriers
- non-owner chats may not write or handle the current turn's approvals / input / interrupt requests
- the system still does not promise a fully mirrored interactive live UI across multiple Feishu chats; approval cards and request-driving interactive events route only to the current `interaction owner`

So the decision at this layer is:

- Feishu allows multiple subscribers on one backend thread
- writability and interactivity are decided by the owner lease
- ordinary replies and terminal output broadcast by subscriber; interactive requests route by owner

## 9. Related Documents

- `docs/contracts/thread-profile-semantics.md`: exact command semantics for `/threads`,
  `/resume`, `fcodex`, and profile handling
- `docs/architecture/fcodex-shared-backend-runtime.md`: shared backend, dynamic port
  discovery, cwd proxy, and wrapper runtime behavior
- `docs/architecture/feishu-codex-design.md`: architecture, design constraints, and current
  repository structure
