# Repository Navigation and Change-Cone Discipline

Document role: synchronized English peer. Canonical Chinese: `docs/architecture/development-navigation.zh-CN.md`.

This document defines how routine diagnosis, review, feature implementation,
behavior change, and refactoring constrain reads, identify fact sources,
expand a change cone, and close navigation impact. A feature or behavior
change aligns its relevant contract, code, tests, guards, and navigation
impact in the same transaction that changes the fact. This document defines
neither product behavior nor permission, commit budgets, or campaign
exceptions.

## 1. Boundary Between the Two Disciplines

Repository navigation discipline applies to every development task. It answers
what to read first, when to read one more hop, which derived entry points a
change must update, and how far to verify. Large-change campaign discipline is
an additional layer for broad changes. It answers what the objective and
non-goals are, how many commits are available, and when to stop or escalate.
The two compose, but must not duplicate rules or mutable status.

Start at the repository root. Task scope, reporting and stop conditions follow
the current request and applicable `AGENTS.md` files. Enter dependency, vendor
or generated trees when the task concerns them. Use the commands here directly
or enter the same workflow through `$develop-focus` or `$navigate-focus-development`.
Architecture and compatibility decisions follow [Technical Design §7](./focus-design.md#7-evolution-rules).

### 1.1 Selecting the requested stages

Read-only investigation (`inspect`) delivers findings. Implementation (`change`)
delivers changes and verification. Source integration (`integrate`) commits or
pushes as requested. Publication (`publish`) delivers the named product and channel.
A request may cover several stages. Establish the worktree baseline, toolchain,
dependencies and verification scope before starting.

For upstream behavior, check the official protocol or pinned source first.
Use a task-local, read-only upstream checkout by default and preserve existing
differences. Cite upstream source in durable documents with its full 40-character commit SHA.

## 2. Fact Roles and Precedence

| Content | Authority | Navigation role |
| --- | --- | --- |
| Normative behavior, architecture intent, and boundaries | The relevant formal document under `docs/contracts/`, `docs/architecture/`, or `docs/decisions/` | Link only; do not restate |
| Mutable runtime facts and external-effect authority | The one owner in production code | Locate the owner symbol or native implementation file |
| Configuration values and schemas | The canonical configuration surface and validator | Locate the entry or owner only |
| Regression and static evidence | Tests and guards | Form the verification cone only |
| Locations of capability entries, owners, contracts, and verification cones | [Capability catalog](../../scripts/focus_capabilities.json) | Human-reviewed derived index |
| Agent procedure entry point | The `develop-focus` and `navigate-focus-development` skills and applicable `AGENTS.md` | Route only to current authorities and fixed tools |
| Temporary campaign status | The current `docs/_work/` ledger | Never enter long-lived navigation |

The capability catalog is a human-reviewed, incomplete, disposable, and
rebuildable derived index that narrows the first read. An `owner` reference
locates an owner established by formal documentation and production code; it
does not create ownership. A missing capability does not prove its absence from
the repository. Handle conflicts with authoritative sources under section 6.
A code/formal-contract disagreement is a contract gap; neither navigation nor
test evidence can decide the normative behavior.

## 3. Code-First Navigation Invariant

Production structure should let developers follow public entries, clearly named
owners, direct dependencies, and corresponding tests to locate a change without
additional catalog prose. Fact roles remain as defined in section 2.

Code and tests must preserve these discoverability properties:

- Name packages, modules, and symbols with capability or owner vocabulary, and
  give each mutable fact or external effect one obvious production owner.
- Keep public entries and cross-boundary dependencies explicit, direct, and
  directional. Do not hide authority behind broad re-exports, dynamic
  registration, compatibility aliases, `common.py`, or `utils.py`.
- Use formal-contract vocabulary in owner APIs and types. Module docstrings may
  state a local role and link to a formal contract, but must not copy behavior,
  defaults, or mutable facts.
- Give focused tests predictable capability- or owner-shaped topology, and
  protect cross-owner invariants with explicit sentinels or direction guards.
- Split packages or files only when ownership, change locality, or dependency
  direction becomes clearer; do not fragment an owner that must maintain one
  invariant merely to satisfy a metric.

If a recurring task cannot find its owner, call chain, or tests through those
entries, correct the discoverability gap in code structure or formal contracts
within a bounded transaction or campaign.

## 4. Read-Cone Discipline

1. Read the `AGENTS.md` files applicable to the current path, then query the
   closest reviewed capability with `focus_nav.py list` / `show`. A hit is a
   reading hypothesis, not proof of ownership.
   For example, `python scripts/focus_nav.py list --under mobile` lists capabilities
   with current mobile references. `python scripts/focus_nav.py show <capability>`
   gives their implementations, contracts and verification entries.
2. For the first read, open only the returned entries, implementations, contracts
   and verification references applicable to the change. Identify the task's
   fact type, authority, and external effect before expanding.
3. Expand one hop only when evidence shows that a call or import crosses the
   current boundary; another owner reads or writes the same mutable fact or
   effect; a formal contract links to a higher-precedence contract; a failing
   test or guard points to an adjacent module; or the change affects a known
   public entry or direct consumer.
4. For Python boundaries, prefer `focus_nav.py module` to compute live direct
   imports/importers. For other languages and non-import relations, use narrow
   searches for an exact symbol, route, event, configuration key, or test name.
   Follow only one evidence-backed hop at a time; do not preload sibling files
   by directory.
5. If the catalog has no match, start a narrow search from user vocabulary, a
   public entry, a formal contract, or a failing test. Do not guess an owner or
   invent capability references. Register a capability only after human review
   of its owner, contract, and verification cone.
6. Read `docs/_work/` only for an explicitly active governance task. Routine
   development must not treat historical ledgers as current architecture or
   behavior evidence.

Stop expanding once the evidence explains the target behavior, locates the one
change authority, and selects the regression cone. Directory size or possible
relevance alone is not evidence to expand.

## 5. Change and Navigation-Impact Closure

Before editing, identify the formal contract, production owner, public entry,
direct consumers, focused tests, sentinels, direction guards and verification
steps for the affected platforms. Keep edits inside that cone unless an evidence trigger from section 4
requires expansion.

Review affected capability references in the same transaction whenever any of the
following changes. Edit the catalog only when its locations or verification scope change.

- an entry or owner's path, symbol, responsibility, or effect authority;
- a formal contract's path, heading, precedence, or behavior boundary;
- focused-test, sentinel, platform verification entry, or test-package topology;
- import direction, direct consumers, or applicable guards;
- capability creation, merge, split, or removal.

If no catalog capability is affected, navigation-impact review may close without
adding one. New entries still require the human review in section 4 and clear
value for repeated development.

Manually review the transaction's explicit changed paths before committing.
The live reverse lookup can assist that review:

```bash
python scripts/focus_nav.py paths <repo-relative-path>... [--locations]
```

The tool does not read Git or infer a capability or semantic owner from a path.
It returns only exact current-catalog matches with their capability, role, and
reference. A pytest `::node` reference matches its base file. `--locations`
parses current source to locate a symbol, Markdown heading section, or test
target. Native code and assets with whole-file references resolve to the full
current file. The lookup fails closed if any selector is not unique or if a directory-level
test target has no exact line range. `unmapped` means only that no catalog
reference matched; it is not proof of no semantic impact and does not replace
manual navigation-impact review. If the catalog cannot load, follow section 6.

A path migration must atomically remove the old reference. Unless a formal
external contract requires compatibility, do not retain old navigation paths,
shims, broad re-exports, or dual old/new entry points. Behavior fixes, owner
extractions, and package moves retain their separate transaction boundaries;
the navigation projection changes with the transaction that actually affects
it.

## 6. Fail-Closed Handling of a Stale Index

An existing path or symbol proves only that a reference resolves, not that its
owner, contract, or regression cone remains correct. If a reference is
missing, code evidence contradicts its classification, ownership moved, tests
no longer cover the behavior, or a capability points to ambiguous paths:

1. Stop using that catalog item as evidence.
2. Reconstruct the change cone narrowly from formal documents, production
   code, and tests.
3. Correct or remove stale references within this task's scope in the current
   transaction.
4. Rerun catalog validation and the affected verification cone.

Never change code or contracts to conform to a stale catalog conclusion. If an
unrelated stale reference prevents the whole catalog from loading, complete the
manual review from formal contracts, code, and tests and record that limitation.
Do not automatically expand the scope to repair unrelated references.

## 7. Allowed and Forbidden Long-Lived Navigation Content

The capability catalog contains only reviewed entry, owner, contract, focused-test,
sentinel, guard and optional `platform-check` references. Platform verification
references locate build scripts, device tests or specific sections of an operator guide.
Define checks shared by several capabilities once under `shared-platform-checks` in
the same catalog and reference them by name. `list --under`, `show`, reverse lookup
and verification plans use the same expanded references. READMEs and skills point to these queries.

Long-lived navigation must not store:

- behavior narratives, invariants, architecture rationale, or product defaults;
- branches, HEADs, counts, digests, manifests, markers, or campaign evidence;
- complete or transitive import, call, or test graphs;
- arbitrary shell commands, mutable environment facts, or `docs/_work/` refs;
- speculative entries without owner, contract, and verification-cone review.

Direct Python imports/importers, changed-path reverse lookup, and reference
locations must be computed live from current source and explicit input. Do not
persist their graph, reverse index, or line numbers. The catalog's strict schema
and reference validation reject forbidden shapes, but semantic correctness
remains the responsibility of change-impact review.

## 8. Verification Cone and Completion

`focus_verify.py <capability>` is the reviewed minimum verification cone, not a
replacement for transaction or campaign exit gates. A real change must also
include direct-consumer regressions introduced by the edit, tests named by
failure evidence, applicable static guards, contract/document checks, and any
wider gates required by its risk.

In `python scripts/focus_verify.py <capability> --dry-run`, `commands` lists automatic
checks. The `platform-check` references identify separate checks to run for the affected
artifacts and also appear in `show`. Verify UI behavior in the relevant available browser,
emulator or physical device and record the actual environment. Classify results as
`passed`, `failed`, `not-run` or `blocked-by-environment`.

When maintaining navigation itself, use `python scripts/focus_capabilities.py` to
validate current references, `python -m pytest -q tests/repo_navigation` to exercise
the tools and `bash scripts/check-docs.sh` to check document links and bilingual structure.

A development transaction is complete only when:

- authoritative contracts, code, and tests agree for the changed semantics;
- navigation references for the affected capabilities have been reviewed and stale
  references corrected, or the absence of a catalog match confirmed;
- old paths and stale references affected by this change are absent;
- focused verification and all wider gates required by the transaction pass.

### 8.1 Source integration and publication

Before integration, review the baseline and final worktree differences and stage
only the task's files. Run the local checks for the applicable [CI workflows](../../.github/workflows).

After pushing, query GitHub Actions for the exact source SHA and wait for all
applicable runs to succeed. Inspect logs for failed or cancelled runs, distinguish
code failures from external infrastructure issues and retry only confirmed transient
failures that are safe to retry. Report any inability to read remote status.
Deliver the source SHA and corresponding remote results for a source push.

If publication was requested, continue after source CI passes. Verify the remote
artifact and its provenance under the product contract and report the publication
receipt. Read back remote state before deciding whether to retry an uncertain
publication. Report verified stages, remaining material gaps and any decision needed.
[Server artifact publication](../contracts/install-artifact-delivery.md#6-build-and-publication-are-separate-actions) · [Android publisher procedure](../../mobile/README.md#android-发布者流程)
