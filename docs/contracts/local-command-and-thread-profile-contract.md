# Local Commands and Runtime-Settings Contract

Chinese original: `docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`

This file keeps its historical filename, but it no longer defines any
project-owned profile surface. It defines the boundary between local entry
points and the remaining settings model.

## 1. Three local entry points

### 1.1 `feishu-codex`

Responsible for:

- installation and upgrades
- service lifecycle
- instance management
- project-level helper actions

### 1.2 `feishu-codexctl`

Responsible for:

- inspecting instance / binding / thread / service state
- performing limited local admin actions
- diagnosing attach / detach / backend problems

It is not:

- a second frontend for turn settings
- a local mirror of Feishu setting cards

### 1.3 `fcodex`

Responsible for:

- entering the local Codex TUI
- resuming or attaching to a live thread
- acting as a local frontend against the instance backend

It is not:

- a service-management CLI
- a project-owned settings surface

## 2. Only one project-owned writable setting family remains

### 2.1 Binding-wise next-turn settings

- scope: Feishu binding
- Feishu entries: `/model`, `/effort`, `/approval`, `/permissions`
- local `fcodex` / upstream TUI keep their own local state; they do not
  auto-merge with persisted Feishu binding settings

## 3. Removed project-owned settings

The project no longer supports:

- legacy project-owned profile commands
- `/memory`
- `feishu-codexctl thread memory`
- any project-owned thread-memory or provider restore semantics

If an operator wants upstream profile/provider behavior, they must use
upstream Codex config, upstream profile-v2 files, or upstream launch
parameters directly.

## 4. Current meaning of `fcodex -p/--profile`

The project no longer treats `fcodex -p/--profile` as a persisted mutation
entry.

Its role is now:

- an upstream / local-TUI launch parameter
- not a local mirror of any Feishu command
- not something this project persists as thread truth

## 5. What `fcodex resume` still promises

`fcodex resume <thread_id|thread_name>` now promises:

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
