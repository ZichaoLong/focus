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
- Otherwise resolution follows `preferred-running -> unique-running -> default-running -> current-instance-paths`.
- `thread status`, `thread bindings`, `thread archive`, `thread attach`, and `thread detach` require exactly one of:
  - `--thread-id <id>`
  - `--thread-name <name>`

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
| `feishu-codexctl [--instance <name>] service reset-backend [--force]` | Reset the current instance backend without restarting the `feishu-codex` service | mutating | Feishu `/reset-backend` |
| `feishu-codexctl [--instance <name>] service attach` | Restore all recoverable detached Feishu push in the current instance | mutating | Feishu `/attach service`, and the post-reset `Attach Current Instance` button |

### 4.3 `binding`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] binding list` | List bindings visible in the target instance | read-only | none |
| `feishu-codexctl [--instance <name>] binding status <binding_id>` | Show one binding's chat, thread, push state, next-prompt status, interaction owner, and session settings | read-only | lower-level diagnostics behind Feishu `/status` and `/preflight` |
| `feishu-codexctl [--instance <name>] binding attach <binding_id>` | Restore Feishu push for one binding | mutating | Feishu `/attach binding` |
| `feishu-codexctl [--instance <name>] binding detach <binding_id>` | Pause Feishu push for one binding while keeping its bookmark | mutating | binding-scoped counterpart of Feishu `/detach` |
| `feishu-codexctl [--instance <name>] binding clear <binding_id>` | Clear one binding bookmark | mutating | none |
| `feishu-codexctl [--instance <name>] binding clear-all` | Clear all binding bookmarks in the target instance | mutating | none |

`binding clear` is not `detach`:

- `clear` removes the local bookmark
- `detach` removes the current Feishu push attachment

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
| `feishu-codexctl [--instance <name>] thread archive (--thread-id <id> \| --thread-name <name>)` | Archive a target thread and clear bindings that still point to it in the target instance | mutating | local instance-scoped counterpart of Feishu `/archive` |
| `feishu-codexctl [--instance <name>] thread attach (--thread-id <id> \| --thread-name <name>)` | Restore Feishu push for all detached bindings on one target thread | mutating | Feishu `/attach thread`, and the post-reset `Attach Current Thread` button |
| `feishu-codexctl [--instance <name>] thread detach (--thread-id <id> \| --thread-name <name>)` | Pause Feishu push for one target thread while keeping thread / binding relationships intact | mutating | no exact single Feishu command |

Implementation note:

- local `thread detach` goes through the running `feishu-codex` service control plane
- the lower layer may still call upstream `thread/unsubscribe`, but that is an internal protocol detail, not the user-facing command name

### 4.6 `image`

| Command | Purpose | Type | Feishu counterpart |
| --- | --- | --- | --- |
| `feishu-codexctl [--instance <name>] image send --path <file> [--thread-id <id> \| --thread-name <name>]` | Send one local image file to all currently attached Feishu bindings on the target thread | mutating | none; this is a local control-plane action |

## 5. Mapping to Feishu

| Local command | Closest Feishu entry | Key difference |
| --- | --- | --- |
| `service reset-backend` | `/reset-backend` | both are instance-level backend actions; one is CLI, one is a Feishu card flow |
| `service attach` | `/attach service` | both are instance-level recovery actions; the Feishu primary entry usually comes from a reset result card |
| `binding status <binding_id>` | `/status`, `/preflight` | local output is lower-level and includes binding ids, reason codes, and interaction owner details |
| `binding attach <binding_id>` | `/attach binding` | local command can target any known binding id directly; Feishu defaults to the current chat binding |
| `binding detach <binding_id>` | `/detach` | Feishu `/detach` is only current-chat scoped; local command can target any known binding id directly |
| `prompt send --binding-id <binding_id>` | none | local CLI can synthesize a future or system-triggered prompt through the service control plane; there is no equivalent Feishu slash command today |
| `thread attach --thread-id/--thread-name` | `/attach thread` | Feishu thread scope is limited to the current chat's current thread; local command can target any thread directly |
| `thread detach --thread-id/--thread-name` | no exact single Feishu command | Feishu `/detach` is current-binding scoped; the local thread action can affect all currently attached bindings on that thread |
| `thread list --scope cwd` | `/threads` | Feishu is a chat workflow entry point; local CLI is just thread discovery |
| `thread status` | lower-level diagnostics behind `/status`, `/preflight`, `/attach`, `/detach` | local CLI is a thread-scoped debugging surface |

## 6. Boundary

The following expectations are explicitly wrong:

- `feishu-codexctl` is not a local UI for Feishu `/threads`
- `feishu-codexctl` does not enter the Codex TUI
- `binding clear` does not mean “stop push for the current thread”

If any `feishu-codexctl` subcommand is added, removed, renamed, or changes its selector rules, instance resolution, or Feishu mapping, this document must change with the code.
