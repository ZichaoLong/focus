# Local Commands and Runtime-Settings Contract

Chinese original: `docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`

This file keeps its historical filename, but it no longer defines any
project-owned profile surface. It defines the boundary between local entry
points and the remaining settings model.

## 1. Four local entry points

### 1.1 `focus`

Responsible for:

- entering the local Codex TUI
- resuming or attaching to a live thread
- acting as a local frontend against the instance shared backend

It is not:

- a service-management CLI
- a project-owned settings surface

### 1.2 `fcodex`

`fcodex` is an equivalent alias for `focus`, kept for the direct "Codex TUI
thin wrapper" meaning.

Responsible for:

- the same local Codex TUI wrapper behavior as `focus`
- a stable entry for operators who prefer a Codex-specific command name

It is not:

- another agent CLI
- a separate runtime or state surface from `focus`

### 1.3 `focusctl`

Responsible for:

- local repair after installation and upgrades
- service lifecycle
- instance management
- inspecting instance / binding / thread / service state
- performing limited local admin actions
- diagnosing attach / detach / backend problems

It is not:

- a second frontend for turn settings
- a local mirror of Feishu setting cards
- a Codex TUI

### 1.4 `focusd`

Responsible for:

- the background daemon entry called by the platform service manager

It is not:

- a daily manual management command
- a local Codex TUI wrapper

## 2. Only one project-owned writable setting family remains

### 2.1 Binding-wise next-turn settings

- scope: Feishu binding
- Feishu entries: `/model`, `/effort`, `/approval`, `/permissions`
- local `focus` / `fcodex` / upstream TUI keep their own local state; they do not
  auto-merge with persisted Feishu binding settings

## 3. Removed project-owned settings

The project no longer supports:

- legacy project-owned profile commands
- `/memory`
- `focusctl thread memory`
- any project-owned thread-memory or provider restore semantics

If an operator wants upstream profile/provider behavior, they must use
upstream Codex config, upstream profile-v2 files, or upstream launch
parameters directly.

## 4. Current meaning of `focus` / `fcodex -p/--profile`

The project no longer treats `focus -p/--profile` or `fcodex -p/--profile` as
a persisted mutation entry.

Its role is now:

- an upstream / local-TUI launch parameter
- not a local mirror of any Feishu command
- not something this project persists as thread truth

## 5. What `focus resume` / `fcodex resume` still promises

`focus resume <thread_id|thread_name>` and
`fcodex resume <thread_id|thread_name>` now promise:

- thread identity resolution
- live-runtime-owner / loaded-gate fail-close behavior
- attaching to the correct instance backend

It no longer promises:

- restoring a project-owned profile slice
- restoring a project-owned memory/provider slice

## 6. One maintenance rule

If a new setting is introduced into this project, it must first be classified
as exactly one of:

1. binding-wise next-turn settings
2. read-only diagnostic view

Until that classification exists, the project must not add a new local command
surface for it.
