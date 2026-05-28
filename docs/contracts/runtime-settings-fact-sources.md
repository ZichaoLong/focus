# Runtime Settings Fact Sources and Effectivity Boundaries

Chinese original: `docs/contracts/runtime-settings-fact-sources.zh-CN.md`

This document defines one shared analysis frame for questions such as:

- What exactly was resolved when a setting write happened?
- After the write returns, which layer becomes the persisted fact source?
- At which official boundary will upstream actually consume the setting?
- Is a current status page reading persisted intent, a load-time snapshot, or
  live runtime truth?
- Is the value merely recorded, or has it actually taken effect?

Without separating those questions, it is easy to blur together “what was just
set”, “what the next load/turn will use”, and “what the current live runtime is
really using”.

## 1. Scope

The current project has at least two major classes of runtime-related settings:

- **thread-wise next-load state**
- **frontend-owned runtime settings**

Users may casually think of both as “settings”, but they do not share the same
fact source, application boundary, or read-back contract.

This document defines the shared frame only. It does not replace the
setting-family business contracts:

- thread-wise next-load shared rules:
  `docs/contracts/thread-next-load-settings-semantics.md`
- runtime control surface / Feishu-side runtime settings:
  `docs/contracts/runtime-control-surface.md`

## 2. Five questions and one stage marker

For any runtime setting, the system should answer these five questions
separately, and also mark whether the setting is still in a provisional stage.

### 2.1 Write-time resolution source

This is: “When the user issues a write, how is the target value resolved?”

It answers:

- what the user is really asking to set
- whether aliases, shorthands, or compound commands were expanded first
- whether the target was completed into a fully writable value before storage

### 2.2 Post-write persisted source

This is: “After the write succeeds, which layer is now the persisted fact
source?”

It answers:

- where a later read should look
- whether the write landed at thread scope, binding scope, or only in a
  temporary pending state

### 2.3 Application boundary

This is: “Which official upstream boundary will actually consume this value?”

Typical boundaries include:

- `thread/start`
- `thread/resume`
- `turn/start`

“Persisted” is not the same thing as “already consumed by a live runtime”.

### 2.4 Read-side view

This is: “What layer is a given read API, status page, or debug surface showing?”

It answers:

- next-load / next-turn intent
- a load-time observed snapshot
- or the authoritative live runtime truth

If the project has no authoritative read surface for the live truth, it must
say so explicitly.

### 2.5 Effectivity judgment

This is: “Has the setting crossed its application boundary and been consumed by
the real runtime?”

It answers:

- whether the value is only persisted intent
- whether it is now the input for the next load / turn
- or whether the current live runtime has actually consumed it

### 2.6 Provisional / pending stage

There are moments where the five questions above do not all have stable answers.

Typical cases include:

- the `thread_id` has not materialized yet
- the `thread/start` outcome is unknown
- a pending seed has not yet been promoted into formal thread-wise persisted
  state

Those moments must be marked explicitly as:

- **provisional / pending**

The system must not pretend that a temporary seed is already formal persisted
truth.

## 3. Thread-wise next-load state

The shared rules for this family live in
`docs/contracts/thread-next-load-settings-semantics.md`. This document only
places it inside the unified fact-source frame.

### 3.1 Write-time resolution source

- the target is first resolved into a thread-stable value under its own setting
  contract
- profile-style slices must resolve to a complete valid triple:
  `profile`, `model`, `model_provider`
- memory-style slices must resolve to a normalized legal enum value

### 3.2 Post-write persisted source

On a normal thread, the formal persisted source is:

- the thread-wise profile store
- the thread-wise memory store

But the provisional stage must stay distinct:

- launch seed
  - there is no `thread_id` yet
  - it is only a session-level one-shot seed
- pending threadwise seed
  - a `thread_id` now exists
  - but it is still not formal thread-wise persisted state

Only after the first successful user turn completes may that pending seed be
promoted into the formal thread-wise persisted fact.

### 3.3 Application boundary

The application boundary for this family is:

- the unloaded -> loaded thread boundary
- specifically, supported `thread/start` / `thread/resume` paths

These are not turn-time hot overrides, and they are not in-place hot patches of
an already loaded runtime.

### 3.4 Read-side view

For an **unloaded** thread:

- the thread-wise persisted store is the fact source

For a **loaded** thread:

- the live runtime is the current truth
- the only stable project read today is the
  **load-time observed snapshot** returned by `thread/start` / `thread/resume`

For a **provisional** thread:

- the launch seed / pending seed only describes a to-be-materialized intent
- it must not be treated as formal persisted thread truth

### 3.5 Effectivity judgment

These settings count as effective only when:

- the target thread is unloaded
- a later supported `thread/start` / `thread/resume` happens
- and that load actually consumes the persisted thread-wise state

Therefore:

- “written into the thread-wise store” means the next load will use it
- it does not mean an already loaded runtime was changed in place

## 4. Frontend-owned runtime settings

The Feishu-side product contract for this family lives in
`docs/contracts/runtime-control-surface.md`. This document only defines how to
reason about that family under the shared frame.

### 4.1 Write-time resolution source

On the Feishu side, writes are first resolved under the current binding's
command contract.

For example:

- `/model` resolves to a model override
- `/effort` resolves to a reasoning-effort override
- `/approval` resolves to `approval_policy`
- `/permissions` resolves to the independent runtime field `permissions_profile_id`

### 4.2 Post-write persisted source

For the Feishu surface, the persisted source is:

- the current Feishu binding's persisted settings

The service may also refresh in-memory binding runtime state, but that remains a
binding-level fact, not a thread-level fact.

### 4.3 Application boundary

These settings are mainly consumed at:

- `thread/start` initiated by the current binding
- `turn/start` initiated by the current binding

Therefore:

- if changed before a turn actually starts, they may affect that upcoming turn
- if the current turn is already running, they typically affect the next turn

### 4.4 Read-side view

The default read-side meaning of these settings is:

- the current binding's next-turn intent

For example, values shown in `/status` or the matching settings pages answer:

- “What will this Feishu chat inject when it starts the next turn itself?”

They do not answer:

- what another Feishu chat will inject
- what local `fcodex` will inject
- what the full live truth of the loaded thread currently is

### 4.5 Effectivity judgment

These settings count as consumed only when a later `thread/start` or
`turn/start` from that binding actually sends them upstream.

Therefore:

- “saved on the binding” does not mean “the currently loaded thread is already
  running under it”
- it is closer to “input intent for the next load / turn started by this
  binding”

## 5. Formal place of provisional threads and pending seeds

The repository must explicitly acknowledge that:

- a provisional stage exists
- pending seeds exist
- they are not the same thing as formal persisted thread-wise truth

Three layers must stay distinct:

1. launch seed
   - a session-level one-shot seed
   - no thread identity yet
2. pending threadwise seed
   - already bound to a `thread_id`
   - still waiting for the first successful turn to promote it
3. promoted thread-wise state
   - only this is the formal persisted truth for later restore paths

This distinction also changes the effectivity judgment:

- in provisional / pending stages, the most accurate statement is usually
  “intent has been recorded”
- it is not yet correct to say “the thread now formally carries this persisted
  state”

## 6. Practical reading rule

When the user asks “what is true now?”, the question must be classified first:

- “What was just set?”
  - read the write-time resolution source
- “What is persisted now?”
  - read the post-write persisted source
- “What will the next thread load use?”
  - read thread-wise next-load state
- “What will this Feishu chat send on its next turn?”
  - read the current binding's frontend-owned runtime settings
- “What is the live runtime using right now?”
  - prefer live runtime / load-time snapshot
  - if the current contract has no stable read surface, answer unknown instead
    of pretending the persisted value is the live truth
