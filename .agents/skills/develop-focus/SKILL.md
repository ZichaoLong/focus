---
name: develop-focus
description: Execute an explicitly requested Focus diagnosis, review, feature implementation, behavior change, or refactoring task through the current repository authority, change-cone, and verification discipline.
---

# Develop Focus

Work from the Focus repository root. This is an execution router, not authority for product behavior, permissions, campaign scope, or stop decisions.

## Classify the request

Use one lane before reading broadly: `inspect` is read-only diagnosis/review;
`change` implements or refactors and verifies; `integrate` commits or pushes
only when explicitly requested; `publish` handles install artifacts, releases,
or tags. Do not turn an inspect request into a change.

## Load authority

1. Read the user task and applicable repository `AGENTS.md` files. Exclude
   dependency, vendor, and generated trees unless the task explicitly enters
   them. If no repository `AGENTS.md` applies, use the user instruction,
   canonical repository docs, and this router; no template is an authority.
2. Re-resolve instructions before entering a new scope. Read
   `docs/architecture/development-navigation.zh-CN.md` completely and use
   `$navigate-focus-development`; it owns source roles, read-cone expansion,
   stale-index handling, navigation closure, and verification scope.
3. If a campaign ledger is explicitly active, follow it as the sole temporary
   status source; otherwise do not invent campaign state or a parallel plan.
4. For upstream-owned behavior, inspect official or pinned upstream evidence
   first. Upstream checkouts are read-only by default, task-local, and must keep
   pre-existing differences untouched; durable citations use full 40-character
   commits. For UI behavior, add browser/device verification when available.
5. For publication, read `docs/contracts/install-artifact-delivery.zh-CN.md`
   and the relevant workflow; a validation run is not publication.

## Preflight and execution

1. Confirm repository root, baseline worktree, platform, toolchain, and dependencies. Inspect the fixed verification plan before running it.
2. Classify every gate as `passed`, `failed`, `not-run`, or
   `blocked-by-environment`; never present a missing tool as a code failure.
3. Select the smallest evidence-backed change cone with
   `$navigate-focus-development`. Keep `inspect` read-only; for `change`, close
   contract, owner, consumer, test, guard, and navigation impacts together.
4. Map risk to the relevant CI workflow and wider gates. For `integrate`, stage
   only owned paths, recheck the baseline and final worktree, and report the
   exact commit and remote result. For `publish`, verify artifact, tag, release,
   source revision, and remote read-back; do not retry an ambiguous upload.
5. Stop when the requested outcome is verified or a current stop rule applies;
   do not expand into unrelated findings. Report changes, verification status,
   unmapped/stale refs, blockers, residual risk, and the next decision.

## Local and GitHub CI gates

Local verification is pre-push evidence, not a substitute for remote CI. Before
an explicitly requested `integrate`, inspect the workflows triggered by the
target ref, run the focused cone plus the required wider local equivalents, and
classify every skipped or unavailable gate.

After pushing, query GitHub Actions for the exact pushed commit SHA and wait for
the applicable workflow runs to finish. Treat the remote result as part of
integration completion: a pending, cancelled, or failed required run is not
green and must not be reported as complete. Inspect failed logs and distinguish
code failures from infrastructure or external-service failures; retry only when
the failure is clearly transient and the retry is safe. If GitHub status cannot
be read, report it as `not-run` or `blocked-by-environment` rather than inferring
success. The final handoff must include the commit SHA, workflows considered,
and each remote result.
