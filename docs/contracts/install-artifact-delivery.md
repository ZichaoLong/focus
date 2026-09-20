# Focus Install Artifact Delivery Contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/install-artifact-delivery.zh-CN.md`.

This document defines the boundary among Focus sources, installable bundles,
GitHub Release channels, local builds, and explicit publication. It preserves one
verifiable installation path after generated Web production assets leave Git
history. It does not promise to deliver Python, third-party wheels, or the Codex
CLI as one offline payload.

## 1. Terms and Owners

| Fact or action | Sole owner |
| --- | --- |
| Closed bundle/channel-manifest schemas, construction, and validation | `bot/installation/install_bundle.py` |
| Stable/local-artifact selection, download, and install-transaction boundary | `bot/installation/installer.py` (with `install.py` as the public entry point) |
| Identity record for the latest successful bundle installation | `bot/installed_build_identity.py`; commit timing remains owned by `bot/installation/installer.py` |
| Isolated argv shape for installed Python modules | `bot/managed_python.py` |
| Clean Focus-wheel build and source-payload verification | `bot/installation/python_distribution.py` |
| GitHub Release validation and upload ordering | `scripts/build_support/github_publication.py` |
| Local bundle entry point | `scripts/build_install_bundle.py` |
| Current-workspace Web build, temporary local bundle, and official-installer orchestration | `scripts/install_workspace.sh` |
| Sole repository artifact-upload entry point | `scripts/publish_install_bundle.py` |
| Manual publication gate | `.github/workflows/publish-installable.yml` |
| Python declarations and lock semantics | [Python dependency-locking decision](../decisions/python-dependency-locking.md) |

A “bundle” is a ZIP file, not a directory, and must not be unpacked before it is
passed to `--artifact`. A source checkout is build input rather than installation
payload. Generated `bot/web_assets/dist/` and `build/install/` trees are ignored
local artifacts.

## 2. Closed Bundle Schema

A bundle contains exactly three regular, unencrypted, top-level ZIP entries:

- `manifest.json`;
- one Focus wheel;
- `requirements.lock`.

Directories, absolute paths, parent traversal, backslash paths, symlinks,
duplicate entries, and additional files are rejected. `manifest.json` is a strict
UTF-8 JSON object that rejects duplicate keys, unknown fields, and missing fields.
The current schema is:

| Field | Contract |
| --- | --- |
| `schema` | Exactly `focus-install-bundle` |
| `schema_version` | Integer `1` |
| `channel` | `stable` or `local` |
| `version` | Nonempty safe identifier matching the Focus wheel version |
| `build_id` | Nonempty safe identifier for this build |
| `source_revision` | Declared source revision; publication accepts a 40-character lowercase commit SHA and requires inner/outer equality |
| `files` | Exactly two records with distinct names |

Each file record allows only `name`, `role`, `size`, and `sha256`. `name` is a
top-level POSIX filename, `size` is a bounded positive integer, and `sha256` is a
lowercase SHA-256. The two roles each occur exactly once:

- `focus-wheel`: the filename ends in `.whl`; wheel metadata has the name `focus`
  and the manifest version, and the wheel contains the Focus Web production
  payload and notices;
- `python-dependency-lock`: the filename is exactly `requirements.lock`, containing
  a UTF-8 locked-requirements projection.

The validator checks archive shape, expansion limits, and every payload size and
SHA-256 before writing only the two declared payloads into an empty temporary
directory. Any mismatch rejects the whole bundle before the install transaction.

## 3. Outer Channel Manifest

Remote `stable` bundles also carry one outer channel manifest in
the same GitHub Release:

- stable: `focus-install-stable.json`;

It is another strict UTF-8 JSON object that rejects duplicate keys, unknown fields,
and missing fields:

| Field | Contract |
| --- | --- |
| `schema` | Exactly `focus-install-channel` |
| `schema_version` | Integer `1` |
| `channel` | Exactly the requested remote channel |
| `release_tag` | Exactly the containing GitHub Release tag |
| `version`, `build_id`, `source_revision` | Exactly match the inner bundle manifest |
| `bundle` | Contains only `name`, `size`, and `sha256`, identifying one ZIP asset in the same Release |

The installer cross-checks GitHub asset metadata, downloaded byte counts, the
outer SHA-256, inner/outer manifest identity, and wheel identity. The remote Release
tag must also resolve to the exact commit declared by `source_revision`. The outer
digest binds the channel descriptor to exact bundle bytes under the same repository
authority. It is not an independent signature or trust root from GitHub and HTTPS,
and this contract does not claim otherwise.

## 4. Three Installation Authorities

### Stable

With no explicit source, the installer reads the
repository's latest non-draft, non-prerelease GitHub Release and requires exactly
one stable channel manifest plus its referenced bundle. Removing an optional
leading `v`, the stable Release tag equals the wheel version and resolves to the
bundle's `source_revision`. Stable bundle and channel-manifest assets are immutable;
publication rejects an existing name with different bytes.

Stable publication uses an already-created formal Release. If the latest Release
has no bundle, the installer does not fall back to checkout sources or an older Release.

### Local Artifact

`--artifact PATH` uses the explicitly selected bundle ZIP without contacting
GitHub or requiring an outer channel manifest. It still validates the complete
inner schema, every payload byte, wheel identity, and Web payload. `local` is the
default developer-build shape. A separately downloaded stable ZIP can
also be installed through `--artifact`, but doing so does not reinterpret its
channel.

There is no implicit fallback among the two authorities. A caller repairs the
selected source or explicitly chooses another one.

## 5. Install Transaction and Network Boundary

Remote Release lookup, channel-manifest and bundle download, and complete validation
of either a local or remote bundle all finish before Focus acquires offline-maintenance
admission, stops a service, or mutates the managed `.venv`. A preflight failure
leaves the current installation and service state unchanged.

Only after validation does the installer enter the existing managed transaction:
it proves all instances idle, deletes and rebuilds the Focus-exclusive CPython
3.11+ `.venv` on every install, then force-reinstalls the validated wheel under
the bundled `requirements.lock` constraint. Both pip and the post-install
consistency check run under an isolated interpreter, and install subprocesses do
not inherit `PYTHON*` import settings. Packages from the system, Conda, user site,
current directory, or `PYTHONPATH` are outside the managed environment. The
installer preserves configured index, proxy, and certificate authority, but
rejects effective pip `target`, `prefix`, `root`, or `user` configuration before
dependency writes so packages cannot be redirected outside the managed `.venv`.
Wrappers, completion, and service definitions are refreshed only after isolated
`pip check` succeeds. All four public wrappers and completion launch an absolute
managed interpreter as `-I -m <module>`; service definitions persist that same
isolated module argv directly instead of traversing a user wrapper. Isolated mode
controls import authority only for the current Focus Python process and does not
delete ordinary environment variables, so PATH and existing Focus/provider/Codex
configuration remain available to downstream tools. This is not a hot upgrade,
multi-generation environment, or automatic rollback state machine.

After the complete install body succeeds and before originally running instances
are restored, the installer atomically writes the validated bundle's `version`,
`channel`, `build_id`, and `source_revision` to `installed-build.json` in the
shared global data directory. The file uses the closed `focus-installed-build`
schema version 1 and describes the managed Focus installation shared by all
instances rather than any one instance. A failed install does not commit the
candidate bundle identity and leaves stopped services offline. Runtime projection
accepts the record only when it is strict and its `version` matches the current
Python package version. An older installation without this record reports an
unknown identity; it must not infer channel/build from a checkout, working
directory, GitHub's latest Release, or the wheel version.

Remote channels require GitHub access. Python networking honors standard
`HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY`. `--artifact` removes only the Focus
bundle's GitHub download; pip can still download third-party dependencies according
to its configured index, proxy, certificates, and cache. The bundle contains no
Python interpreter, third-party wheelhouse, or third-party artifact hashes. A user
may download the ZIP elsewhere and transfer it to the target machine, but Focus
does not promise a fully zero-network installation.

## 6. Build and Publication Are Separate Actions

A developer first generates production Web assets under `web/`, then runs
`python scripts/build_install_bundle.py`. The default produces a `local` bundle in
ignored `build/install/`; `bash install.sh --artifact <zip>` or
`./install.ps1 --artifact <zip>` installs it. The builder requires both the Web
payload and `requirements.lock` in the source and constructs and verifies one
deterministic Focus wheel containing them.

Unix developers may run `bash /path/to/focus/scripts/install_workspace.sh` from
any working directory to orchestrate those steps. This entry point does not run
`npm ci`; the caller installs Web dependencies after the first clone, when
`web/package-lock.json` changes, or when `node_modules` is absent. It generates
the production Web assets, builds a local bundle in a unique temporary directory,
requires that directory to contain exactly one Focus ZIP, and passes that exact
path to the official `install.sh --artifact`. The temporary directory is removed
after the installer returns, and no failed step may continue with an older bundle.
This entry point accepts only the optional `--migrate-from-feishu-codex`, forwards
it unchanged to `install.sh`, and rejects caller attempts to override the artifact
or channel. It creates neither a second install transaction nor another publication
path.

Ordinary commits, pull requests, CI verification, local Web builds, and local
bundle builds never publish artifacts. GitHub upload is explicit: manually dispatch
`publish-installable.yml`, or deliberately invoke the sole upload command with an
already-built and validated bundle plus its matching channel manifest.

Publication completes bundle, channel-manifest, and source-revision preflight first.
Stable then verifies the existing formal Release and tag, and uploads the immutable
bundle followed by its channel manifest; successful manifest upload and read-back is
the stable publication commit point. An ambiguous upload result is reconciled
from GitHub by commit, size, and SHA-256, and fails closed if the same result cannot
be proved.

The formal workflow writes the checked-out, gated `HEAD` to `source_revision`. The
standalone upload command cannot prove a clean caller worktree, but publication must prove that the target GitHub tag
resolves to that exact commit.

Stable requires an existing formal Release and immutable assets. Ordinary validation must not become publication by
reusing upload side effects or implicitly creating tags.

## 7. Maintenance Closure

A change to schemas, channel authority, the install-transaction boundary, or upload
ordering must update this contract, the owner implementation, installer help, the
publication workflow, and focused tests in one transaction. A Python dependency-lock
semantic change also updates the
[Python dependency-locking decision](../decisions/python-dependency-locking.md)
without maintaining competing explanations in both documents.
