# Runtime Settings Fact Sources and Effectivity Boundaries

Chinese original: `docs/contracts/runtime-settings-fact-sources.zh-CN.md`

This document defines the shared rule for answering: after a setting is
written, which layer is the authoritative fact source?

## 1. Only one writable setting family remains

### 1.1 Binding-wise next-turn settings

Current formal members:

- model
- effort
- approval
- permissions
- collaboration mode

Their properties:

- scoped to the current Feishu binding
- persisted in binding runtime settings
- primarily consumed at `turn/start`
- on unloaded-thread recovery, cold `thread/resume` may carry a narrow one-shot
  subset so the first post-resume autonomous turn does not fall back to stale
  loaded-thread defaults

## 2. The project no longer owns any thread-wise next-load setting

The following surfaces are removed from the project contract:

- legacy project-owned profile commands
- `/memory`
- `feishu-codexctl thread memory`
- `new_thread_memory_mode_seed`
- any project-owned thread-level memory/provider/profile restore state

As a result, the project no longer maintains a persisted fact source for
"extra config that this project injects on the next resume of a thread."

## 3. Read-only fact family: live runtime / upstream snapshot

Some values are still read, but they are not project-owned persisted settings:

- live loaded-backend state
- upstream thread snapshot
- runtime views returned by upstream `config/read`

Those values may be shown in:

- `/status`
- diagnostics
- admin cards

But they must not be treated as:

- a writable project setting layer
- the persisted fact source behind a removed legacy profile command

## 4. Writable-setting table

| Setting family | Persisted source | Official application boundary | Primary read-side |
| --- | --- | --- | --- |
| binding-wise next-turn | persisted runtime settings of the current binding | `turn/start`; cold `thread/resume` may carry a narrow one-shot subset for unloaded-thread recovery | `/status`, setting cards, preflight |

## 5. Decision rule for binding-wise next-turn

If the question is:

- "what model / effort / permissions will the next turn from this Feishu chat use?"

look first at:

- the persisted runtime settings of the current binding

Within that family:

- `auto` still means "do not explicitly override"
- it no longer maps to any project-owned thread-level persisted state

## 6. One maintenance rule

If a new setting is added later, it must first be classified as exactly one of:

1. binding-wise next-turn settings
2. read-only diagnostic view

Until that classification exists, the setting must not become a new command
surface or persisted project state layer.
