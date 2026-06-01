# Thread Next-Load Settings Semantics

Chinese original: `docs/contracts/thread-next-load-settings-semantics.zh-CN.md`

This file is retained as a retirement note under its historical name.

## 1. Current conclusion

The project no longer keeps any project-owned thread-wise next-load setting.

That means the formal contract no longer includes:

- any thread memory setting
- any thread provider setting
- `new_thread_memory_mode_seed`
- any thread-level setting layer that is first persisted by this project and
  later injected again on resume

## 2. What replaced it

### 2.1 Instance startup baseline

Managed through `/profile` and `/profile-clear`.

Its semantics:

- applies to the next backend start of the instance
- is not thread truth

### 2.2 Binding-wise next-turn settings

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

## 3. Current `resume` contract

Project-supported resume paths now promise only:

- thread identity resolution and safety admission
- resuming against the correct instance backend
- preserving instance-level startup baseline and the frontend's own runtime
  semantics

They do not promise:

- restoring an extra project-owned memory/provider slice for a thread

## 4. Why this file still exists

The concept of "thread-wise next-load settings" is still useful because it
prevents maintainers from conflating:

- instance baseline
- binding overrides
- live-runtime diagnostics

But in the current version, the number of formal members in that category is:

- `0`

## 5. Future maintenance rule

If a thread-wise next-load setting is ever reintroduced, the project must first
document:

1. the post-write persisted source
2. the official application boundary
3. how it differs from instance baseline and binding overrides

Until that exists, the command surface must not reintroduce it.
