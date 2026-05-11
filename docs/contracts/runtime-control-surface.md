# Runtime Control Surface Contract

Chinese original: `docs/contracts/runtime-control-surface.zh-CN.md`

This file is the authoritative contract for the current runtime vocabulary and control actions.

## 1. Three-layer mental model

The product now exposes only three user-facing layers:

1. `binding`
   - which thread a Feishu chat currently remembers
2. `attach / detach`
   - whether that Feishu chat currently receives push for that thread
3. `backend / live runtime`
   - whether that thread is loaded in the backend, and which instance / local frontend currently owns live runtime

Upstream `thread/unsubscribe` still exists, but only as an internal protocol action. It is no longer a user-facing concept.

## 2. Core vocabulary

### 2.1 `binding`

One Feishu chat's logical pointer to a thread.

- `unbound`
- `bound`

It answers:

- “Which thread will this chat continue by default on the next message?”

It does not answer:

- whether push is still attached
- whether the backend is loaded

### 2.2 `feishu push`

Whether the current Feishu chat receives push for the thread.

- `attached`
- `detached`
- `not-applicable`

It answers:

- “Will this Feishu chat currently receive push for this thread?”

### 2.3 `backend thread status`

The current backend state of the thread in this instance.

Typical values:

- `notLoaded`
- `idle`
- `active`
- `systemError`

This is a separate axis from Feishu attachment state.

### 2.4 `live runtime owner`

The machine-global owner of the live thread runtime.

It may be:

- one `feishu-codex` service instance
- one local `fcodex` / proxy holder
- none

It answers:

- “Which instance or local frontend is actually holding this live thread now?”

It is not the only safety fact for cross-instance attach / resume.

- before cross-instance continuation, the system must first verify that no other running instance still keeps the thread `loaded`
- only after that loaded gate passes may the current instance continue to claim `ThreadRuntimeLease`

### 2.5 `interaction owner`

Who currently owns write / interrupt / approval / extra-input control for the thread.

It is not identical to `live runtime owner`:

- `live runtime owner` is about holding live runtime
- `interaction owner` is about owning the current turn's interaction control

### 2.6 binding-wise turn-time settings

The Feishu side also has a class of settings that do not belong to
thread-wise next-load state and do not form the permanent snapshot truth of a
loaded thread.

They are:

- **binding-wise turn-time settings**

The currently explicit user-facing entries include:

- `/approval`
- `/sandbox`
- `/permissions`
- `/collab-mode`

Their contract is:

- the setting value is persisted on the current Feishu binding
- the current binding injects it when creating a thread or starting `turn/start`
- if changed before the turn starts, it can affect that turn immediately
- if the current turn is already running, it affects the next turn instead

They are not:

- thread-wise next-load state
- one shared thread-level truth across all frontends
- a live-runtime snapshot that can always be re-read stably for a loaded thread

Therefore:

- one Feishu chat's stored settings do not automatically become the defaults of
  another Feishu chat or local `fcodex`
- another frontend may inject different runtime overrides on its own turns
- `fcodex` does not automatically participate in this Feishu binding-wise
  persistence model

## 3. Hard rules

### 3.1 First attach / last detach

For the Feishu service itself:

- when the first binding on a thread goes from detached to attached, the service must ensure it is subscribed to that thread
- when the last attached Feishu binding on a thread becomes detached, the service must automatically stop its own Feishu-side subscription for that thread
- a local `attached` flag is not enough by itself; the service must only mark `attached` after its own backend connection has re-established the real thread subscription fact

This constrains the Feishu service only.

It does not constrain local `fcodex`:

- local `fcodex` may still subscribe independently
- so the backend may stay loaded after the last Feishu detach

### 3.2 Restart recovery

A persisted `attached` value is not a durable truth across processes.

So after restart or a fresh service connection:

- persisted `attached` must be downgraded to `detached`
- the binding bookmark stays
- later `/attach`, `/resume`, or the next accepted plain message may attach again

### 3.3 Pure reject for detached prompts

If the current binding is `bound + detached`, and the next plain message is denied by live-runtime / interaction / sharing rules:

- it must be a pure reject
- it must not resume behind the scenes
- it must not add a Feishu subscriber behind the scenes
- it must not flip `detached` back to `attached`

## 4. Important state combinations

### 4.1 `bound + attached + idle`

Valid steady state.

Meaning:

- the chat still remembers the thread
- the chat still receives push
- no turn is currently running in the backend

### 4.2 `bound + detached + notLoaded`

The most typical “thread-wise profile is directly writable” state.

Meaning:

- the binding bookmark still exists
- Feishu is not receiving push
- this instance has confirmed the thread is not loaded

### 4.3 `bound + detached + idle/active`

Also valid.

Meaning:

- Feishu has detached
- but another subscriber still keeps the backend loaded
- the common case is local `fcodex`

So:

- `detached` does not imply `notLoaded`

## 5. Command contracts

### 5.1 `/status`

`/status` is a chat-scoped summary command.

It shows only:

- current directory
- current thread
- the current thread's thread-wise profile
- the current Feishu session's permissions / approval / sandbox / collaboration settings

It is no longer the full debugging surface.

### 5.2 `/preflight`

`/preflight` is a chat-scoped dry-run.

It may answer:

- whether the next plain message would be accepted or blocked
- whether `/detach` is currently available for the current chat

It must not:

- start a turn
- call resume
- change binding / attached / detached / owner state

### 5.3 `/detach`

`/detach` applies only to the current chat binding.

It:

- keeps the binding bookmark
- flips the current chat from `attached` to `detached`
- if that chat was the last attached Feishu binding on the thread, automatically stops the Feishu service's own subscription for that thread

It does not:

- delete the thread
- clear the binding
- force the backend to unload

### 5.4 `/attach [binding|thread|service]`

This is the recovery action.

Scopes:

- `binding`
  - restore only the current chat binding
- `thread`
  - restore all detached bindings on the current chat's thread
- `service`
  - restore all recoverable detached bindings in the current instance

All attach actions must fail closed when:

- another running instance still reports the thread as `loaded`
- the system cannot verify whether other running instances are fully `unloaded`
- the loaded gate passes but live-runtime lease claim still denies them
- the target thread is no longer attachable
- the current instance cannot safely acquire the needed runtime

`service attach` must also satisfy:

- instance-level batch restore
- thread-level fail-close
- partial success across different threads is allowed

Attach is not a read-only inspection.

- if the thread is already loaded, attach must still re-establish the service connection's backend-side thread subscription
- it must not flip local state to `attached` based only on a successful `thread/read`

### 5.5 `/reset-backend`

`/reset-backend` is an instance-scoped action.

It:

- resets the current instance backend
- preserves binding bookmarks
- preserves thread-wise profile/provider data
- preserves user config and data
- moves affected Feishu bindings into `detached`

It does not:

- automatically delete bindings
- automatically clear thread-wise profile
- automatically guarantee that push becomes attached again

So the result card must directly offer:

- `Attach Current Thread`
- `Attach Current Instance`
- `Keep Detached`

Before the reset actually runs, preview / denial wording should split facts into
two layers:

- `hard blockers`
  - for example active threads, pending approval/input requests, and running
    Feishu bindings
- `collateral impact`
  - for example attached bindings, live runtime holders, and the count / short
    summary of loaded threads on the current instance that would also be
    affected

Do not dump every loaded thread into the primary card by default.

## 6. Local management surface

The formal local `feishu-codexctl` command matrix lives in
`docs/contracts/feishu-codexctl-command-matrix.md`.

This document no longer maintains a second command list; it only defines runtime
state and control semantics.

## 7. reset-backend and re-profile

The direct-write rule and reset path for thread-wise next-load settings
(currently profile / memory mode) live in
`docs/contracts/thread-next-load-settings-semantics.md`.

This document keeps only the runtime-control requirement:

- the Feishu-side `/profile <name>` / `/memory <...>` flows should prefer direct write when possible, otherwise “apply and reset backend”
- it should not force ordinary users to understand complex detach / attach / unsubscribe relationships first

## 8. Bottom line

The user-facing contract must stay:

- `binding` answers “which thread is remembered”
- `attach / detach` answers “whether this chat receives push”
- `backend / live runtime` answers “where the thread is loaded and who currently holds it”

Any code, CLI wording, help card, result card, README, or contract doc that still collapses these layers into a single “release runtime residency” concept should be treated as a contract bug and tightened further.
