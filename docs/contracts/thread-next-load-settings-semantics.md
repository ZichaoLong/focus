# Thread Next-Load Settings Semantics

Chinese original: `docs/contracts/thread-next-load-settings-semantics.zh-CN.md`

This document defines a shared contract class: **thread-wise, persisted settings that take effect on next-load**.

They form one logical state for a thread:

- **thread-wise next-load state**

The current slices of that state are:

- **profile slice**
  - `profile`
  - `model`
  - `model_provider`
- **memory slice**
  - `memory mode`

Future thread-wise restore settings should reuse this document instead of copying another restore/mutation rule stack.

## 1. Basic fact

- these settings are **thread-wise**, not binding-wise
- for **supported resume paths**, the contract is: when the same thread moves from unloaded back to loaded, it should use the same persisted thread-wise next-load state
- that persisted next-load state is the truth for **unloaded** threads
- they are **not** the hot-update truth for an already loaded runtime
- the truth for a **loaded** thread is owned by its live runtime instead

“Supported resume paths” currently means mainly:

- Feishu-side restore / resume flows for the current thread
- local `fcodex resume <thread>`

This document does **not** promise:

- that the project will automatically normalize divergence caused by bare `codex` or other out-of-contract runtime/config mutations
- that an already loaded thread will hot-update immediately just because a persisted setting was changed

## 2. When it takes effect

These settings take effect when:

- the target thread is currently backend `notLoaded`
- and a supported resume path loads it again

More precisely:

- this is a **next-load** contract
- not an “edit the currently loaded runtime in place” contract

## 3. The observability boundary of a loaded snapshot

For a **loaded** thread, the only runtime observation this project can rely on
stably today is:

- the runtime fields returned by `thread/start` / `thread/resume`

That should be treated as a:

- **load-time observed snapshot**

It answers:

- “What runtime was observed when this thread finished this load / resume?”

It does not answer:

- “What is the full live config truth for this already loaded thread at any later arbitrary time?”

In particular, the following must not be treated as a full authoritative read of
loaded live runtime:

- `thread/read`
  - primarily thread metadata / history reading
- `config/read`
  - the current layered on-disk config

In this project's contract, the load-time observed snapshot is sufficient for:

- thread-wise next-load restore behavior on unloaded -> loaded paths
- showing and diagnosing what was observed at load time

But it does **not** promise:

- that the full live runtime of a loaded thread can always be re-read exactly at
  arbitrary later points

## 4. Which official paths can drift a loaded runtime away from that snapshot

Even while a thread remains loaded, upstream exposes official mutation surfaces
that can make later real behavior drift away from the load-time observed
snapshot.

At minimum, this includes:

- `turn/start` runtime overrides
  - for example `model`, `cwd`, `approvalPolicy`, `sandbox` / experimental `permissions`
- `config/batchWrite` with `reloadUserConfig: true`
  - hot-reloads loaded threads
- `config/mcpServer/reload`
  - queues MCP config refresh for each thread's next active turn

That means:

- different TUIs / frontends attached to the same loaded thread may still change
  its later turn behavior through official upstream paths
- this drift does not require manual snapshot edits or process-memory hacks

## 5. Slice mutation meaning

Each command only owns its own slice mutation:

- explicit profile mutation owns the **profile slice**
- explicit memory mutation owns the **memory slice**
- a plain resume with no explicit mutation request should not rewrite any slice

For profile specifically:

- a persisted profile slice is valid only when all three fields are present:
  `profile`, `model`, `model_provider`
- supported project paths must fail closed on an incomplete persisted profile
  slice; they must not silently refill missing fields from the current local
  config or backend defaults

For local `fcodex`:

- explicit `-p/--profile` means “actively rewrite the profile slice”
- no `-p/--profile` means “do not rewrite the profile slice; resume using the persisted slice”
- the setting-specific contract may further define how that target value is
  resolved; for profile in `feishu-codex`, it is intentionally thread-stable
  instead of cwd / project-dynamic

## 6. When direct mutation is allowed

These settings may be written directly only when the thread is **verifiably globally unloaded**.

That requires at least:

- no attached Feishu binding on the thread
- no live runtime lease on the thread
- backend confirmation that the thread is not loaded

Therefore:

- detached alone is not enough
- closing one Feishu chat is not enough
- an open local `fcodex` session is usually not enough either

## 7. What happens when direct mutation is not yet allowed

Before evaluating direct-write / reset-backend, one idempotent short-circuit
must apply:

- if the requested value already equals the current persisted thread-wise
  setting, the request should succeed immediately
- for profile, this equality check covers the full effective next-load setting:
  `profile`, `model`, `model_provider`
- this is a no-op success; it must not offer reset-backend, and it must not
  actually reset backend

Only when the target value differs from the current persisted setting should the
system continue into the direct-write / reset-backend decision:

1. no-op success
   - the target value already matches the persisted setting
2. direct write
   - the thread is already verifiably globally unloaded
3. offer “apply and reset backend”
   - the thread is not directly writable yet, but the current instance can converge through reset-backend
4. fail closed
   - live runtime is owned by another instance, or the current instance cannot safely reset

That means:

- users should not have to reason about complex detach / attach / unsubscribe relationships first
- the system should prefer a clear “direct write” or “apply and reset backend” path

## 8. Relationship to setting-specific contracts

This document defines only the shared rule set, not the business meaning of each setting.

The setting-specific meaning still lives in:

- thread-wise profile: `docs/contracts/thread-profile-semantics.md`
- thread-wise memory mode: `docs/contracts/thread-memory-semantics.md`
