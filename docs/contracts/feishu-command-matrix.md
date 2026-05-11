# Feishu Command Matrix

Chinese original: `docs/contracts/feishu-command-matrix.zh-CN.md`

This file is the source-of-truth matrix for the Feishu command surface.

It answers four questions only:

- which slash commands are formally supported
- which commands are reachable from `/help`
- who may execute them in P2P and group chats
- which local surface is the closest counterpart

It does not redefine:

- binding / attach / detach / backend state semantics
- when a thread-wise profile is mutable
- the full group-chat contract

## 1. Reading Rules

- “Reachable from `/help`” means reachable through help-page buttons, forms, or follow-up result cards.
- “Admin only” means the current bot's admin check must pass.
- “Anyone” only means no admin check in that scope; it does not mean all group members may mutate shared state.

## 2. Commands

### 2.1 Navigation, Chat, and Thread

| Command | Purpose | Reachable from `/help` | P2P | Group | Closest local counterpart |
| --- | --- | --- | --- | --- | --- |
| `/help [chat\|group\|thread\|runtime\|identity]` | Open help navigation or one page directly | yes | admin only | admin only | none |
| `/commands` | Show a plain-text list of common commands | no | admin only | admin only | none |
| `/h` | Alias for `/help` | no | admin only | admin only | none |
| `/pwd` | Show current working directory | no | admin only | admin only | none |
| `/status` | Show current chat's directory, current thread, and current-session settings summary | yes; `chat` page | admin only | admin only | `feishu-codexctl binding status <binding_id>` for deeper diagnostics |
| `/preflight` | Dry-run the next plain message and current-chat detach availability | yes; `chat` page | admin only | admin only | partly overlaps `feishu-codexctl binding status <binding_id>` |
| `/cd [path]` | Show or switch current directory; switching clears current thread binding | yes; `chat` page form | admin only | admin only | none |
| `/new` | Create a new current thread | yes; `thread` page | admin only | admin only | none |
| `/threads` | Browse threads in the current directory | yes; `thread` page | admin only | admin only | `feishu-codexctl thread list --scope cwd` |
| `/resume <thread_id\|thread_name>` | Resume a target thread into the current chat | yes; `thread` page form | admin only | admin only | use `fcodex resume <thread_id\|thread_name>` for local live-thread continuation |
| `/profile [name]` | Show or change the current thread's thread-wise profile | yes; `thread -> current thread` | admin only | admin only | no direct local equivalent |
| `/memory [off\|read\|read_write]` | Show or change the current thread's thread-wise memory mode | yes; `thread -> current thread` | admin only | admin only | `feishu-codexctl thread memory --thread-id/--thread-name`; `fcodex resume` reuses the persisted mode |
| `/compact` | Compact the current bound thread's context history | yes; `thread -> current thread` | admin only | admin only | no direct local equivalent |
| `/rename <title>` | Rename the current thread | yes; `thread -> current thread` form | admin only | admin only | none |
| `/archive [thread_id\|thread_name]` | Archive the current thread, or archive an explicit target | yes; `thread -> current thread` | admin only | admin only | `feishu-codexctl thread archive --thread-id/--thread-name` |
| `/detach` | Stop the current chat from receiving Feishu push for the current thread while keeping the binding bookmark | not from the root; exposed as a button on `chat -> current chat` | admin only | admin only | `feishu-codexctl binding detach <binding_id>`; thread scope is `feishu-codexctl thread detach ...` |
| `/attach [binding\|thread\|service]` | Restore Feishu push for the current chat, current thread, or current instance | not a root help command; primary entry is usually a reset result card | admin only | admin only | `feishu-codexctl binding/thread/service attach ...` |
| `/cancel` | Cancel the current execution | no; primary entry is the execution-card button | admin only | admin only | none |

### 2.2 Runtime and Identity

| Command | Purpose | Reachable from `/help` | P2P | Group | Closest local counterpart |
| --- | --- | --- | --- | --- | --- |
| `/reset-backend` | Preview and reset the current instance backend | yes; `runtime` page | admin only | admin only | `feishu-codexctl service reset-backend` |
| `/permissions [read-only\|default\|full-access]` | Set approval policy and sandbox together | yes; `runtime` page | admin only | admin only | none |
| `/model [name\|auto]` | Set the current Feishu session's turn-time model override | yes; `runtime` page | admin only | admin only | none |
| `/approval [untrusted\|on-request\|never]` | Set approval policy | yes; `runtime` page | admin only | admin only | none |
| `/sandbox [read-only\|workspace-write\|danger-full-access]` | Set sandbox policy | yes; `runtime` page | admin only | admin only | none |
| `/collab-mode [default\|plan]` | Set collaboration mode for future turns in the current Feishu session | yes; `runtime` page | admin only | admin only | none |
| `/whoami` | Show the caller's identity | yes; `identity` page | anyone | unsupported | none |
| `/bot-status` | Show bot identity and config probe results | yes; `identity` page | anyone | admin only | none |
| `/init <token>` | Initialize admins and `bot_open_id` | yes; `identity` page form | anyone | unsupported | `feishu-codex config init-token` only shows the token |
| `/debug-contact <open_id>` | Debug contact-name resolution | no | admin only | unsupported | none |

### 2.3 Group-only

| Command | Purpose | Reachable from `/help` | P2P | Group | Closest local counterpart |
| --- | --- | --- | --- | --- | --- |
| `/group` | Show whether the current group is activated | yes; `group` page | unsupported | admin only | none |
| `/group activate` | Activate the current group | yes; `group` page | unsupported | admin only | none |
| `/group deactivate` | Deactivate the current group | yes; `group` page | unsupported | admin only | none |
| `/group-mode` | Show the current group working mode | yes; `group` page | unsupported | admin only | none |
| `/group-mode assistant` | Switch to `assistant` | yes; `group` page | unsupported | admin only | none |
| `/group-mode mention-only` | Switch to `mention-only` | yes; `group` page | unsupported | admin only | none |
| `/group-mode all` | Switch to `all` | yes; `group` page | unsupported | admin only | none |

## 3. Commands Intentionally Not on the Main Help Path

These remain plain-text or result-card entry points rather than first-class root help buttons:

- `/commands`
- `/h`
- `/pwd`
- `/cancel`
- `/attach`
- `/debug-contact`

`/detach` is also not a root help command, but it is intentionally exposed as a button on the “current chat” help page because it is still a comprehensible session-scoped push toggle.

## 4. Result-card Buttons

These are part of the formal Feishu user surface and must be maintained together with slash commands:

- execution card: `Cancel Execution`
- `/threads` list card: `Resume/Current`, `Archive`, `More`, `Collapse`
- `/profile` / `/memory` / `/reset-backend` result cards: `Apply And Reset Backend`, `Force Apply And Reset Backend`, `Attach Current Thread`, `Attach Current Instance`, `Keep Detached`
- `/model` / `/permissions` / `/approval` / `/sandbox` / `/collab-mode` cards: turn-time runtime-setting toggle buttons
- approval / extra-input cards: their request-type-specific allow / deny / submit buttons

## 5. Boundary

- `feishu-codex` owns install, instance, and service lifecycle. It is not the Feishu chat command surface.
- `feishu-codexctl` owns local inspection and management of bindings, threads, and services. It is not a second frontend.
- `fcodex` is the local live-thread continuation entry point.

If any Feishu command is added, removed, renamed, or moved in `/help`, or if button entry points or permission boundaries change, this file must be updated with the code.
