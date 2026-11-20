# Focus Web Browser Update Contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-update.zh-CN.md`.

This contract defines the source, preflight, confirmation, and restart boundary for
updating the Focus installation from the browser. It is not in-process hot replacement
and it does not update the Codex app-server or CLI.

## 1. Source and input

- The update source is machine-level durable configuration. The default is
  `https://github.com/ZichaoLong/focus.git` on the fixed `main` branch.
- Browser input cannot contain a workspace path, shell command, or local file path.
  Git credentials come from the host's credential helper, deploy key, or SSH agent,
  not from the URL.
- Changing the source requires explicit confirmation. Each check accepts a newly entered
  commit; an empty value resolves remote `refs/heads/main` once and then pins the build
  to the complete 40-character SHA.
- The only targets are `main` and `stable`. `main` uses the machine-level Git source and
  builds the selected source; `stable` downloads the latest formal Focus GitHub Release
  bundle, ignores the custom Git source, and does not rebuild Web assets. Stable does not
  accept a commit input.

## 2. Check and preflight

`POST /api/update/check` carries a `target` and an optional `commit` for `main`. It creates
one bounded background check and does not change the current installation or service.
The `main` path clones/fetches the exact commit, builds Web production assets and a local
bundle; the `stable` path downloads and validates the formal Release bundle. Both complete
before any shutdown:

- Git, Node/npm, Python, package-index, proxy, and certificate requests;
- pip installation and `pip check` in a staging managed environment;
- a complete wheelhouse download so the later install can run with `--no-index`
  and cannot unexpectedly start a second network request;
- free bytes, inodes, temporary-directory, and bundle-staging checks; and
- Focus wheel, dependency-lock, and source-revision consistency checks.

Python preflight reads the target wheel's complete-runtime policy. Missing runtimes are downloaded into this operation's
staging tree, verified for interpreter and standard-library ownership, then atomically published into the shared `.python`
cache. Interrupted downloads remain operation-owned; they must not overwrite, delete or repair an existing shared runtime
in place. Dependency downloads, offline trial
installation, `pip check`, core-module imports, and CLI startup checks all use the
target Python. Its base interpreter and standard library must belong to Focus;
compatibility with the old environment is not sufficient evidence. Only then is
the operation `ready`, with `python_runtime` in the existing `preflight` object.
Runtime-cache preparation failures do not change the old service.

At the start of each check, the updater resolves one Node/npm toolchain and reuses
that validated pair for every Web command in the check. Resolution prefers an
explicit stable toolchain path (`FOCUS_NODE_BIN`/`FOCUS_NPM_BIN`) and the updater
PATH, then stable fnm/nvm default aliases; it never reads or executes shell startup
files or blindly chooses the highest installed version. The selected paths, versions,
and source are recorded in the preflight journal. Apply uses the already prepared
offline bundle and does not resolve Node/npm again.

The independent updater forwards the deployment user's explicit Git/SSH, HTTP(S)/SOCKS
proxy, pip/npm index, and certificate settings together with the Focus roots. It does not
forward arbitrary service or provider/API credentials into source-controlled build hooks,
so preflight uses the same package and network authorities as that user's installation.

A failure is recorded as `failed` while the old service continues running. A successful
check is `ready` for one exact target/commit and has no implicit fallback.

`checking` and `applying` are durable long-running states; they do not mean that the
updater's admission HTTP request has finished the work. The browser must keep polling
and show the current target, stage message, operation id, and latest recorded time. While
either state is active, checking another target, changing the source, and applying a
different operation are disabled. Closing Server update in Settings does not cancel the operation;
reopening it reads the same journal. Multiple browser tabs can still race, so the backend
single-flight refusal remains required. When that refusal is received, the browser reads
the current status and explains that another operation is active instead of submitting a
second check.

Preparation offers **Cancel preparation**, retaining the separate main/stable check buttons.
`POST /api/update/cancel` accepts only exact `{operation_id}` under the existing authentication, same-origin, CSRF and
document admission. Cancellation targets only that ID's check unit; it does not stop Focus services or cancel an applying
or uncertain installation. To cover a race with check completion, cancellation also admits the same unapplied `ready`
operation. An operation already admitted to apply rejects cancellation.

Under the same journal lock, cancellation first records `cancelling`, fencing late worker ready/failed publication and apply,
then asks systemd to stop the entire check cgroup. Check units use `KillMode=control-group` and a bounded stop timeout,
including Git/npm/pip/uv descendants that create their own sessions. The browser shows cancellation progress and keeps
polling. New checks, source changes and apply remain blocked until the unit is confirmed inactive/failed with no queued systemd job and this operation's
staging is removed. Only then does the journal become `cancelled`. Published shared Python runtimes and the installed
Focus are preserved.

Repeated cancellation of the same ID creates no second task; an old ID cannot cancel a newer check. An uncertain stop
request or unit state, or failed cleanup, leaves the operation `cancelling`, retains staging and admission blocking, and
reports an error with explicit cancellation retry. A lost HTTP response triggers journal reads, never automatic POST replay
or a new check. Closing the panel, reloading the page or restarting the service continues observing the same journal.

The updater persists a bounded fixed `phase`, phase-start time, last-real-progress time,
and optional byte progress in the journal. Stable download phases report received/total
bytes when the response supplies a size. Raw Git/npm/pip output is not projected into the
browser or a public journal, preventing credential-bearing URLs from leaking. Phase timing
is diagnostic evidence and must not be used to invent percentages for unreported build or
dependency work.

If a status read temporarily fails, the browser may continue polling at a bounded cadence but must mark
the last known status stale; a network error is not evidence that the operation ended. An
`unknown` result blocks new checks and applies until an operator inspects the service and
journal on the host.

If a check is recorded as `unknown` but its check transient unit is definitively inactive
and installation never started, a new explicit check may replace that stale operation.
An `unknown` apply operation remains blocked for manual inspection and cannot be replaced
by a new check.

## 3. Apply, restart, and result

Settings has four top-level sections. Expand About Focus Web inside Server update to inspect the installed build and Codex app-server identity. The update section identifies the instance, target and machine-wide restart. Explicit confirmation submits the full operation ID captured when opening the dialog. Copy is optional and the ID remains selectable.

The apply transient unit runs from the `preflight-venv` containing the tested
target Focus, not the production `.venv` it will replace. Before shutdown it
revalidates the bundle digest, wheelhouse, dedicated runtime, and execution
environment. Production `.venv` is created with that same target Python; apply
does not download runtimes or resolve another interpreter. An old `ready` record
without dedicated-Python preflight evidence requires a fresh check.

The first browser update of a legacy installation still runs the old updater: it
installs the new code while preserving the original Python. New-version startup
therefore does not require migration to have finished. After reloading the page,
check and apply the same full commit again; the new updater performs migration.
Do not add network migration to service startup, bootstrap-install, or the old
updater's stopped-service phase. After the second update, cold starts and later
updates rely on the dedicated Python rather than the original bootstrap Python.

`POST /api/update/apply` requires the ready operation id (shown separately and copyable in
the browser) and a second user confirmation.
On Linux Focus starts an independent updater in a transient systemd user unit (other
platforms fail closed before shutdown). The existing managed-install transaction
proves every instance idle, closes ingress, stops services, installs the validated bundle,
starts instances that were running, and waits for service status. The update affects every
Focus instance on the machine.

Preflight failure does not stop the service. A failure after shutdown does not automatically
roll back or retry an unknown result; the journal records `failed` or `unknown`, and a
stopped service may remain offline until an operator checks it. A successful operation is
`succeeded`; after the service returns, the browser must perform a full document reload to
consume the new static assets.

## 4. Wire and lifecycle

`GET /api/update` returns the machine-level source and operation journal, including target
and operation id. Source, check, cancel
and apply are authenticated same-origin, CSRF-protected user actions and renew the current
Web session. The journal does not own thread, writer, approval, or recovery authority.
Transport loss during the update is a service lifecycle effect, not proof of installation
success.

## 5. Maintenance closure

Changes to update-source behavior, status vocabulary, preflight boundaries, or the install
transaction must update this contract, its Chinese canonical peer, the wire catalog and
generated projection, Gateway, browser decoder/UI, and focused tests together.
