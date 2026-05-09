# Thread Profile Semantics

Chinese original: `docs/contracts/thread-profile-semantics.zh-CN.md`

This file defines only the profile-specific semantics and entry contract for thread-wise profile behavior.
The shared next-load effect and direct-write / reset-backend rules live in
`docs/contracts/thread-next-load-settings-semantics.md`.

## 1. Basic fact

- profile is **thread-wise**, not binding-wise
- for supported resume paths, the same thread should use the same persisted thread-wise profile when it moves from unloaded back to loaded
- the project no longer keeps an “instance-level default profile” as a user-facing concept

## 2. Feishu-side `/profile [name]`

`/profile` is the formal profile-management entry point for the current thread.

It follows the shared next-load-setting rule, so it has three outcomes:

1. direct write
   - the shared direct-write condition is satisfied
2. offer “apply and reset backend”
   - the shared direct-write condition is not satisfied yet, but the current instance can converge through reset-backend
3. fail closed
   - live runtime is owned by another instance, or the current instance cannot safely reset

## 3. State after reset-backend

When backend reset is triggered from `/profile`:

- binding bookmarks stay
- related Feishu bindings become `detached`
- the thread-wise profile/provider is persisted immediately once the write succeeds
- continued Feishu push is not automatically guaranteed

The result card must offer:

- `Attach Current Thread`
- `Attach Current Instance`
- `Keep Detached`

## 4. Relationship to `/attach` and `/detach`

- `/detach`
  - only pauses Feishu push for a chat
  - does not imply the thread is globally unloaded
- `/attach`
  - only restores Feishu push
  - does not change thread-wise profile

So:

- profile management and attach/detach are different state axes

## 5. Local `fcodex -p`

`fcodex resume <thread> -p <profile>` may rewrite profile only when the thread is not currently loaded.

If the thread is still loaded, the command should reject clearly and tell the user:

- removing `-p/--profile` is the direct way to enter the current session
- if the goal is to change profile, wait until the thread is verifiably globally unloaded
- the common alternative is Feishu `/profile <name>` plus the reset-backend flow

## 6. Old mental models that are no longer valid

These statements are no longer accurate:

- “release runtime first, then change profile”
- “unsubscribe always makes the profile writable”
- “the instance has its own default profile that affects existing threads”

The accurate contract is:

- profile is thread-wise
- next-load effect and direct-write rules are defined by the shared contract
- divergence caused by bare `codex` or other out-of-contract runtime/config mutations is not normalized by this project
