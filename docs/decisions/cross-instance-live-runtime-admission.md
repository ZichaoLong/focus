# Cross-Instance Live Runtime Admission

Chinese original: `docs/decisions/cross-instance-live-runtime-admission.zh-CN.md`

See also:

- `docs/decisions/shared-backend-resume-safety.md`
- `docs/contracts/runtime-control-surface.md`
- `docs/contracts/local-command-and-thread-profile-contract.md`
- `docs/architecture/fcodex-shared-backend-runtime.md`

## 1. Status

This document records the target contract agreed for the next rollout.

Until implementation lands, current shipped behavior is still defined by the
existing formal contracts and code. This document is the design decision that
the next implementation round should converge to.

## 2. Problem

The current machine-level `ThreadRuntimeLease` is not strong enough to be the
only cross-instance safety gate.

Reason:

- upstream app-server keeps a thread loaded for about 30 minutes after the last
  subscriber unsubscribes
- a later `thread/resume` may reuse that already-loaded in-memory thread
- therefore `lease == none` does not imply `backend == notLoaded`

That creates a real stale-loaded risk across instances: one instance can keep a
thread loaded in memory after another instance has already advanced persisted
history.

## 3. Decision

### 3.1 Product contract

- thread visibility remains global
- live continuation is instance-exclusive
- cross-instance migration is `cold migration only`
- no cross-instance hot takeover is supported

### 3.2 Admission model

Cross-instance-sensitive paths must use two layers:

1. `global loaded gate`
   - before attach / resume across instances, the system must verify whether
     another running instance still reports the target thread as loaded
   - if another running instance still reports it as loaded, reject
   - if the system cannot verify that fact, reject
2. atomic `ThreadRuntimeLease` claim
   - after the loaded gate passes, the instance must still acquire the machine
     level runtime lease before continuing
   - this is kept to prevent concurrent resume races between two instances that
     both observe a not-loaded state at nearly the same time

### 3.3 Meaning of `ThreadRuntimeLease`

`ThreadRuntimeLease` stays as an internal coordination primitive, but its role
is narrowed:

- it is not the sole source of truth for cross-instance safety admission
- it is the atomic machine-level claim that prevents racing writers
- it carries holder metadata such as `service` vs `fcodex`

User-facing mental model should prefer:

- "another running instance still has this thread loaded"
- not "another instance owns the lease"

## 4. Attach Contract

### 4.1 Binding / thread / service attach

All attach-style operations must obey the same loaded gate.

- `binding attach` is admitted only if the target thread passes the gate
- `thread attach` is admitted only if the target thread passes the gate
- `service attach` is an instance-level batch restore, but failure is decided at
  thread granularity

### 4.2 Service attach result shape

`service attach` should behave as:

- batch restore all detached bindings in the current instance
- group work by thread
- each thread is either fully restored for this instance or fully blocked
- partial success across different threads is allowed
- blocked threads must be listed explicitly with reasons

This means:

- instance-level batch restore
- thread-level fail-close
- result-level partial success

## 5. Operational Implications

- no automatic cross-instance continuation when another running instance may
  still hold a loaded in-memory copy
- source-instance reset, idle unload, or explicit cold migration workflow is
  acceptable
- convenience must lose to fail-close when the loaded state cannot be proven

## 6. Scope For Next Implementation Round

The next rollout should apply this decision to:

- Feishu attach paths
- detached binding auto-attach / re-attach paths
- local `fcodex resume` routing where cross-instance loaded conflicts matter
- status / rejection text so users see "loaded elsewhere" rather than lease-only
  language
