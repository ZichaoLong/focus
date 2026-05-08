# Thread Memory Mode Semantics

Chinese original: `docs/contracts/thread-memory-semantics.zh-CN.md`

This file defines only the contract for thread-wise memory mode behavior.

## 1. Basic fact

- memory mode is **thread-wise**, not binding-wise
- the same thread should observe the same thread-wise memory mode whether it is resumed from Feishu or `fcodex`
- the project exposes one unified concept, `memory mode`, instead of surfacing upstream's two boolean knobs directly to Feishu users

The formal values are:

- `off`
- `read`
- `read_write`

Their upstream mapping is fixed:

- `off`
  - `memories.use_memories = false`
  - `memories.generate_memories = false`
  - `thread/memoryMode/set = disabled`
- `read`
  - `memories.use_memories = true`
  - `memories.generate_memories = false`
  - `thread/memoryMode/set = disabled`
- `read_write`
  - `memories.use_memories = true`
  - `memories.generate_memories = true`
  - `thread/memoryMode/set = enabled`

## 2. What it controls

Thread-wise memory mode controls:

- whether the thread reads memory after a future resume
- whether the thread may generate / write memory after a future resume

It does **not** mean:

- each thread has an isolated memory store
- different bindings may observe different memory modes

Upstream memory data still lives under the global `CODEX_HOME/memories`.
Different threads only differ in how they read / generate memory, not in owning separate storage.

## 3. When direct mutation is allowed

A thread-wise memory mode may be written directly only when the thread is **verifiably globally unloaded**.

That requires at least:

- no attached Feishu binding on the thread
- no live runtime lease on the thread
- backend confirmation that the thread is not loaded

Therefore:

- detached alone is not enough
- closing one Feishu chat is not enough
- an open local `fcodex` session is usually not enough either

## 4. Feishu-side `/memory [off|read|read_write]`

`/memory` is the formal memory-mode management entry point for the current thread.

It has three outcomes:

1. direct write
   - the thread is already verifiably globally unloaded
2. offer “apply and reset backend”
   - the thread is not directly writable yet, but the current instance can converge through reset-backend
3. fail closed
   - live runtime is owned by another instance, or the current instance cannot safely reset

## 5. State after reset-backend

When backend reset is triggered from `/memory`:

- binding bookmarks stay
- related Feishu bindings become `detached`
- the thread-wise memory mode is persisted immediately once the write succeeds
- continued Feishu push is not automatically guaranteed

The result card must offer:

- `Attach Current Thread`
- `Attach Current Instance`
- `Keep Detached`

## 6. Local behavior

The local command surface does not currently expose a standalone thread-wise memory-mode mutator.

The formal contract is:

- Feishu `/memory` is the supported way to mutate thread-wise memory mode
- `fcodex resume <thread>` automatically applies the persisted memory mode when resuming that thread
- new threads do not have an “instance-level default memory mode” as a user-facing concept

That means:

- once a thread has a persisted memory mode from Feishu, local `fcodex` resume will carry it forward
- if the thread is still loaded, the new memory mode still follows the unload / reset-backend path rather than promising hot reload

## 7. Relationship to `/attach` and `/detach`

- `/detach`
  - only pauses Feishu push for a chat
  - does not imply the thread is globally unloaded
- `/attach`
  - only restores Feishu push
  - does not change thread-wise memory mode

So:

- memory-mode management and attach/detach are different state axes

## 8. Old mental models that are no longer valid

These statements are no longer accurate:

- “memory is a per-Feishu-session toggle”
- “detach is enough to change memory directly”
- “changing memory mode hot-updates every already loaded thread immediately”

The accurate contract is:

- memory mode is thread-wise
- writability depends on verifiable global unload
- if that condition is not met, the system should converge through reset-backend rather than forcing the user to reason about more low-level actions
