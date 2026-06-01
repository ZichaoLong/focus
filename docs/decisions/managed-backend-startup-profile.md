# Managed Backend Startup Profile

Chinese original: `docs/decisions/managed-backend-startup-profile.zh-CN.md`

See also:

- `docs/contracts/thread-profile-semantics.md`
- `docs/contracts/thread-memory-semantics.md`
- `docs/contracts/thread-next-load-settings-semantics.md`
- `docs/architecture/fcodex-shared-backend-runtime.md`
- `docs/contracts/local-command-and-thread-profile-contract.md`

## 1. Status

This document records the current product conclusion and the recommended next
design direction.

It separates two layers:

- **verified current facts**
  - behavior already confirmed in current code and upstream behavior
- **recommended future capability**
  - not implemented in this repository yet, but currently the better product
    route

Until implementation lands, current shipped behavior is still defined by the
existing contracts and code.

## 2. Problem

There is a specific provider/catalog tension in the current project:

- bare `codex -p <profile>` often gets its own app-server / TUI runtime per
  invocation
- one `feishu-codex` instance keeps reusing one long-lived shared backend

That creates one key difference:

- bare `codex` may resolve backend-global model metadata / catalog at startup
  for that specific profile
- a `feishu-codex` shared backend can only decide one backend-global model
  metadata / catalog view when that backend starts

Therefore, if a provider such as ZAI / GLM needs its own
`model_catalog_json` to get accurate model metadata, context-window settings,
and related behavior tuning, then:

- bare `codex` can consume that catalog through its isolated startup path
- `feishu-codex` cannot switch the shared backend's backend-global catalog
  later through thread-wise `/profile` alone

The visible symptom is often:

- the actual provider call may already be GLM
- but backend model metadata for that slug is still unresolved
- TUI, `/model`, and base instructions fall back to generic metadata
- warnings appear, or the assistant self-identifies in a GPT/OpenAI-shaped way

## 3. Current Facts

### 3.1 backend-global catalog and thread-wise profile are different state layers

This project already treats:

- `profile`
- `memory`

as **thread-wise next-load state**.

That means the contract is:

- for supported resume paths, when the same thread moves from unloaded back to
  loaded, it should reuse the same persisted next-load setting

But backend-global model metadata, `model/list`, and catalog path are not part
of that state layer.

They are shared backend facts chosen when the backend starts.

### 3.2 `remote` mode only means “connect to an external backend”

The exact meaning of `app_server_mode = remote` is:

- the current instance no longer launches and owns the backend process
- it only connects to an already-running external app-server endpoint

So remote mode can be used to attach to a backend that was started elsewhere
with a specific profile, but that still only means "use an external backend".
It does not give this repository a native provider-aware backend startup
control surface.

### 3.3 `remote` mode is not a good primary path for thread-wise next-load settings

In the current repository, the remaining formal setting surfaces are:

- instance startup profile
- binding-wise next-turn settings

When the target thread is still loaded, those settings often need unload /
`reset-backend` convergence.

But in remote mode, the instance does not own the backend process, so it cannot
perform `reset-backend`.

That makes remote mode more than a minor catalog difference. It also weakens:

- `/profile`
- local control-plane flows that rely on `reset-backend`

### 3.4 the project intentionally does not keep an “instance-level default profile”

The current contract already states:

- the project no longer keeps an “instance-level default profile” as a
  user-facing concept

The key issue is not only whether existing threads are retroactively rewritten.
The deeper problem is the user mental model:

- once a feature is named a “default profile”, users naturally infer that
  whenever a thread is loaded without an explicit override, it should be
  re-resolved from that default profile

That conflicts with the current thread-wise next-load contract.

The current source of truth remains:

- for unloaded threads, persisted thread-wise next-load state is the truth

## 4. Rejected Paths

### 4.1 no longer target “one backend where GPT and GLM both get their own optimal catalogs”

That is now an explicitly dropped goal.

The reason is not just implementation complexity. The state layers themselves
do not match:

- catalog / model metadata are backend-global
- `profile` / `memory` are thread-wise

Thread-wise profile switching alone cannot make one long-lived shared backend
hold two different backend-global catalog truths at the same time.

### 4.2 do not use `remote` as the main ZAI catalog solution

Remote may still be useful as a debug or temporary wiring path, but it should
not become the main product route for using ZAI well.

Reason:

- it moves provider-aware backend startup control outside the repository
- it removes `reset-backend` from the current instance
- it degrades the formal convergence path for thread-wise `profile` /
  `memory`

### 4.3 do not name the future capability an “instance-level default profile”

If a new backend-startup feature is introduced later, it should not be named:

- `default_profile`
- `instance_default_profile`

Those names wrongly imply that a backend startup default is also the thread's
default source of truth.

## 5. Decision

### 5.1 the more appropriate next route is `managed backend startup profile`

If a future instance should serve a specific provider better, such as ZAI /
GLM, the more appropriate capability is:

- `managed backend startup profile`

Its purpose is not to replace thread-wise profile semantics. Its purpose is to
fill the missing backend-startup control layer.

### 5.2 exact semantics of that capability

If implemented, this capability should be tightly defined as:

- effective only when `app_server_mode = managed`
- only affecting the backend process launched by the current instance
- used when the backend starts and when a managed backend is restarted after
  `reset-backend`
- deciding which active configuration the backend consumes at startup
- therefore affecting backend-global:
  - active profile resolution
  - `model/list`
  - model metadata
  - catalog path

It should **not** mean:

- no write into thread-wise profile store
- no new project-owned thread-level persisted setting
- no retroactive rewrite of already loaded threads
- no pretending to be the thread's “default profile truth”

### 5.3 relationship to existing thread-wise state

If this capability lands, the recommended separation is:

- backend startup profile
  - defines only backend-global startup defaults
- thread-wise profile / memory
  - continue to define the persisted next-load setting for one thread

In other words:

- existing thread truth is still defined by persisted thread-wise state
- backend startup profile is only the shared backend baseline at startup

For a new thread, backend startup profile should matter only when there is
**no explicit thread-wise seed and no request-time explicit override**.

### 5.4 this is not “route threads/providers to different backends”

The current product direction explicitly does not accept:

- dynamic backend choice inside one instance based on thread/profile/provider

So the design assumption of backend startup profile is:

- one instance still owns one managed backend
- only the startup configuration of that backend becomes more explicit

## 6. Supporting Constraints

### 6.1 if startup profile is used, instance-level `model` / `model_provider` should usually stay empty

Current new-thread creation paths prefer request-level or instance-level
`model` / `model_provider` when they inject `thread/start` parameters.

If backend startup profile is introduced later, but instance config still pins:

- `model`
- `model_provider`

then those explicit injected values may still mask backend startup defaults and
make behavior ambiguous again.

So if the goal is to keep a clearer backend startup baseline while the shared
backend still serves multiple thread-wise profiles, instance-level `model` /
`model_provider` should usually remain empty.

### 6.2 `reset-backend` should reuse the same startup profile

If the capability is implemented, restarting a managed backend after
`reset-backend` should reuse the same startup profile.

Otherwise users would see an unstable result:

- initial instance startup gives a ZAI-aware backend
- `reset-backend` falls back to a generic backend

That would directly break the predictability of the feature.

## 7. Operational Conclusion

After this discussion, the repository should follow these conclusions:

- stop targeting “one backend that mixes GPT and GLM while both get their own
  optimal catalogs”
- if the goal is to use ZAI well while preserving the existing product
  contract around `/profile`, `/reset-backend`, and turn-time settings, the
  better
  future route is:
  - one dedicated instance
  - `managed` backend mode
  - an explicit backend startup profile that lets that backend start with the
    ZAI-aware catalog it needs
- that capability should be defined as backend startup control, not as the
  thread's default-profile source of truth

## 8. Non-goals

This document does not define:

- provider-specific catalog overlay inside one backend
- dynamic backend routing by thread/profile/provider
- any rewrite of current shipped thread-wise profile / memory semantics
- any fake `reset-backend` patch semantics for remote mode
