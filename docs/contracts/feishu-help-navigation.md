# Feishu Help Navigation Contract

Chinese original: `docs/contracts/feishu-help-navigation.zh-CN.md`

This file defines only the `/help` and `/commands` navigation contract.

It answers:

- which topic pages `/help` must expose
- what each page is responsible for
- which commands are intentionally not on the main help path

## 1. Goal

`/help` is not a second documentation site and not a flat dump of every command.

Its job is progressive disclosure:

1. group actions by the problem the user is solving now
2. enter the relevant action through buttons or forms
3. leave advanced recovery / debugging actions to result cards or plain-text commands

## 2. Root Navigation

The `/help` root card must expose exactly five topics:

- `Current Chat`
- `Group`
- `Thread`
- `Runtime`
- `Identity`

They correspond to:

- `Current Chat`
  - `/status`
  - `/preflight`
  - `/cd`
- `Group`
  - `/group`
  - `/group-mode`
  - group-collaboration boundaries
- `Thread`
  - `/threads`
  - `/new`
  - `/resume`
  - the current-thread page
- `Runtime`
  - `/permissions`
  - `/model`
  - `/effort`
  - `/approval`
  - `/sandbox`
  - `/collab-mode`
  - `/reset-backend`
- `Identity`
  - `/whoami`
  - `/bot-status`
  - `/init`

## 3. Page Contracts

### 3.1 Current Chat

Must provide:

- a `/status` button
- a `/preflight` button
- a dynamic push-toggle action
- a `/cd` form entry

It does not need to expose `/pwd`.

The push-toggle action must follow current binding state:

- show `/detach` when the current binding is `attached`
- show `/attach` when the current binding is `detached`

### 3.2 Thread

Must provide:

- `/threads`
- `/new`
- a `/resume` form
- `/compact`
- a `Current Thread` secondary page

### 3.3 Current Thread

Must provide:

- `/profile`
- `/memory`
- `/compact`
- `/archive`
- a `Rename` form entry

Its body must also state:

- push toggling belongs to the `Current Chat` page
- if the goal is re-profiling, `/profile` is the preferred path
- local advanced debugging may use `feishu-codexctl thread detach --thread-id <thread_id>`

### 3.4 Runtime

Must provide:

- `/permissions`
- `/model`
- `/effort`
- `/approval`
- `/sandbox`
- `/collab-mode`
- `/reset-backend`

Its body must also state:

- after reset, `/attach [binding|thread|service]` can restore push delivery
- the more common entry point is the attach buttons on the reset result card

### 3.5 Identity

Must provide:

- `/whoami`
- `/bot-status`
- an `/init` form entry

And it must clearly state:

- `/whoami` and `/init` are P2P-only

## 4. Role of `/commands`

`/commands` is a plain-text command index.

It must:

- list common commands in the same grouping as `/help`

It must not become:

- a second navigation card system
- an exhaustive dump of every debugging command

## 5. Commands Intentionally Off the Main Help Path

These are not required to be reachable directly from the `/help` root card:

- `/commands`
- `/h`
- `/pwd`
- `/cancel`
- `/attach`
- `/debug-contact`

Why:

- `/commands` and `/h` are index / alias surfaces
- `/pwd` has effectively been weakened by no-arg `/cd`
- `/cancel` already has a primary execution-card button
- `/attach` is a recovery surface and is better surfaced from reset result cards
- `/debug-contact` is an admin debugging command

The `Current Chat` page must still make the session-scoped push toggle visible, even though neither `/detach` nor `/attach` is a root help command.

## 6. Button Permissions

The help card itself may be browsed in groups, but any button or form that mutates state must still be permission-checked by the command handler.

So:

- seeing navigation is not the same as being authorized to execute it
- final permission enforcement belongs to backend command handling, not to card visibility alone

If any help page, button, or form entry is added, removed, or renamed, or if the help-page placement of `compact` changes, this file must be updated with the code.
