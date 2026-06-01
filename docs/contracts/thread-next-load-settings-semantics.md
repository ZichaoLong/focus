# Thread Next-Load Settings Semantics

Chinese original: `docs/contracts/thread-next-load-settings-semantics.zh-CN.md`

This document defines the **thread-wise, persisted settings that take effect on
next-load** and are still formally kept by this project.

## 1. Current scope

The current thread-wise next-load state has only one slice:

- **memory slice**
  - `memory mode`

This means the current contract no longer includes:

- profile
- model
- model provider
- effort
- approval
- permissions
- collaboration mode

Those settings belong to other layers:

- startup profile: `docs/contracts/thread-profile-semantics.md`
- binding-wise next-turn settings:
  `docs/contracts/runtime-control-surface.md`

## 2. Basic facts

- memory mode is **thread-wise**, not binding-wise
- for an unloaded thread, the persisted memory mode is the truth
- for a loaded thread, the live runtime becomes the truth
- writing thread-wise memory mode does not mean the current live runtime has
  already changed

Supported restore paths mainly include:

- Feishu-side restore / wake-up of the current thread
- local `fcodex resume <thread>`

## 3. Post-write persisted source

For a normal thread:

- the formal persisted source is `ThreadMemoryModeStore`

During a provisional stage:

- if a thread has just been created and is not yet stably materialized, the
  system may hold a pending seed first
- after the corresponding successful `turn/completed`, that pending seed is
  promoted into a formal thread-wise record

## 4. Application boundaries

Memory mode is actually consumed at:

- `thread/resume`
  - restore an existing thread using its persisted memory mode
- `thread/start`
  - only for the "new thread startup seed" path

So its semantics are:

- **next-load**
- not turn-time override

## 5. New-thread seed

An instance may configure `new_thread_memory_mode_seed`.

That seed:

- affects only new threads
- does not rewrite other existing threads' persisted memory mode
- is recorded again into that new thread's formal or pending memory state after
  creation succeeds

## 6. Direct write and reset-backend

`/memory` follows the shared thread-wise mutation rule:

1. if the target thread is verifiably globally unloaded
   - direct write is allowed
2. if the current instance can converge through reset-backend
   - offer "apply and reset backend"
3. otherwise
   - fail closed

This mutability check now belongs only to thread-wise memory. It no longer
piggybacks any profile contract.

## 7. Read-side view

`/memory`, status pages, and local thread diagnostics should primarily show:

- the thread's persisted memory mode

They may additionally show:

- the memory configuration observed when the current live runtime was loaded
- the instance's `new_thread_memory_mode_seed`

But they must distinguish:

- "what the next load will use"
- "what the currently loaded runtime is using"

## 8. Non-goals

This document no longer promises:

- any thread-wise profile slice
- `fcodex -p/--profile` rewriting a thread's persisted restore settings
- turn-time settings such as effort or model being synchronized through
  thread-wise state
