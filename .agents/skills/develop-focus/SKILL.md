---
name: develop-focus
description: Execute an explicitly requested Focus diagnosis, review, feature implementation, behavior change, or refactoring task through the current repository authority, change-cone, and verification discipline.
---

# Develop Focus

Work from the Focus repository root. This is an execution router, not authority for product behavior, permissions, campaign scope, or stop decisions.

## Classify the request

Use one lane: `inspect` is read-only diagnosis/review; `change` implements or refactors and verifies; `integrate` commits or pushes only when explicitly requested; `publish` handles install artifacts, releases, or tags. Do not turn inspect into change.

## Load authority

1. Read the user task and applicable `AGENTS.md`; exclude dependency, vendor, and generated trees unless the task enters them. If none applies, use the user instruction and canonical repository docs; no template is authority.
2. Before a new scope, read `docs/architecture/development-navigation.zh-CN.md` and use `$navigate-focus-development`; it owns source roles, read-cone expansion, stale-index handling, navigation closure, and verification scope.
3. Follow an explicitly active campaign ledger as its sole temporary status source; otherwise invent neither campaign state nor a parallel plan.
4. For upstream behavior, inspect official or pinned evidence first. Upstream checkouts are read-only by default, task-local, and must keep pre-existing differences untouched; durable citations use full 40-character commits. Add browser/device verification for UI behavior when available.
5. For publication, read `docs/contracts/install-artifact-delivery.zh-CN.md` and the relevant workflow; a validation run is not publication.

## Preflight and execution

1. Confirm root, baseline worktree, platform, toolchain, dependencies, and the fixed verification plan.
2. Classify every gate as `passed`, `failed`, `not-run`, or `blocked-by-environment`; never present a missing tool as a code failure.
3. Select the smallest evidence-backed cone with `$navigate-focus-development`; for `change`, close contract, owner, consumer, test, guard, and navigation impacts together.
4. Map risk to the relevant workflow and wider gates. For `integrate`, stage only owned paths, recheck the baseline/final worktree, and report the exact commit and remote result. For `publish`, verify artifact, tag, release, source revision, and remote read-back; do not retry an ambiguous upload.
5. Stop when verified or a stop rule applies; do not expand into unrelated findings. Report changes, verification, stale refs, blockers, residual risk, and the next decision.

## Local and GitHub CI gates

Local checks are pre-push evidence, not remote CI. For `integrate`, inspect each relevant workflow, run the focused cone and required wider local equivalents, and classify skipped or unavailable gates.
After push, query GitHub Actions for the exact commit SHA and wait for all applicable runs. Pending, cancelled, or failed required runs are not green and cannot be reported complete.
Inspect failed logs, distinguish code from infrastructure/external-service failures, and retry only clearly transient safe failures. If status cannot be read, report `not-run` or `blocked-by-environment`, never inferred success.
The final handoff includes the commit SHA, workflows considered, and each remote result.
