# Thread Next-Load Settings Semantics

Chinese original: `docs/contracts/thread-next-load-settings-semantics.zh-CN.md`

This document defines a shared contract class: **thread-wise, persisted settings that take effect on next-load**.

The current settings in this class are:

- thread-wise profile
- thread-wise memory mode

Future thread-wise restore settings should reuse this document instead of copying another restore/mutation rule stack.

## 1. Basic fact

- these settings are **thread-wise**, not binding-wise
- for **supported resume paths**, the contract is: when the same thread moves from unloaded back to loaded, it should use the same persisted setting
- they are **not** the hot-update truth for an already loaded runtime

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

## 3. When direct mutation is allowed

These settings may be written directly only when the thread is **verifiably globally unloaded**.

That requires at least:

- no attached Feishu binding on the thread
- no live runtime lease on the thread
- backend confirmation that the thread is not loaded

Therefore:

- detached alone is not enough
- closing one Feishu chat is not enough
- an open local `fcodex` session is usually not enough either

## 4. What happens when direct mutation is not yet allowed

Before evaluating direct-write / reset-backend, one idempotent short-circuit
must apply:

- if the requested value already equals the current persisted thread-wise
  setting, the request should succeed immediately
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

## 5. Relationship to setting-specific contracts

This document defines only the shared rule set, not the business meaning of each setting.

The setting-specific meaning still lives in:

- thread-wise profile: `docs/contracts/thread-profile-semantics.md`
- thread-wise memory mode: `docs/contracts/thread-memory-semantics.md`
