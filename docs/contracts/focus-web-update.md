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

## 2. Check and preflight

`POST /api/update/check` creates one bounded background check and does not change the
current installation or service. It clones/fetches the exact commit into a temporary
directory, builds Web production assets and a local bundle, and completes before any
shutdown:

- Git, Node/npm, Python, package-index, proxy, and certificate requests;
- pip installation and `pip check` in a staging managed environment;
- a complete wheelhouse download so the later install can run with `--no-index`
  and cannot unexpectedly start a second network request;
- free bytes, inodes, temporary-directory, and bundle-staging checks; and
- Focus wheel, dependency-lock, and source-revision consistency checks.

The independent updater forwards the deployment user's explicit Git/SSH, HTTP(S)/SOCKS
proxy, pip/npm index, and certificate settings together with the Focus roots. It does not
forward arbitrary service or provider/API credentials into source-controlled build hooks,
so preflight uses the same package and network authorities as that user's installation.

A failure is recorded as `failed` while the old service continues running. A successful
check is `ready` for one exact commit and has no implicit fallback.

## 3. Apply, restart, and result

`POST /api/update/apply` requires the ready operation id and a second user confirmation.
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

`GET /api/update` returns the machine-level source and operation journal. Source, check,
and apply are authenticated same-origin, CSRF-protected user actions and renew the current
Web session. The journal does not own thread, writer, approval, or recovery authority.
Transport loss during the update is a service lifecycle effect, not proof of installation
success.

## 5. Maintenance closure

Changes to update-source behavior, status vocabulary, preflight boundaries, or the install
transaction must update this contract, its Chinese canonical peer, the wire catalog and
generated projection, Gateway, browser decoder/UI, and focused tests together.
