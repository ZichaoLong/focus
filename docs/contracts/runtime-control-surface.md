# Runtime Control Surface Contract

Chinese original: `docs/contracts/runtime-control-surface.zh-CN.md`

This document defines the formal semantics of the Feishu-side control surface.

## 1. Only two setting families remain

### 1.1 Instance startup baseline

Entry points:

- `/profile`
- `/profile-clear`

Semantics:

- manage the startup baseline of the current instance's managed backend
- do not directly mutate the current thread
- take effect only when the backend starts or restarts after reset

### 1.2 Binding-wise next-turn settings

Entry points:

- `/model`
- `/effort`
- `/approval`
- `/permissions`
- `/collab-mode`

Semantics:

- manage overrides for future turns of the current Feishu binding
- are primarily consumed at `turn/start`
- do not write any project-owned thread-level persisted state

## 2. Removed setting surface

The following entry points are no longer part of the formal contract:

- `/memory`
- any thread-wise memory control surface

If an operator wants to change process-level upstream capabilities such as
memory/provider selection, they must do it through:

- the instance startup profile
- upstream `~/.codex/config.toml`
- profile-v2

not through a project-owned thread-level setting.

## 3. Other core state axes

Independent from settings, the control surface still separates three state
axes:

1. `binding`
   - which thread the current chat logically points to
2. `attach / detach`
   - whether the current chat receives Feishu push for that thread
3. `backend / live runtime`
   - whether the thread is loaded in the backend, and who currently owns live
     runtime

Those axes are parallel to settings and must not be conflated with them.

## 4. Formal semantics of `/profile`

`/profile` still appears under the "thread settings" workbench area, but its
true scope is:

- the current instance

Therefore:

- `/profile <name>` changes the instance startup profile
- `/profile-clear` clears the instance startup-profile override
- if the operator wants the change immediately, they must reset the backend

## 5. Formal semantics of turn-time settings

`/model`, `/effort`, `/approval`, `/permissions`, and `/collab-mode`:

- belong to the current binding's next-turn settings
- read back persisted binding intent by default
- are not the instance baseline
- are not thread-level persisted truth

Within that family:

- `auto` means "do not explicitly override"
- it no longer maps to any project-owned thread-level fallback state

## 6. Side-effect boundary of reset-backend

When an instance resets its backend:

- the backend process restarts
- binding bookmarks stay
- related Feishu push paths detach first
- the startup profile stays
- binding-wise next-turn settings stay

Reset-backend does not:

- rewrite thread history
- automatically re-attach every chat
- upgrade binding settings into thread-level settings

## 7. What `/status` should show

`/status` and related diagnostics should show separately:

- the instance startup profile
- the current binding's next-turn overrides
- attach/detach and live-runtime state

They should no longer present:

- a thread-wise memory setting
- "extra memory config that this project will inject on the next resume"
