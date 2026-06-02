# Feishu `/help` Navigation Contract

Chinese original: `docs/contracts/feishu-help-navigation.zh-CN.md`

This file defines only the navigation contract for `/help` and `/commands`.

## 1. Home goal

`/help` is not a full documentation site and not a flat dump of every command.

Its job is:

1. show a compact current-state summary
2. route the user into fixed workspaces
3. keep low-frequency actions on lower-level pages or result cards

## 2. Fixed home workspaces

The home must expose exactly these six workspaces:

- `Start`
- `Thread Settings`
- `Turn Settings`
- `Connection Status`
- `Group Settings`
- `More`

The home summary must include at least:

- current working directory
- current thread
- current push state
- current turn-setting summary

## 3. Page contracts

### 3.1 Start

Owns:

- `/new`
- `/threads`
- `/resume`
- `/cd`

Its body should remind the user that:

- the same thread may be observed from multiple endpoints, but a live turn has
  only one interaction owner
- local continuation of the same live thread uses `fcodex resume <thread_id|thread_name>`

### 3.2 Thread Settings

Owns:

- `/goal`
- `/compact`
- `/archive`
- the rename form

Its body should remind the user that:

- thread creation, resume, and browsing belong to `Start`
- there is no longer a project-owned profile or thread-memory control surface here

### 3.3 Turn Settings

Owns:

- `/permissions`
- `/model`
- `/effort`
- `/approval`
- `/collab-mode`
- `/last text`

Its body should remind the user that:

- these settings affect future turns of the current Feishu binding
- `/permissions` is the recommended first entry

### 3.4 Connection Status

Owns:

- `/status`
- `/preflight`
- `/detach`
- `/attach`
- related attach subpages

### 3.5 Group Settings

Owns:

- `/group`
- `/group activate`
- `/group deactivate`
- `/group-mode`

### 3.6 More

Owns:

- `/commands`
- `/whoami`
- `/bot-status`
- `/init`
- `/reset-backend`
- `/debug-contact`

## 4. Back-button rules

- first-level workspace pages must expose `Back Home`
- lower-level pages must expose only `Back`
- every back button occupies its own row

## 5. Compatibility entries
