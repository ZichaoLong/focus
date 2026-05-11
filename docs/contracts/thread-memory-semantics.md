# Thread Memory Mode Semantics

Chinese original: `docs/contracts/thread-memory-semantics.zh-CN.md`

This file defines only the memory-mode-specific semantics and entry contract.
The shared next-load effect and direct-write / reset-backend rules live in
`docs/contracts/thread-next-load-settings-semantics.md`.

## 1. Basic fact

- memory mode is **thread-wise**, not binding-wise
- for supported resume paths, the same thread should use the same persisted thread-wise memory mode when it moves from unloaded back to loaded
- the project exposes one unified concept, `memory mode`, instead of surfacing upstream's two boolean knobs directly to Feishu users

The formal values are:

- `off`
- `read`
- `read_write`

Their upstream mapping is fixed:

- `off`
  - `memories.use_memories = false`
  - `memories.generate_memories = false`
- `read`
  - `memories.use_memories = true`
  - `memories.generate_memories = false`
- `read_write`
  - `memories.use_memories = true`
  - `memories.generate_memories = true`

## 2. What it controls

Thread-wise memory mode controls:

- whether the thread reads memory after a future resume
- whether the thread may generate / write memory after a future resume

It does **not** mean:

- each thread has an isolated memory store
- different bindings may observe different memory modes
- that `/memory` hot-updates an already loaded backend thread

Upstream memory data still lives under the global `CODEX_HOME/memories`.
Different threads only differ in how they read / generate memory, not in owning separate storage.

## 3. Feishu-side `/memory [off|read|read_write]`

`/memory` is the formal memory-mode management entry point for the current thread.

It follows the shared next-load-setting rule, so it has three outcomes:

1. direct write
   - the shared direct-write condition is satisfied
2. offer “apply and reset backend”
   - the shared direct-write condition is not satisfied yet, but the current instance can converge through reset-backend
3. fail closed
   - live runtime is owned by another instance, or the current instance cannot safely reset

Both “direct write” and “write after reset” target only the **persisted thread-wise setting**.
They do not bypass the next-load contract to hot-patch an already loaded runtime in place.

## 4. State after reset-backend

When backend reset is triggered from `/memory`:

- binding bookmarks stay
- related Feishu bindings become `detached`
- the thread-wise memory mode is persisted immediately once the write succeeds
- continued Feishu push is not automatically guaranteed

The result card must offer:

- `Attach Current Thread`
- `Attach Current Instance`
- `Keep Detached`

## 5. Local behavior

The formal contract is:

- Feishu `/memory` remains the supported chat-side mutation entry
- local `feishu-codexctl thread memory` is the supported standalone local inspection / mutation entry
- `fcodex resume <thread>` automatically applies the persisted memory mode when resuming that thread
- `default_thread_memory_mode` in `codex.yaml` is a new-thread seed for project-supported new-thread creation paths
- `default_thread_memory_mode` is meaningful only if upstream Codex memory feature is already enabled outside this project

That means:

- once a thread has a persisted memory mode from Feishu or local control, local `fcodex` resume will carry it forward
- project-supported new-thread creation paths may seed an initial persisted memory mode immediately
- if the thread is still loaded, the new memory mode still follows the unload / reset-backend path rather than promising hot reload
- divergence caused by bare `codex` or other out-of-contract runtime/config mutations is not normalized by this project

## 6. Relationship to `/attach` and `/detach`

- `/detach`
  - only pauses Feishu push for a chat
  - does not imply the thread is globally unloaded
- `/attach`
  - only restores Feishu push
  - does not change thread-wise memory mode

So:

- memory-mode management and attach/detach are different state axes

## 7. Old mental models that are no longer valid

These statements are no longer accurate:

- “memory is a per-Feishu-session toggle”
- “detach is enough to change memory directly”
- “changing memory mode hot-updates every already loaded thread immediately”

The accurate contract is:

- memory mode is thread-wise
- next-load effect and direct-write rules are defined by the shared contract
