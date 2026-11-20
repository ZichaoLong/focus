---
name: develop-focus
description: Execute an explicitly requested Focus diagnosis, review, feature implementation, behavior change, source integration, or server or Android publication using the repository's navigation and verification discipline.
---

# Develop Focus

Work from the Focus repository root. This is an execution router, not authority for product behavior, permissions, campaign scope, or stop decisions.

## Classify the request

Match the requested stages: `inspect` is read-only diagnosis/review, `change` implements and verifies, `integrate` commits and/or pushes the requested source, and `publish` delivers a named product and channel. A single explicit request may authorize the whole sequence. A request for inspection ends with findings; a source push alone ends with CI.

## Load authority

1. Read the user task and applicable `AGENTS.md`; exclude dependency, vendor, and generated trees unless the task enters them. If none applies, use the user instruction and canonical repository docs; no template is authority.
2. Before a new scope, use `$navigate-focus-development` under `docs/architecture/development-navigation.zh-CN.md`. For architecture or compatibility decisions, also read §7 of `docs/architecture/focus-design.zh-CN.md`.
3. Follow an explicitly active campaign ledger as its sole temporary status source; otherwise invent neither campaign state nor a parallel plan.
4. For upstream behavior, inspect official or pinned evidence first. Upstream checkouts are read-only by default, task-local, and must keep pre-existing differences untouched; durable citations use full 40-character commits. Add browser/device verification for UI behavior when available.
5. For a server stable publication use `docs/contracts/install-artifact-delivery.zh-CN.md` and the relevant workflow. For Android main or stable use the mobile distribution section in `docs/contracts/focus-mobile.zh-CN.md` and its publisher. A validation run is not publication.

## Preflight and execution

1. Confirm root, baseline worktree, platform, toolchain, dependencies, and the fixed verification plan.
2. Classify every gate as `passed`, `failed`, `not-run`, or `blocked-by-environment`; never present a missing tool as a code failure.
3. For `change`, complete the navigation and verification closure defined by the navigation discipline.
4. For `integrate`, stage only owned paths and recheck the baseline/final worktree. For server `publish`, verify the artifact, tag, Release, and source revision. For Android, verify the authorized channel, signing fingerprint and exact source SHA, then publish the APK and manifest in a single distribution-repository commit. Stable may promote a verified main APK. Perform remote read-back before deciding how to handle an uncertain push.
5. Stop when verified or a stop rule applies; do not expand into unrelated findings. Report changes, verification, stale refs, blockers, residual risk, and the next decision.

## Local and GitHub CI gates

Local checks are pre-push evidence, not remote CI. For `integrate`, inspect each relevant workflow, run the focused cone and required wider local equivalents, and classify skipped or unavailable gates.
After push, query GitHub Actions for the exact commit SHA and wait for all applicable runs. Pending, cancelled, or failed required runs are not green and cannot be reported complete.
Inspect failed logs, distinguish code from infrastructure/external-service failures, and retry only clearly transient safe failures. If status cannot be read, report `not-run` or `blocked-by-environment`, never inferred success.
After source CI passes, carry out any publication included in the request. Report the source SHA and each remote result; for mobile releases also give the distribution SHA, channel, APK link, digest, and verified signer.
