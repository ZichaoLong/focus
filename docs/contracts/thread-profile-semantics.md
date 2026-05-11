# Thread Profile Semantics

Chinese original: `docs/contracts/thread-profile-semantics.zh-CN.md`

This file defines only the profile-specific semantics and entry contract for the
**profile slice** of thread-wise next-load state.
The shared next-load effect and direct-write / reset-backend rules live in
`docs/contracts/thread-next-load-settings-semantics.md`.

## 1. Basic fact

- profile is **thread-wise**, not binding-wise
- for supported resume paths, the same thread should use the same persisted profile slice when it moves from unloaded back to loaded
- the persisted profile slice is the truth for an unloaded thread
- the live runtime is the truth for a loaded thread
- a persisted profile slice is valid only when `profile`, `model`, and
  `model_provider` are all present; supported project paths must fail closed on
  incomplete persisted records
- the project no longer keeps an “instance-level default profile” as a user-facing concept
- for this project's explicit profile-mutation paths, `profile -> model /
  model_provider` is resolved from the shared user-level
  `CODEX_HOME/config.toml` (with runtime provider fallback when needed)
- per-cwd / project-local config is intentionally out of scope for that
  thread-wise profile-slice contract

## 2. Feishu-side `/profile [name]`

`/profile` is the formal profile-management entry point for the current thread.

It follows the shared next-load-setting rule, so it has three outcomes:

1. direct write
   - the shared direct-write condition is satisfied
2. offer “apply and reset backend”
   - the shared direct-write condition is not satisfied yet, but the current instance can converge through reset-backend
3. fail closed
   - live runtime is owned by another instance, the current instance cannot
     safely reset, or the target profile cannot resolve to a concrete
     `profile` + `model` + `model_provider` tuple

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

One idempotent exception is allowed:

- if the requested effective next-load profile setting already equals the
  persisted thread-wise setting for that thread, the command may continue as a
  no-op reuse even while the thread is still loaded
- for profile, this equality check covers the full persisted tuple:
  `profile`, `model`, `model_provider`
- if the profile name is the same but resolved `model` or `model_provider`
  differs, that is not no-op reuse; it is still a profile-setting change and
  must follow the normal direct-write / reset-backend admission rule
- here "resolved" means the thread-stable project contract above, not
  upstream's per-cwd / per-repo config resolution
- for an unloaded thread, plain `fcodex resume <thread>` keeps using the
  persisted tuple, even if the profile name now resolves differently in local
  config
- for an unloaded thread, explicit `fcodex resume <thread> -p <profile>`
  requests the profile name's current effective setting and rewrites the
  persisted tuple before resume
- for a loaded thread, plain `fcodex resume <thread>` joins the live runtime;
  it does not try to reconcile persisted-profile drift against current local
  config

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
