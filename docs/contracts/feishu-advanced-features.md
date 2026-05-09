# Feishu Advanced Codex Features Contract

Chinese original: `docs/contracts/feishu-advanced-features.zh-CN.md`

This document defines the Feishu-side contract for the currently exposed
upstream Codex advanced features:

- `compact`
- `skills`
- `plugins`

It answers:

- which state layer each feature operates on
- which changes affect the current thread versus only future turns
- which upstream advanced features are intentionally not exposed in Feishu

## 1. Goal

The Feishu surface does not mirror the full upstream TUI advanced UI.

The current contract exposes only:

- the smallest user-understandable loop that is worth using in Feishu
- entry points that match this repository's state boundaries
- explicit support / non-support boundaries

## 2. `/compact`

`/compact` is an explicit action on the **currently bound thread**.

Its contract is:

- it applies only to the currently bound thread
- it does not accept extra arguments
- it is rejected while a turn is running
- it is rejected when no thread is currently bound
- it is rejected when the current thread is not loaded in the current backend,
  with guidance to `/attach` or send a plain message first

Feishu **does not** implicitly attach or resume a thread just to run
`/compact`.

That is intentional:

- `compact` is a thread-scoped explicit mutation
- it should not silently change Feishu runtime or backend residency state
- fail-closed behavior is clearer than hidden recovery side effects

## 3. `/skills`

`/skills` operates on the **skills configuration surface visible from the
current working directory**.

Its contract is:

- show the skills visible from the current directory
- show each skill's scope, path, and enabled state
- allow enabling or disabling a skill
- make the change effective for future turns

It is not:

- a thread-private setting
- a backend-reset surface
- a skill install or uninstall surface

The Feishu implementation intentionally force-reloads the current-directory
skills view so the card stays close to on-disk reality.

## 4. `/plugins`

`/plugins` operates on the **plugins visibility and configuration surface
visible from the current working directory**.

It has two layers:

### 4.1 `/plugins`

Without arguments, `/plugins` must provide:

- a marketplace overview for the current directory
- an overview of currently installed visible plugins
- copyable / referenceable `plugin_id` values

### 4.2 `/plugins <plugin_id>`

With a `plugin_id`, it must provide:

- detail for that plugin
- whether it is installed and enabled
- summaries of related skills, hooks, apps, and MCP servers

If the plugin is already installed, Feishu may also:

- enable it
- disable it

Those changes apply to future turns.

## 5. Plugin Capabilities Intentionally Not Exposed

Feishu currently does **not** expose:

- plugin install
- plugin uninstall
- marketplace add/remove/update
- plugin sharing
- auth-driven plugin flows

Why:

- these actions have heavier side effects
- their state model is more complex
- they do not fit the normal Feishu daily command path

## 6. Agents / Subagents

Feishu currently does not expose a dedicated agents / subagents inspection or
control page.

That is not because upstream lacks the concept. It is because:

- the current app-server request surface does not offer a stable agent-view API
  that maps cleanly onto Feishu cards
- forcing subagent state into the main execution card would add significant
  maintenance complexity

So the current formal contract is:

- natural-language prompts may still cause the model to use subagents under the
  upstream tool contract
- Feishu does not currently expose a separate agents command surface

## 7. Help-Navigation Placement

The formal Feishu navigation placement is:

- `/compact`
  - `Thread -> Current Thread`
- `/skills`
  - `Advanced`
- `/plugins`
  - `Advanced`

If these advanced-feature commands are added, removed, renamed, moved to a
different state layer, or reassigned to a different help page, this document
must be updated with the code.
