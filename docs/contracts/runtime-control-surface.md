# Runtime Control Surface Contract

Chinese original: `docs/contracts/runtime-control-surface.zh-CN.md`

This document is the user-facing contract for the Feishu-side runtime control
surface.

## 1. The control surface separates only three setting families

### 1.1 Instance startup profile

Entry points:

- `/profile`
- `/profile-clear`

Semantics:

- manage the startup baseline of the current instance's managed backend
- do not directly mutate the current thread
- take effect only on the next backend start / reset

### 1.2 Thread-wise next-load memory

Entry point:

- `/memory`

Semantics:

- manage the current thread's memory mode
- take effect on the next `thread/resume` or the corresponding startup-seed path
- are not turn-time overrides

### 1.3 Binding-wise next-turn settings

Entry points:

- `/model`
- `/effort`
- `/approval`
- `/permissions`
- `/collab-mode`

Semantics:

- manage runtime overrides for future turns of the current Feishu binding
- are primarily consumed at `turn/start`
- do not write thread-wise next-load state

## 2. Other core state axes

Besides settings, the control surface continues to separate three orthogonal
state axes:

1. `binding`
   - which thread the current chat logically points to
2. `attach / detach`
   - whether the current chat receives Feishu push for that thread
3. `backend / live runtime`
   - whether the thread is loaded in the backend, and who currently owns live
     runtime

Those state axes must not be conflated with the setting families.

## 3. Formal semantics of `/profile`

`/profile` still appears under the "thread settings" workbench area, but its
true scope is:

- **the current instance**

That placement is a workflow choice only: operators often adjust backend
baseline while working on the current thread.

Therefore:

- `/profile <name>` changes the instance startup profile
- `/profile-clear` clears the instance startup-profile override
- if the operator wants the current instance to switch immediately, they must
  reset the backend

## 4. Formal semantics of `/memory`

`/memory` is the only formally retained thread-wise next-load setting entry
point.

It has three outcomes:

1. direct write
   - the target thread is verifiably globally unloaded
2. offer "apply and reset backend"
   - the current instance can converge through reset-backend
3. fail closed
   - the current state is not safe to mutate

## 5. Formal semantics of turn-time settings

`/model`, `/effort`, `/approval`, `/permissions`, and `/collab-mode`:

- all belong to the current Feishu binding's next-turn settings
- primarily read back persisted binding intent
- are not thread snapshot truth
- are not instance startup baseline

Within that family:

- `auto` means "do not explicitly override"
- it does not mean "clear some thread-wise state to default"

## 6. Side-effect boundary of reset-backend

When an instance resets its backend:

- the backend process restarts
- binding bookmarks stay
- related Feishu push paths detach first
- thread-wise memory store stays
- startup profile stays
- binding-wise next-turn settings stay

Reset-backend does not:

- rewrite thread history
- automatically re-attach every chat
- upgrade binding settings into thread-wise state

## 7. What status pages should read

`/status` and related diagnostics should show separately:

- the instance startup profile
- the current thread's persisted memory mode
- the current binding's next-turn overrides

They should no longer present:

- "current thread-wise profile"
- "re-profile possible"

because those are no longer part of the formal contract.
