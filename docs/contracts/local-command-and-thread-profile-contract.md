# Local Commands and Runtime-Settings Contract

Chinese original: `docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`

This file keeps its historical name, but its focus is no longer "thread
profile." It now defines the boundary between local entry points and the
current settings model.

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

- a replacement for a Feishu `/memory` surface
- a second turn-settings frontend

### 1.3 `fcodex`

Responsible for:

- entering the local Codex TUI
- resuming or attaching to a live thread
- acting as a local frontend against the instance backend

It is not:

- a service-management CLI
- a local mirror of Feishu setting cards

## 2. Only two project-owned setting families remain

### 2.1 Instance startup baseline

- scope: instance
- Feishu entries: `/profile`, `/profile-clear`
- local meaning: mutate the startup baseline of the instance backend

### 2.2 Binding-wise next-turn settings

- scope: Feishu binding
- Feishu entries: `/model`, `/effort`, `/approval`, `/permissions`, `/collab-mode`
- local `fcodex` / upstream TUI keep their own local state; they do not auto-merge
  with persisted Feishu binding settings

## 3. Removed local thread-memory contract

The project no longer supports:

- `feishu-codexctl thread memory`
- any project-owned thread-memory restore semantics
- `fcodex resume <thread>` consuming an extra project-owned persisted memory
  setting

If an operator wants to switch memory/provider behavior, they must use:

- the instance startup profile
- upstream config / profile-v2

## 4. Current meaning of `fcodex -p/--profile`

The project no longer treats `fcodex -p/--profile` as a thread-wise persisted
mutation entry.

Its role is now:

- an upstream / local-TUI parameter
- not a local mirror of Feishu `/profile`
- not something this project persists as thread truth

## 5. What `fcodex resume` still promises

`fcodex resume <thread_id|thread_name>` now promises:

- thread identity resolution
- live-runtime-owner / loaded-gate fail-close behavior
- attaching to the correct instance backend

It no longer promises:

- restoring a project-owned thread memory/provider slice

## 6. One maintenance rule

If a new setting is introduced into this project, it must first be classified
as exactly one of:

1. instance startup baseline
2. binding-wise next-turn settings
3. read-only diagnostic view

Until that classification exists, the project must not add a new local command
surface for it.
