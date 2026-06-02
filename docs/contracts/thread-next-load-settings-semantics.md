# Thread Next-Load Settings Semantics

Chinese original: `docs/contracts/thread-next-load-settings-semantics.zh-CN.md`

This file is retained as a retirement note under its historical name.

## 1. Current conclusion

The project no longer keeps any project-owned thread-wise next-load setting.

That means the formal contract no longer includes:

- any thread memory setting
- any thread provider setting
- any thread profile setting
- `new_thread_memory_mode_seed`
- any thread-level setting layer that is first persisted by this project and
  later injected again on resume

## 2. What remains instead

### 2.1 Binding-wise next-turn settings

Managed through:

- `/model`
- `/effort`
- `/approval`
- `/permissions`
- `/collab-mode`

Their semantics:

- apply to future turns of the current Feishu binding
- are primarily consumed at `turn/start`
- are not thread-level persisted restore settings

### 2.2 Upstream-owned process and thread state

If an operator wants upstream profile/provider or memory behavior, they must
use upstream Codex config, upstream profile-v2 files, or upstream launch
parameters directly.

This project does not mirror those choices into a project-owned next-load
layer.

## 3. Current `resume` contract

Project-supported resume paths now promise only:

- thread identity resolution and safety admission
- resuming against the correct instance backend
- preserving the frontend's own runtime semantics

They do not promise:

- restoring an extra project-owned profile/memory/provider slice for a thread

## 4. Why this file still exists

The concept of "thread-wise next-load settings" is still useful because it
prevents maintainers from conflating:

- binding overrides
- live-runtime diagnostics
- upstream-owned process state

But in the current version, the number of formal members in that category is:

- `0`

## 5. Future maintenance rule

If a thread-wise next-load setting is ever reintroduced, the project must first
document:

1. the post-write persisted source
2. the official application boundary
3. how it differs from binding overrides and upstream-owned process state

Until that exists, the command surface must not reintroduce it.
