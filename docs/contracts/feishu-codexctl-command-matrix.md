# `feishu-codexctl` Command Matrix

Chinese original: `docs/contracts/feishu-codexctl-command-matrix.zh-CN.md`

This file defines the formal local `feishu-codexctl` management surface.

It answers:

- which resources `feishu-codexctl` owns
- which commands are read-only vs mutating
- how thread targets are selected
- how it maps to the Feishu command surface

## 1. Core Positioning

- `feishu-codexctl` is the local inspection / management surface. It is not a second Codex frontend.
- Use `fcodex` when you want to continue a live thread locally.
- Use `feishu-codex` when you want install, repair, service lifecycle, or instance management.
- Use `feishu-codexctl` when you want local service / binding / thread status or local thread-scoped management.

## 2. Instance and Target Resolution

- Every command except `instance list` accepts `--instance <name>`.
- An explicit `--instance` always wins.
- A named instance used here must already have been created via
  `feishu-codex instance create <name>`; `feishu-codexctl` never creates it
  implicitly.
- Otherwise resolution follows `preferred-running -> unique-running -> default-running -> current-instance-paths`.
- `thread status`, `thread bindings`, `thread goal`, `thread attach`, and `thread detach` require exactly one of:
  - `--thread-id <id>`
  - `--thread-name <name>`
- `thread clear-archived-bindings` requires exactly one of `--thread-id <id>` or `--all`; it does not accept `--thread-name`, so local bookmark cleanup does not depend on another upstream thread-name resolution step.
  - `--thread-id` clears local binding bookmarks for the given thread id without validating upstream archived state.
  - `--all` first queries upstream archived threads through a running instance, then clears local binding bookmarks that point to those archived thread ids; without an available running instance it fails closed and does not mutate local data.
- `thread archive` supports two target forms:
  - single-thread: `--thread-name <name>` or `--thread-id <id>`
  - batch: repeat `--thread-id <id>`; each target thread is routed, archived, and locally cleaned up independently using the existing single-thread archive semantics

## 3. Resource Layers

`feishu-codexctl` is split into six resource groups:

- `instance`
- `service`
- `binding`
- `prompt`
- `thread`
- `image`

Important mental model:

- `binding` is the chat-scoped view
- `thread` is the thread-scoped view

Do not conflate them.

## 4. Commands

### 4.1 `instance`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl instance list` | List running local instances, owner pid, control endpoint, and app-server URL | read-only | none |

### 4.2 `service`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] service status` | Show the target instance's service / control-plane / app-server overview | read-only | no exact single command |
| `feishu-codexctl [--instance <name>] service reset-backend [--force]` | Reset the current instance backend for recovery without restarting the `feishu-codex` service | mutating | Feishu `/reset-backend` |
| `feishu-codexctl [--instance <name>] service attach` | Restore all recoverable detached Feishu push in the current instance | mutating | Feishu `/attach service`, and the post-reset `Attach Current Instance` button |

### 4.3 `binding`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] binding list` | List bindings visible in the target instance | read-only | none |
| `feishu-codexctl [--instance <name>] binding status <binding_id>` | Show one binding's chat, thread, push state, next-prompt status, current-instance interaction owner, and session settings | read-only | lower-level diagnostics behind Feishu `/status` and `/preflight` |
| `feishu-codexctl [--instance <name>] binding attach <binding_id>` | Restore Feishu push for one binding | mutating | Feishu `/attach binding` |
| `feishu-codexctl [--instance <name>] binding detach <binding_id>` | Pause Feishu push for one binding while keeping its bookmark | mutating | binding-scoped counterpart of Feishu `/detach` |
| `feishu-codexctl [--instance <name>] binding clear <binding_id>` | Clear one binding bookmark | mutating | none |
| `feishu-codexctl [--instance <name>] binding clear-all` | Clear all binding bookmarks in the target instance | mutating | none |
| `feishu-codexctl [--instance <name>] binding clear-stale [--dry-run]` | Clear stale binding bookmarks that point at threads that can no longer be read; by default scans all running instances and known stopped instances, while explicit `--instance` limits the action to that instance | mutating | none; this is a local bookmark repair / ops entry |

`binding clear` / `clear-all` / `clear-stale` are not `detach`:

- `clear` removes the local bookmark
- `detach` removes the current Feishu push attachment

`binding clear-stale` is retain-oriented:

- it first verifies each bound `current_thread_id` through `thread/read` on a running app-server
- readable threads are retained
- threads that are explicitly unreadable are treated as stale, and matching local bookmarks are cleared
- query failures, timeouts, protocol errors, and ambiguous states fail closed: the binding is retained and reported as unknown
- running instances are cleaned through their service control plane; known stopped instances are cleaned through this project's binding store API

### 4.4 `prompt`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] prompt send --binding-id <binding_id> (--text <text> \| --text-file <file>) [--synthetic-source <label>] [--display-mode silent\|announce]` | Use the target instance control plane to synthetically start one new prompt turn on a binding | mutating | none; this is the local control-plane synthetic prompt entry |

Notes:

- `prompt send` is **binding-scoped**, not thread-scoped.
- Actual execution still goes through the normal running-turn / attach / interaction protections inside the service.
- When the target binding is not writable, the command must fail closed with a refusal reason instead of silently queueing work.

### 4.5 `thread`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] thread list [--scope cwd\|global] [--cwd <path>]` | Browse persisted threads; default is current-directory scope | read-only | target-discovery counterpart of Feishu `/threads` |
| `feishu-codexctl [--instance <name>] thread status (--thread-id <id> \| --thread-name <name>)` | Show backend status, live runtime owner / holders, and bound / attached / detached bindings for one thread | read-only | no exact single command |
| `feishu-codexctl [--instance <name>] thread bindings (--thread-id <id> \| --thread-name <name>)` | Show all bindings currently pointing at one thread | read-only | none |
| `feishu-codexctl [--instance <name>] thread goal (--thread-id <id> \| --thread-name <name>)` | Show the current goal for one thread; this is the default show form | read-only | Feishu `/goal` |
| `feishu-codexctl [--instance <name>] thread goal set (--thread-id <id> \| --thread-name <name>) [--objective <text>] [--status active\|paused]` | Apply a raw persisted-thread goal mutation for debugging or ops; at least one of `--objective` or `--status` is required | mutating | Feishu `/goal set <objective>` for objective writes; no exact Feishu equivalent for raw `--status active\|paused` edits |
| `feishu-codexctl [--instance <name>] thread goal clear (--thread-id <id> \| --thread-name <name>)` | Clear the current goal on one thread | mutating | Feishu `/goal clear` |
| `feishu-codexctl [--instance <name>] thread archive (--thread-id <id> [--thread-id <id> ...] \| --thread-name <name>)` | Archive one or more target threads; after a successful archive, clear local bindings that still point to it in the target instance, other reachable running instances, and known stopped instances | mutating | local operational counterpart of Feishu `/archive`; batch and cross-instance local binding cleanup are local-CLI only |
| `feishu-codexctl [--instance <name>] thread clear-archived-bindings (--thread-id <id> \| --all) [--dry-run]` | Clear local binding bookmarks left behind for archived threads; does not call upstream archive; `--thread-id` clears one specified thread, while `--all` queries upstream archived threads before clearing matching bookmarks; by default scans all running instances and known stopped instances, while explicit `--instance` limits the action to that instance | mutating | none; this is a local bookmark repair / ops entry |
| `feishu-codexctl [--instance <name>] thread attach (--thread-id <id> \| --thread-name <name>)` | Restore Feishu push for all detached bindings on one target thread | mutating | Feishu `/attach thread`, and the post-reset `Attach Current Thread` button |
| `feishu-codexctl [--instance <name>] thread detach (--thread-id <id> \| --thread-name <name>)` | Pause Feishu push for one target thread while keeping thread / binding relationships intact | mutating | no exact single Feishu command |

Implementation note:

- local `thread detach` goes through the running `feishu-codex` service control plane
- the lower layer may still call upstream `thread/unsubscribe`, but that is an internal protocol detail, not the user-facing command name
- local `thread archive` calls upstream Codex archive exactly once; after that succeeds, binding cleanup is split by instance state:
  - other running instances are cleaned through their service control plane, and that local cleanup does not call upstream archive again
  - known stopped instances are cleaned through this project's binding store API for matching `thread_id` bookmarks; the command does not hand-edit `chat_bindings.json`
- if cleanup in a running instance fails because of a running turn, pending request, or unreachable control plane, the upstream archive remains done, but the command exits non-zero and prints a cleanup warning
- `thread clear-archived-bindings` reuses the same local binding cleanup logic but does not archive. It is for repairing leftovers from older versions, externally archived threads, or no-live-owner archive routing after a service restart.
  - `--thread-id` is the explicit repair path; the command does not query upstream just to validate archived state.
  - `--all` is an archived-aware sweep: it first calls upstream `thread/list archived=true` through a running app-server to collect archived thread ids, then reuses the local cleanup path for each id. Without `--instance`, it prefers a running `default` instance for the query, otherwise picks one running instance by name, and cleans all visible instances; with explicit `--instance`, that instance must be running and only that instance is cleaned.

### 4.6 `image`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] image send --path <file> [--thread-id <id> \| --thread-name <name>]` | Send one local image file to all currently attached Feishu bindings on the target thread | mutating | none; this is a local control-plane action |

## 5. Mapping to Feishu

| Local command | Closest Feishu entry | Key difference |
| --- | --- | --- |
| `service reset-backend` | `/reset-backend` | both are instance-level backend actions; one is CLI, one is a Feishu card flow |
| `service attach` | `/attach service` | both are instance-level recovery actions; the Feishu primary entry usually comes from a reset result card |
| `binding status <binding_id>` | `/status`, `/preflight` | local output is lower-level and includes binding ids, reason codes, and current-instance interaction owner details |
| `binding attach <binding_id>` | `/attach binding` | local command can target any known binding id directly; Feishu defaults to the current chat binding |
| `binding detach <binding_id>` | `/detach` | Feishu `/detach` is only current-chat scoped; local command can target any known binding id directly |
| `prompt send --binding-id <binding_id>` | none | local CLI can synthesize a future or system-triggered prompt through the service control plane; there is no equivalent Feishu slash command today |
| `thread attach --thread-id/--thread-name` | `/attach thread` | Feishu thread scope is limited to the current chat's current thread; local command can target any thread directly |
| `thread detach --thread-id/--thread-name` | no exact single Feishu command | Feishu `/detach` is current-binding scoped; the local thread action can affect all currently attached bindings on that thread |
| `thread goal --thread-id/--thread-name` | `/goal` | Feishu only operates on the current chat's current thread; local CLI is a thread-scoped debugging / ops surface and can read any explicit target thread goal |
| `thread goal set/clear` | `/goal set`, `/goal clear` | Feishu commands only affect the current chat's current thread; local CLI can target any explicit thread directly. `thread goal set --status active\|paused` is only a thread-scoped persisted-goal mutation, not a `/goal pause` or `/goal resume` equivalent |
| `thread list --scope cwd` | `/threads` | Feishu is a chat workflow entry point; local CLI is just thread discovery |
| `thread status` | lower-level diagnostics behind `/status`, `/preflight`, `/attach`, `/detach` | local CLI is a thread-scoped debugging surface |

## 6. Boundary

The following expectations are explicitly wrong:

- `feishu-codexctl` is not a local UI for Feishu `/threads`
- `feishu-codexctl` does not enter the Codex TUI
- `binding clear` does not mean “stop push for the current thread”
- `thread goal set --status active|paused` is not a runtime recovery / pause command; it does not promise load, settings sync, or immediate execution

If any `feishu-codexctl` subcommand is added, removed, renamed, or changes its selector rules, instance resolution, or Feishu mapping, this document must change with the code.
