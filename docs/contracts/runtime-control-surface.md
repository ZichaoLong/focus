# Runtime Control Surface Contract

Chinese original: `docs/contracts/runtime-control-surface.zh-CN.md`

This document defines the formal semantics of the Feishu-side control surface.

## 1. Only one writable setting family remains

### 1.1 Binding-wise next-turn settings

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

## 2. Removed setting surfaces

The following entry points are no longer part of the formal project contract:

- legacy project-owned profile commands
- `/memory`
- any thread-wise memory control surface

If an operator wants to change process-level upstream capabilities such as
profile/provider or memory behavior, they must do it through upstream Codex
itself rather than a project-owned Feishu setting surface.

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

## 4. Formal semantics of turn-time settings

`/model`, `/effort`, `/approval`, `/permissions`, and `/collab-mode`:

- belong to the current binding's next-turn settings
- read back persisted binding intent by default
- are not the instance baseline
- are not thread-level persisted truth

Within that family:

- `auto` means "do not explicitly override"
- it no longer maps to any project-owned thread-level fallback state

## 5. Side-effect boundary of reset-backend

When an instance resets its backend:

- the backend process restarts
- binding bookmarks stay
- related Feishu push paths detach first
- binding-wise next-turn settings stay

Reset-backend does not:

- rewrite thread history
- automatically re-attach every chat
- upgrade binding settings into thread-level settings

## 6. What `/status` should show

`/status` and related diagnostics should show separately:

- the current binding's next-turn overrides
- attach/detach state
- live-runtime / loaded state

They should no longer present:

- a project-owned profile setting
- a thread-wise memory setting
- "extra config that this project will inject on the next resume"
