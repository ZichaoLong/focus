# Runtime Settings Fact Sources and Effectivity Boundaries

Chinese original: `docs/contracts/runtime-settings-fact-sources.zh-CN.md`

This document provides the shared analysis frame used to separate:

- what exactly was resolved at write time
- which layer becomes the persisted fact source after the write
- which upstream boundary actually consumes the value
- whether a read-side surface is showing intent, a snapshot, or live truth

## 1. The current three setting families

The project now separates runtime-related settings into three families:

1. **instance startup baseline**
   - currently only the managed backend startup profile
2. **thread-wise next-load state**
   - currently only thread memory mode
3. **frontend-owned next-turn settings**
   - model
   - effort
   - approval
   - permissions
   - collaboration mode

Those families must not be read, written, or explained as if they were the
same thing.

## 2. Shared question list

For any setting, the system should answer separately:

1. write-time resolution source
2. post-write persisted source
3. application boundary
4. read-side view
5. whether it has already taken effect

It should also mark, when needed:

- whether the value is still provisional / pending

## 3. Side-by-side table

| Setting family | Persisted source | Official application boundary | Primary read-side |
| --- | --- | --- | --- |
| instance startup profile | instance config `managed_startup_profile` | managed backend start / restart after reset | `/profile`, `/status`, local instance diagnostics |
| thread-wise memory | `ThreadMemoryModeStore`; pending seed when needed | `thread/start`, `thread/resume` | `/memory`, thread status, resume diagnostics |
| binding-wise next-turn | persisted runtime settings on the current binding | `turn/start` | `/status`, turn-settings cards, preflight |

## 4. Startup profile

### 4.1 Write-time resolution source

- the target value is resolved as a usable profile-v2 name from shared
  `CODEX_HOME`

### 4.2 Post-write persisted source

- instance config field `managed_startup_profile`

### 4.3 Application boundary

- managed backend startup
- managed backend restart after reset

### 4.4 Read-side view

- `/profile` and `/status` read instance-level intent
- that is not the thread-wise truth of the current live thread

## 5. Thread-wise memory

### 5.1 Write-time resolution source

- input is normalized into a legal memory-mode enum

### 5.2 Post-write persisted source

- normal case: `ThreadMemoryModeStore`
- provisional case: pending threadwise seed

### 5.3 Application boundary

- existing thread: `thread/resume`
- new thread: the startup-seed path of `thread/start`

### 5.4 Read-side view

- `/memory` primarily reads persisted intent
- status pages may additionally show a load-time observed value, but must not
  pretend it is always-available live truth

## 6. Binding-wise next-turn settings

### 6.1 Write-time resolution source

- commands or card actions from the current Feishu binding
- `auto` means "do not explicitly override", not "write thread-wise state"

### 6.2 Post-write persisted source

- the persisted runtime settings of the current binding

### 6.3 Application boundary

- main path: `turn/start`

There is one narrow implementation exception today:

- for approval / permissions, some flows that "cold-resume first and then
  continue a goal" also carry a one-shot correction during resume, so the first
  resumed round does not silently fall back to the wrong default

That correction:

- does not change the fact source; it is still binding-wise next-turn state
- does not turn approval / permissions into thread-wise state

### 6.4 Read-side view

- `/status` and related setting cards read the binding's persisted intent
- if a live runtime was changed by another upstream frontend, the project does
  not promise lossless readback of every live field

## 7. Pending / provisional

The system must explicitly admit a provisional stage when:

- a thread was just created and is not yet stably materialized
- the result of `thread/start` is unknown
- backend reset is still replacing a provisional thread

Temporary seeds are allowed there, but they must not be represented as formal
thread/store truth too early.

## 8. One guiding rule

If the question is:

- "what will the next backend start use?"

look at the startup profile first.

If the question is:

- "what will the next resume of this thread use?"

look at thread-wise memory first.

If the question is:

- "what will the next turn from this Feishu chat use?"

look at the binding-wise next-turn settings first.
