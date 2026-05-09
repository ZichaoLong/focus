# Local Commands and Thread Profile Contract

Chinese original: `docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`

This file clarifies four things only:

- the responsibility boundary between `feishu-codex`, `feishu-codexctl`, and `fcodex`
- how thread-wise profile behaves locally and in Feishu
- how thread-wise memory mode behaves locally and in Feishu
- why the public local command surface now uses attach / detach instead of exposing release-runtime

## 1. Three local entry points

### 1.1 `feishu-codex`

Owns:

- install
- service lifecycle
- autostart
- instance management
- project-level helper actions such as skill installation

Does not own:

- entering the Codex TUI
- inspecting one binding / thread's low-level state

### 1.2 `feishu-codexctl`

Owns:

- viewing running instances
- viewing target-instance service / binding / thread state
- limited local binding / thread / image management

Does not own:

- entering the Codex TUI
- rewriting upstream thread history directly

### 1.3 `fcodex`

Owns:

- resuming a local live thread
- entering the Codex TUI
- acting as an independent local frontend subscriber to the backend thread

It is not:

- a mirror of the Feishu command surface
- a service-management CLI

## 2. Formal local naming

The public local naming should now stay aligned with the Feishu surface:

- `service attach`
- `binding attach`
- `binding detach`
- `thread attach`
- `thread detach`

The lower layer may still call:

- `thread/unsubscribe`

But that is now an internal service protocol detail, not a user-facing concept.

## 3. Local routing contract for `fcodex`

`fcodex` now has only two routing categories:

1. thread-targeted resume:
   - `fcodex resume <thread_id|thread_name>`
2. threadless launch:
   - `fcodex`
   - `fcodex <prompt>`
   - other non-resume TUI entry paths that create or continue from no explicit thread target

The formal routing rule is:

- thread-targeted resume must not rely on `default-running` fallback
- threadless launch may still use the convenience fallback:
  - explicit `--instance` wins
  - otherwise the unique running instance wins
  - otherwise a running `default` may win
  - otherwise the command must ask for explicit `--instance`

For thread-targeted resume:

- explicit `--instance` still wins
- `resume <thread_id>` should prefer the live runtime owner when one exists
- `resume <thread_name>` should first resolve the real `thread_id`, then route using thread-aware facts
- if the system still cannot determine one clear target instance, it must reject and ask for explicit `--instance`

## 4. Profile and memory are thread-wise next-load settings

This rule is identical locally and in Feishu:

- for supported resume paths, the same thread should use the same persisted thread-wise setting when it moves from unloaded back to loaded
- binding only answers “which thread does this chat remember”
- attach / detach only answers “does this Feishu chat receive push”

The shared next-load effect and direct-write / reset-backend rules live in
`docs/contracts/thread-next-load-settings-semantics.md`.

## 5. How local profile mutation works

### 5.1 New thread

New threads may be created through:

- `fcodex -p <profile> new`
- or Feishu `/new` followed by `/profile <name>`

### 5.2 Existing thread

The direct-write rule for an existing thread is defined in
`docs/contracts/thread-next-load-settings-semantics.md`.

Therefore:

- `fcodex resume <thread> -p <profile>` must reject while the thread is still loaded
- the user should not be forced to reason about release-runtime / unsubscribe first
- the preferred recovery path is Feishu `/profile <name>`, with reset-backend when needed

### 5.3 Thread-wise memory mode

The local command surface does not currently expose a standalone thread-wise memory-mode mutator.

The formal contract is:

- Feishu `/memory [off|read|read_write]` mutates the thread-wise memory mode
- for supported resume paths, `fcodex resume <thread>` automatically reuses the persisted memory mode when resuming that thread
- the shared direct-write / reset-backend rule is defined in `docs/contracts/thread-next-load-settings-semantics.md`
- the memory-mode-specific business semantics are defined in `docs/contracts/thread-memory-semantics.md`

## 6. reset-backend locally and in Feishu

Whether triggered from Feishu or from local `feishu-codexctl service reset-backend`:

- the backend is reset
- binding bookmarks stay
- related Feishu bindings become `detached`
- thread-wise profile/provider state stays

After that, if the user wants Feishu push again, they must explicitly choose:

- attach the current thread
- attach the current instance
- or keep detached

## 7. Why release-runtime is no longer the main wording

Because it collapsed three different layers into one fuzzy concept:

- whether the binding still remembers the thread
- whether Feishu still receives push
- whether the backend is still loaded

The clearer contract is now:

- `binding`
- `attach / detach`
- `backend / live runtime`

This lets local and Feishu surfaces share one coherent mental model without making the user guess which layer “release” actually released.
