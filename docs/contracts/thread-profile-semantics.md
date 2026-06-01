# Startup Profile Semantics

Chinese original: `docs/contracts/thread-profile-semantics.zh-CN.md`

Note: this file keeps its historical filename, but it no longer defines a
"thread-wise profile". It now defines the **instance-level startup profile for
a managed backend**.

## 1. Definition

- the startup profile is an **instance-level** setting, not thread-wise state
- it only applies when `app_server_mode=managed`
- its fact source is the instance config field `managed_startup_profile`
- its value space is the set of usable profile-v2 names in the shared
  `CODEX_HOME`
- its purpose is to provide one startup baseline layer for the next managed
  backend process

It does not mean:

- the current thread's next-load profile
- the current Feishu binding's turn-time override
- the immediate live truth of an already loaded backend

## 2. `/profile` and `/profile-clear`

On the Feishu side:

- `/profile`
  - without args: show the current instance startup profile and available
    profile list
  - with an arg: set the current instance startup-profile override
- `/profile-clear`
  - clear the current instance startup-profile override
  - fall back to top-level defaults from shared `CODEX_HOME/config.toml`

These commands:

- do not rewrite the current thread
- do not write any thread-wise persisted state
- do not guarantee immediate mutation of the currently loaded backend

## 3. When it takes effect

The startup profile is consumed at:

- managed backend startup
- managed backend restart after reset

Therefore:

- changing `/profile` only affects the next managed backend start
- if the operator wants the current instance to switch immediately, they must
  reset the backend

## 4. Observable result after backend reset

When the operator chooses "apply and reset backend" from `/profile` or
`/profile-clear`:

- the new backend starts with the new startup profile
- if the current bookmark points to a normal thread, the binding bookmark stays
- if the current bookmark is still a provisional shell, or that thread no
  longer exists, the implementation may clear the current binding bookmark as
  part of reset recovery
- relevant Feishu push paths become `detached` first
- the result card offers `Attach Current Thread`, `Attach Current Instance`, and
  `Keep Detached`

What changes here is:

- the backend process startup baseline

What does not change here is:

- thread identity
- binding identity

## 5. Boundary against other setting families

The project now keeps only two writable setting families:

1. instance startup baseline
   - the startup profile defined here
2. binding-wise next-turn settings
   - `docs/contracts/runtime-control-surface.md`

`/profile` belongs only to family 1.

## 6. Non-goals

The project no longer promises:

- "profile is thread-wise next-load truth"
- "the same thread resume automatically reuses a persisted profile slice"
- "Feishu `/profile` is semantically equivalent to local `fcodex -p`"
- "once a thread is unloaded, profile can still be treated as a thread setting"

The new contract is deliberately narrower:

- startup profile only manages the managed backend startup baseline
- the project no longer owns any thread-wise next-load setting layer
