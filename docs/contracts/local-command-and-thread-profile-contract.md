# Local Commands and Runtime-Settings Contract

Chinese original:
`docs/contracts/local-command-and-thread-profile-contract.zh-CN.md`

Note: this file keeps its historical filename, but the current focus is no
longer a "thread profile". It is now the boundary document between local entry
points and the three setting families.

## 1. Three local entry points

### 1.1 `feishu-codex`

Owns:

- install and upgrade
- service lifecycle
- instance management
- project-level helper actions

Does not own:

- entering the Codex TUI
- directly continuing a live thread locally

### 1.2 `feishu-codexctl`

Owns:

- viewing instance / binding / thread / service state
- limited local management actions
- troubleshooting attach / detach / backend issues

Does not own:

- persisting Feishu-side binding-wise next-turn settings
- acting as a second Feishu frontend

### 1.3 `fcodex`

Owns:

- entering the local Codex TUI
- resuming or attaching to a live thread
- acting as a local frontend that talks to the backend

It is not:

- a mirror of the Feishu command surface
- a service-management CLI

## 2. The project's current three setting families

### 2.1 Instance startup profile

- target object: managed backend instance
- Feishu entry points: `/profile`, `/profile-clear`
- local semantics: mutate backend startup baseline, not a thread's persisted
  restore settings

There is currently no local `fcodex` command that is fully equivalent to the
Feishu `/profile` contract.

### 2.2 Thread-wise next-load memory

- target object: thread
- Feishu entry point: `/memory`
- local observe/manage path: `feishu-codexctl thread memory ...`
- local restore path: `fcodex resume <thread>` reuses the persisted memory mode

### 2.3 Binding-wise next-turn settings

- target object: Feishu binding
- Feishu entry points: `/model`, `/effort`, `/approval`, `/permissions`,
  `/collab-mode`
- local `fcodex` / upstream TUI keep their own local state; they are not
  automatically merged with Feishu binding persistence

## 3. Current role of `fcodex -p/--profile`

The project no longer treats `fcodex -p/--profile` as an entry point that
rewrites thread-wise persisted profile state.

Its current role is:

- an upstream / local-TUI launch hint or local runtime hint
- not the local mirror of Feishu `/profile`
- not something this project persists as thread-wise next-load truth

Therefore:

- Feishu `/profile` mutates the instance startup baseline
- `fcodex -p/--profile` influences the local TUI side

The project no longer promises that those two are semantically identical.

## 4. What `fcodex resume` still formally guarantees

`fcodex resume <thread_id|thread_name>` still formally guarantees:

- resolve thread identity first
- then do fail-closed routing based on live-runtime owner and loaded-gate checks
- reuse the thread's persisted memory mode during resume

It no longer formally guarantees:

- reusing some project-persisted thread-wise profile slice
- rewriting a thread's next-load profile tuple through `-p/--profile`

## 5. Relationship to upstream config

Shared `~/.codex/config.toml` remains the user config source for upstream
`codex` / app-server.

But the project's three setting families are not equivalent to "re-implementing
the whole upstream config model":

- startup profile: only the startup baseline layer of the managed backend
- thread memory: only the thread-wise memory restore contract defined here
- binding settings: only Feishu-side future-turn overrides

None of those imply:

- that this project persists every upstream config field as its own thread truth

## 6. One maintenance rule

If a new setting is to enter this project, it must first be classified as one
of:

1. instance startup baseline
2. thread-wise next-load state
3. binding-wise next-turn settings

Until that classification is explicit, it should not be stuffed into `/profile`,
`/memory`, or the existing binding-setting surfaces.
