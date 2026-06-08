# Scheduled Resume and Synthetic Prompt Contract

Chinese original: `docs/contracts/scheduled-prompts.zh-CN.md`

This document defines the current minimal contract for "continue the same
Feishu-bound thread at a future time".

It covers three layers:

- service control plane: `binding/submit-prompt`
- local CLI: `feishu-codexctl prompt send`
- Linux `systemd --user` managed skill: `feishu-scheduled-prompts`

## 1. Goal

The supported product shape is not a built-in scheduler subsystem. It is:

- safely synthesize one new prompt turn for an existing Feishu binding at a
  future time
- keep using the same `feishu-codex` instance backend
- preserve the existing running-turn / attach / interaction / live-runtime
  safety boundaries

Explicitly out of scope today:

- a persistent scheduler / job queue
- cross-binding prompt fan-out
- starting a second bare Codex backend to recover the same thread

## 2. `binding/submit-prompt`

The control plane exposes:

- `binding/submit-prompt`

Its contract:

- the scope is **binding**, not thread
- the minimum input is:
  - `binding_id`
  - `text` or `input_items`
- optional inputs:
  - `actor_open_id`
  - `synthetic_source`
  - `display_mode`
- the target binding must already exist; when it does not exist, the control
  plane must fail closed rather than creating a new binding implicitly
- the target binding may currently have no thread; this means “an existing
  binding with no current thread”, and it follows the normal prompt-entry
  semantics of "create thread first, then start turn"
- the target binding may currently be `detached`; when attach / resume
  preflight succeeds, it follows the normal binding recovery path
- all write admission checks must reuse the existing safety boundary rather than
  bypass it

Return contract:

- `started=true`
  - the turn was started successfully
- `queued=true`
  - the target binding is currently executing, and the synthetic prompt was
    admitted into that same owner binding's local FIFO
  - `queue_position` should be returned
  - when dequeued, the prompt must read the binding's latest next-turn settings
    such as `/model`, `/effort`, `/approval`, `/permissions`, and
    `/collab-mode`
- `started=false`
  - the action fail-closed or startup failed
  - `reason` must be returned; `reason_code` should be returned when available

## 3. `feishu-codexctl prompt send`

The local CLI exposes:

- `feishu-codexctl [--instance <name>] prompt send --binding-id <binding_id> (--text <text> | --text-file <file>)`

Its contract:

- this is the formal local entry for `binding/submit-prompt`
- the default is `display_mode=silent`
- it may additionally accept:
  - `--synthetic-source`
  - `--display-mode silent|announce`
  - `--actor-open-id`
- when the target binding is not writable:
  - the exit code must be non-zero
  - the refusal reason must be printed
- when the only conflict is that the target binding's own current turn is
  running, the prompt is not considered unwritable; it enters the same owner
  binding's local FIFO and the current instance starts it after the active
  execution ends

## 4. `display_mode`

Only two modes exist today:

- `silent`
  - do not emit an extra "this was system-triggered" chat message
  - normal execution / terminal cards still follow the existing runtime behavior
- `announce`
  - send one short trigger notice to the target chat before starting the
    synthetic prompt

There is no more complex message choreography contract yet.

## 5. `feishu-scheduled-prompts` skill

The repository now ships one Linux-only managed skill:

- `feishu-scheduled-prompts`

Its contract:

- it manages `systemd --user` timer/service units
- when the timer fires, it still routes back through `feishu-codexctl prompt send`
- it does not call a standalone Codex SDK helper directly
- it does not depend on a Feishu message loopback trick

The helper currently exposes:

- `create`
- `list`
- `show`
- `remove`
- `run-now`

These helpers are not Feishu slash commands and not a formal cross-platform
public product surface. They are the Linux short-term scheduling shell.

## 6. Safety Boundary

The following are normative:

1. a scheduled task is only "start one new prompt at a future time"
2. scheduled work may not bypass interaction / attach / running-turn admission
3. only a running-turn conflict from the current owner binding itself may enter
   the local in-memory FIFO; cross-binding conflicts, interaction-owner
   conflicts, and attach/preflight failures must still fail closed
4. there is no automatic cross-instance live-runtime takeover
5. the Linux skill is only a scheduling shell; the real execution surface
   remains `binding/submit-prompt`

## 6.1 Owner Binding FIFO

Normal Feishu prompts, `feishu-codexctl prompt send` / `binding/submit-prompt`,
and `/compact` share the same owner-binding admission semantics:

- if the current binding is idle, execute immediately
- if the current binding has an active execution, only that same owner binding
  may enqueue follow-up work
- the queue is process-local memory only; it does not promise restart recovery,
  listing, cancellation, or cross-binding scheduling
- when dequeued, `/compact` establishes a local execution anchor before calling
  upstream `thread/compact/start`, so a following prompt cannot pass through it
- `/model`, `/effort`, `/approval`, `/permissions`, and `/collab-mode` do not
  queue; they update binding-wise next-turn settings immediately, and later
  dequeued prompts read the latest settings

## 7. Platform Boundary

The only formal short-term scheduling implementation today is
`systemd --user`.

Therefore:

- the `feishu-scheduled-prompts` helper is only promised on Linux
- there is no equivalent managed timer helper contract yet for macOS or Windows

If a future cross-platform scheduler product surface is added, this document
must change with the code.
