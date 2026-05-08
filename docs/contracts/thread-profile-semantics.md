# Thread Profile Semantics

Chinese original: `docs/contracts/thread-profile-semantics.zh-CN.md`

This file defines only the contract for thread-wise profile behavior.

## 1. Basic fact

- profile is **thread-wise**, not binding-wise
- when a thread is resumed from any frontend, the same thread-wise profile should be observed
- the project no longer keeps an “instance-level default profile” as a user-facing concept

## 2. When direct mutation is allowed

A thread-wise profile may be written directly only when the thread is **verifiably globally unloaded**.

That requires at least:

- no attached Feishu binding on the thread
- no live runtime lease on the thread
- backend confirmation that the thread is not loaded

Therefore:

- detached alone is not enough
- closing one Feishu chat is not enough
- an open local `fcodex` session is usually not enough either

## 3. Feishu-side `/profile [name]`

`/profile` is the formal profile-management entry point for the current thread.

It has three outcomes:

1. direct write
   - the thread is already verifiably globally unloaded
2. offer “apply and reset backend”
   - the thread is not directly writable yet, but the current instance can converge through reset-backend
3. fail closed
   - live runtime is owned by another instance, or the current instance cannot safely reset

## 4. State after reset-backend

When backend reset is triggered from `/profile`:

- binding bookmarks stay
- related Feishu bindings become `detached`
- the thread-wise profile/provider is persisted immediately once the write succeeds
- continued Feishu push is not automatically guaranteed

The result card must offer:

- `Attach Current Thread`
- `Attach Current Instance`
- `Keep Detached`

## 5. Relationship to `/attach` and `/detach`

- `/detach`
  - only pauses Feishu push for a chat
  - does not imply the thread is globally unloaded
- `/attach`
  - only restores Feishu push
  - does not change thread-wise profile

So:

- profile management and attach/detach are different state axes

## 6. Local `fcodex -p`

`fcodex resume <thread> -p <profile>` may rewrite profile only when the thread is not currently loaded.

If the thread is still loaded, the command should reject clearly and tell the user:

- removing `-p/--profile` is the direct way to enter the current session
- if the goal is to change profile, wait until the thread is verifiably globally unloaded
- the common alternative is Feishu `/profile <name>` plus the reset-backend flow

## 7. Old mental models that are no longer valid

These statements are no longer accurate:

- “release runtime first, then change profile”
- “unsubscribe always makes the profile writable”
- “the instance has its own default profile that affects existing threads”

The accurate contract is:

- profile is thread-wise
- writability depends on verifiable global unload
- if that condition is not met, the system should converge through reset-backend rather than forcing the user to reason about more low-level actions
