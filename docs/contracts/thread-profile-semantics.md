# Thread and Resume Semantics

Chinese original: `docs/contracts/thread-profile-semantics.zh-CN.md`

This file keeps its historical filename, but it no longer defines any
project-owned "profile" feature. It now records the semantics of `/threads`,
`/resume`, `/archive`, and local shared-backend continuation.

## 1. Current scope

This document defines:

- how Feishu-side thread browsing works
- what `/resume` promises
- what `/archive` changes
- what local `focus resume` / `fcodex resume` means in the shared-backend model

It does not define:

- any project-owned profile setting
- any project-owned thread-wise next-load setting
- any local mirror of upstream `codex --profile`

## 2. Thread identity and ownership

The project keeps three distinct concepts:

1. thread identity
   - comes from upstream Codex thread metadata
2. Feishu binding
   - decides which thread the current chat points to
3. live runtime ownership
   - decides which backend currently hosts the loaded thread

Those concepts must not be conflated.

## 3. `/threads`

`/threads` is a browse surface for the current working directory.

It:

- lists candidate threads for the current directory context
- helps the operator choose a thread to resume or archive
- does not mutate runtime settings by itself

## 4. `/resume`

`/resume <thread_id|thread_name>` now promises only:

- resolving the intended thread
- applying cross-instance safety admission before live reuse
- resuming against the correct backend
- binding the current Feishu chat to that thread

It no longer promises:

- replaying a project-owned profile slice
- replaying a project-owned memory/provider slice
- reconstructing any extra thread-level setting layer owned by this project

If the target thread is already loaded in the current backend, resume reuses
that live runtime directly. If it is not loaded, the implementation resumes it
through upstream `thread/resume` after passing the repository's safety gates.

## 5. `/archive`

`/archive [thread_id|thread_name]` archives the current thread or an explicit
target thread.

It:

- changes thread archival state in Codex
- may clear or update the current binding when the current thread is archived

It does not:

- change runtime-setting families
- imply any profile or memory behavior

## 6. Local `focus` / `fcodex` continuation

`focus resume <thread_id|thread_name>` and
`fcodex resume <thread_id|thread_name>` are the local continuation entry
points for a live shared-backend thread.

They promise:

- the same thread identity resolution model
- the same cross-instance loaded/runtime safety checks
- attaching local TUI continuation to the correct backend

`focus -p/--profile` and `fcodex -p/--profile` still exist only as upstream
Codex launch parameters. This project does not persist them, reflect them into
Feishu, or treat them as thread truth.

## 7. Non-goals

The project no longer promises:

- "Feishu `/resume` replays an old thread profile"
- "Feishu and `focus` / `fcodex` share a project-owned profile fact source"
- "unloaded threads still carry a project-owned next-load profile layer"

The current contract is intentionally narrower:

- thread identity is upstream-owned
- resume safety is repository-owned
- turn-time overrides remain binding-owned
