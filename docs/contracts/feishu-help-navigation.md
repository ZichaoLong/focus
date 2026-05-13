# Feishu Help Navigation Contract

Chinese original: `docs/contracts/feishu-help-navigation.zh-CN.md`

This file defines only the `/help` and `/commands` navigation contract.

It answers:

- what the `/help` home must expose
- what each workspace page is responsible for
- which commands are intentionally kept off the workbench home

## 1. Goal

`/help` is not a second documentation site and not a flat dump of every command.

Its job is still progressive disclosure:

1. show a compact current-state summary first
2. let the user enter a fixed workspace based on what they want to do
3. keep low-frequency advanced actions on lower-level pages or result cards

## 2. Root Navigation

The `/help` root card is now a workbench, not a five-topic directory.

It must contain both:

- a status summary
- six fixed workspaces

### 2.1 Home Summary

The home summary must at least include:

- current working directory
- current thread
- current push state
- current turn-setting summary

The current turn-setting summary must use explicit labels:

- `Permissions <value> | Model <value> | Reasoning <value>`
- append `| Plan Mode` only when plan mode is enabled

In a group-chat context, when group state can be read safely, it should also include:

- whether the current group is enabled
- the current group mode

### 2.2 Fixed Workspaces

The home must expose exactly these six workspaces:

- `Start`
- `Thread Settings`
- `Turn Settings`
- `Connection Status`
- `Group Settings`
- `More`

The home itself does not carry:

- dynamic suggestion pages
- intent search
- low-frequency diagnostic forms

### 2.3 Direct Topic Entry

These direct topics are currently supported:

- `/help`
- `/help overview`
- `/help start`
- `/help thread-settings`
- `/help turn`
- `/help connection`
- `/help group`
- `/help more`

These legacy aliases must remain compatible:

- `chat`
- `thread`
- `runtime`
- `identity`

## 3. Page Contracts

### 3.1 Back Buttons

- every first-level workspace page must expose `Back Home`
- every lower-level page must expose only `Back`
- every back button must occupy its own row

### 3.2 Start

This page owns:

- `/new`
- `/threads`
- a `/resume` form
- a `/cd` form

Its body must also state:

- the same thread may be observed from multiple endpoints, but a live turn has only one interaction owner
- local continuation of the same live thread uses `fcodex resume <thread_id|thread_name>`
- local listing of current-directory threads uses `feishu-codexctl thread list --scope cwd`

### 3.3 Thread Settings

This page must provide:

- `/profile`
- `/memory`
- `/compact`
- `/archive`
- a `Rename` form
- an `Archive Target` form

Its body must also state:

- thread creation, resuming, browsing, and directory switching belong to `Start`
- direct re-profiling should prefer `/profile <name>`
- direct memory-mode changes should prefer `/memory <off|read|read_write>`

### 3.4 Turn Settings

This page must provide:

- `/permissions`
- `/model`
- `/effort`
- `/approval`
- `/sandbox`
- `/collab-mode`

Its body must also state:

- `/permissions` is the recommended first entry
- these settings affect future turns in the current Feishu session
- instance-level backend reset lives under `More -> Advanced Actions`

### 3.5 Connection Status

This page must provide:

- `/status`
- `/preflight`
- one dynamic push-toggle action
- `/attach service`
- a `More Attach Options` lower-level page

The dynamic push-toggle must follow current binding state:

- show `Pause Push` and execute `/detach` when the current binding is `attached`
- show `Resume Current Session` and execute `/attach` when the current binding is `detached`

The `More Attach Options` page must provide:

- `/attach thread`
- `/attach`

### 3.6 Group Settings

This page must provide:

- `/group`
- `/group activate`
- `/group deactivate`
- `/group-mode`

Its body must also state:

- non-admin users cannot use the bot before the group is enabled
- `all` is the highest-risk mode
- all shared-state mutations are still guarded by backend permission checks

### 3.7 More

This page must provide:

- `/whoami`
- `/bot-status`
- `/commands`
- an `Init` form
- an `Advanced Actions` lower-level page

Its body must also state:

- `/whoami` and `/init` are P2P-only

The `Advanced Actions` page must provide:

- `/reset-backend`
- a `Debug Contact` form

Submitting that form is equivalent to:

- `/debug-contact <open_id>`

## 4. Role of `/commands`

`/commands` is a plain-text command index.

It must:

- list common commands
- use the same grouping as the workbench

It must not become:

- a second navigation-card system
- an exhaustive dump of every debugging command

## 5. Commands Intentionally Kept Off the Workbench Home

These commands are not required to appear as fixed entry points on the home card:

- `/help`
- `/h`
- `/pwd`
- `/cancel`

Why:

- `/help` and `/h` are already entry surfaces
- `/pwd` has effectively been weakened by no-arg `/cd`
- `/cancel` already has a primary execution-card button

Current non-home but still reachable cases:

- `/commands` is reachable from `More`
- `/attach` is reachable from `Connection Status`
- `/debug-contact` is reachable from `More -> Advanced Actions`

## 6. Button Permissions

The help card itself may be browsed in groups, but any button or form that mutates state must still be permission-checked by the command handler.

So:

- visible navigation is not the same as execution permission
- final permission enforcement belongs to backend command handling, not card visibility alone

If any help page, button, or form entry is added, removed, renamed, or moved to a different workspace, this file must be updated with the code.
