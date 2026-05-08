# Local Commands and Thread Profile Contract

Chinese original: `docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`

This file clarifies three things only:

- the responsibility boundary between `feishu-codex`, `feishu-codexctl`, and `fcodex`
- how thread-wise profile behaves locally and in Feishu
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

## 3. Profile is thread-wise, not binding-wise

This rule is identical locally and in Feishu:

- the same thread must see the same thread-wise profile no matter whether it is resumed from Feishu or `fcodex`
- binding only answers “which thread does this chat remember”
- attach / detach only answers “does this Feishu chat receive push”

## 4. How local profile mutation works

### 4.1 New thread

New threads may be created through:

- `fcodex -p <profile> new`
- or Feishu `/new` followed by `/profile <name>`

### 4.2 Existing thread

An existing thread may be rewritten directly only when it is **verifiably globally unloaded**.

Therefore:

- `fcodex resume <thread> -p <profile>` must reject while the thread is still loaded
- the user should not be forced to reason about release-runtime / unsubscribe first
- the preferred recovery path is Feishu `/profile <name>`, with reset-backend when needed

## 5. reset-backend locally and in Feishu

Whether triggered from Feishu or from local `feishu-codexctl service reset-backend`:

- the backend is reset
- binding bookmarks stay
- related Feishu bindings become `detached`
- thread-wise profile/provider state stays

After that, if the user wants Feishu push again, they must explicitly choose:

- attach the current thread
- attach the current instance
- or keep detached

## 6. Why release-runtime is no longer the main wording

Because it collapsed three different layers into one fuzzy concept:

- whether the binding still remembers the thread
- whether Feishu still receives push
- whether the backend is still loaded

The clearer contract is now:

- `binding`
- `attach / detach`
- `backend / live runtime`

This lets local and Feishu surfaces share one coherent mental model without making the user guess which layer “release” actually released.
