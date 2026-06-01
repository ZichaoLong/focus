# Docs Index

This directory is the source of truth for repository architecture, runtime
boundaries, and feature contracts.

## Reading Rule

When code and docs disagree, treat that as a contract gap. Tighten the code,
the docs, or both.

## Document Types

Active docs are now organized by role:

- `docs/contracts/`
  - normative feature and runtime behavior contracts
- `docs/architecture/`
  - current architecture, layering, module split, and implementation shape
- `docs/decisions/`
  - decision records and upstream-derived safety constraints that explain why a
    design boundary exists
- `docs/verification/`
  - manual test checklists and verification-oriented material
- `docs/archive/`
  - completed plans and historical rollout material; useful for context, but
    not part of the active runtime contract

Status guidance:

- treat `contracts/`, `architecture/`, and `decisions/` as active repository
  facts
- treat `verification/` as validation support, not product/runtime semantics
- treat `archive/` as historical context only
- treat local notes under `docs/_work/` as working material, not as repository
  facts

## Read By Type

### User-Facing Entry

- [README.md](../README.md)
  - quickstart, installation, common commands, operational pitfalls, and where
    to read next

### Contracts

- [`feishu-codexctl-command-matrix.md`](./contracts/feishu-codexctl-command-matrix.md)
- [`feishu-command-matrix.md`](./contracts/feishu-command-matrix.md)
- [`feishu-thread-lifecycle.md`](./contracts/feishu-thread-lifecycle.md)
- [`runtime-control-surface.md`](./contracts/runtime-control-surface.md)
- [`runtime-settings-fact-sources.md`](./contracts/runtime-settings-fact-sources.md)
- [`thread-next-load-settings-semantics.md`](./contracts/thread-next-load-settings-semantics.md)
- [`thread-profile-semantics.md`](./contracts/thread-profile-semantics.md)
- [`thread-memory-semantics.md`](./contracts/thread-memory-semantics.md)
- [`feishu-help-navigation.md`](./contracts/feishu-help-navigation.md)
- [`scheduled-prompts.md`](./contracts/scheduled-prompts.md)
- [`codex-permissions-model.md`](./contracts/codex-permissions-model.md)
- [`group-chat-contract.md`](./contracts/group-chat-contract.md)
- [`local-command-and-thread-profile-contract.md`](./contracts/local-command-and-thread-profile-contract.md)

### Architecture

- [`feishu-codex-design.md`](./architecture/feishu-codex-design.md)
- [`fcodex-shared-backend-runtime.md`](./architecture/fcodex-shared-backend-runtime.md)

### Decisions

- [`cross-instance-live-runtime-admission.md`](./decisions/cross-instance-live-runtime-admission.md)
- [`shared-backend-resume-safety.md`](./decisions/shared-backend-resume-safety.md)
- [`managed-backend-startup-profile.md`](./decisions/managed-backend-startup-profile.md)
- [`feishu-attachment-ingress.md`](./decisions/feishu-attachment-ingress.md)
- [`feishu-card-text-projection.md`](./decisions/feishu-card-text-projection.md)
- [`feishu-raw-card-retrieval.md`](./decisions/feishu-raw-card-retrieval.md)
- [`feishu-output-images.md`](./decisions/feishu-output-images.md)

### Verification

- [`group-chat-manual-test-checklist.zh-CN.md`](./verification/group-chat-manual-test-checklist.zh-CN.md)

### Archive

- [`codex-handler-decomposition-plan.md`](./archive/codex-handler-decomposition-plan.md)

## Read By Question

| Question | Read |
| --- | --- |
| What `feishu-codexctl` subcommands exist, which state layer each operates on, which mutate state, what the parameter constraints are, and how they map to the Feishu surface? | [`feishu-codexctl-command-matrix.md`](./contracts/feishu-codexctl-command-matrix.md) |
| What Feishu slash commands currently exist, which are reachable from `/help`, who may execute them, what buttons belong to them, and how do they map to local CLIs? | [`feishu-command-matrix.md`](./contracts/feishu-command-matrix.md) |
| What is the current architecture, layering, module split, and repository structure? | [`feishu-codex-design.md`](./architecture/feishu-codex-design.md) |
| What is the Feishu-side thread lifecycle, and what states must stay distinct? | [`feishu-thread-lifecycle.md`](./contracts/feishu-thread-lifecycle.md) |
| What shared state vocabulary and admin-surface contract apply to `/status`, `/detach`, and `feishu-codexctl`? | [`runtime-control-surface.md`](./contracts/runtime-control-surface.md) |
| How should questions like “what was just set”, “what is persisted now”, “when does it actually take effect”, and “does provisional state already have a formal fact source” be separated for runtime settings? | [`runtime-settings-fact-sources.md`](./contracts/runtime-settings-fact-sources.md), [`thread-next-load-settings-semantics.md`](./contracts/thread-next-load-settings-semantics.md), [`runtime-control-surface.md`](./contracts/runtime-control-surface.md) |
| For thread-wise next-load settings such as profile and memory mode, when do they take effect, when is direct write allowed, and when is reset-backend required? | [`thread-next-load-settings-semantics.md`](./contracts/thread-next-load-settings-semantics.md) |
| What do `/threads`, `/resume`, `/profile`, and `/archive` mean across Feishu, `fcodex`, and the TUI? | [`thread-profile-semantics.md`](./contracts/thread-profile-semantics.md) |
| Why was the historical thread-memory surface removed, and which two setting layers replace it now? | [`thread-memory-semantics.md`](./contracts/thread-memory-semantics.md), [`runtime-settings-fact-sources.md`](./contracts/runtime-settings-fact-sources.md) |
| What is the formal boundary for continuing a Feishu-bound thread later, including `binding/submit-prompt`, `feishu-codexctl prompt send`, and the Linux `systemd --user` skill? | [`scheduled-prompts.md`](./contracts/scheduled-prompts.md) |
| What is the current contract for `/detach`, a thinner `fcodex`, the `feishu-codexctl` split, and thread-wise profile/provider? | [`local-command-and-thread-profile-contract.md`](./contracts/local-command-and-thread-profile-contract.md) |
| How do multi-instance `default` / named-instance behavior, shared thread visibility, `fcodex --instance`, and the global runtime lease work? | [`thread-profile-semantics.md`](./contracts/thread-profile-semantics.md), [`runtime-control-surface.md`](./contracts/runtime-control-surface.md), [`fcodex-shared-backend-runtime.md`](./architecture/fcodex-shared-backend-runtime.md) |
| How should provider-specific catalogs, `remote`, and a future `managed backend startup profile` be chosen between, and why is that not an “instance-level default profile”? | [`managed-backend-startup-profile.md`](./decisions/managed-backend-startup-profile.md), [`thread-profile-semantics.md`](./contracts/thread-profile-semantics.md), [`thread-memory-semantics.md`](./contracts/thread-memory-semantics.md) |
| What information architecture and semantic rules does the Feishu `/help` navigation surface follow? | [`feishu-help-navigation.md`](./contracts/feishu-help-navigation.md) |
| What is the formal behavior contract for group activation, group modes, history recovery, and group-command triggering? | [`group-chat-contract.md`](./contracts/group-chat-contract.md) |
| How do approval, sandbox, writable roots, and protected paths behave? | [`codex-permissions-model.md`](./contracts/codex-permissions-model.md) |
| How does `fcodex` shared-backend mode work, including wrapper, proxy, and `--cd` semantics? | [`fcodex-shared-backend-runtime.md`](./architecture/fcodex-shared-backend-runtime.md) |
| What safety rules apply to shared backend reuse and `/resume`? | [`shared-backend-resume-safety.md`](./decisions/shared-backend-resume-safety.md) |
| What boundary should Feishu attachment / file-message support follow, including what gets downloaded and what remains outside this repository? | [`feishu-attachment-ingress.md`](./decisions/feishu-attachment-ingress.md) |
| What is the boundary for Feishu card text projection, terminal `final_reply_text`, and best-effort extraction from ordinary cards? | [`feishu-card-text-projection.md`](./decisions/feishu-card-text-projection.md) |
| How should Feishu card reads move from JSON 2.0 display output to `message_id`-based raw-card retrieval, and what is the read decision across ordinary forwards, merge-forwards, and best-effort projection? | [`feishu-raw-card-retrieval.md`](./decisions/feishu-raw-card-retrieval.md) |
| What is the current boundary for Feishu outbound generated images, including text-before-image ordering and why arbitrary workspace images are out of scope? | [`feishu-output-images.md`](./decisions/feishu-output-images.md) |
| What cross-instance safety rule applies before attach / resume, and why is `ThreadRuntimeLease` alone not enough? | [`cross-instance-live-runtime-admission.md`](./decisions/cross-instance-live-runtime-admission.md), [`shared-backend-resume-safety.md`](./decisions/shared-backend-resume-safety.md), [`runtime-control-surface.md`](./contracts/runtime-control-surface.md) |
| What should be covered in manual group-chat regression testing? | [`group-chat-manual-test-checklist.zh-CN.md`](./verification/group-chat-manual-test-checklist.zh-CN.md) |
| What historical rollout plan was used to decompose `CodexHandler` ownership? | [`codex-handler-decomposition-plan.md`](./archive/codex-handler-decomposition-plan.md) |

## Practical Reading Paths

- For architecture or large refactors:
  - [`feishu-codex-design.md`](./architecture/feishu-codex-design.md)
  - then the relevant `contracts/` and `decisions/` docs
- For session or runtime bugs:
  - [`feishu-thread-lifecycle.md`](./contracts/feishu-thread-lifecycle.md)
  - [`runtime-control-surface.md`](./contracts/runtime-control-surface.md)
  - [`runtime-settings-fact-sources.md`](./contracts/runtime-settings-fact-sources.md)
  - [`thread-profile-semantics.md`](./contracts/thread-profile-semantics.md)
  - [`local-command-and-thread-profile-contract.md`](./contracts/local-command-and-thread-profile-contract.md)
  - [`shared-backend-resume-safety.md`](./decisions/shared-backend-resume-safety.md)
- For group-chat work:
  - [`feishu-command-matrix.md`](./contracts/feishu-command-matrix.md)
  - [`group-chat-contract.md`](./contracts/group-chat-contract.md)
  - [`feishu-help-navigation.md`](./contracts/feishu-help-navigation.md)
  - [`group-chat-manual-test-checklist.zh-CN.md`](./verification/group-chat-manual-test-checklist.zh-CN.md)
- For local `feishu-codexctl` inspection / management work:
  - [`feishu-codexctl-command-matrix.md`](./contracts/feishu-codexctl-command-matrix.md)
  - [`scheduled-prompts.md`](./contracts/scheduled-prompts.md)
  - [`local-command-and-thread-profile-contract.md`](./contracts/local-command-and-thread-profile-contract.md)
  - [`runtime-control-surface.md`](./contracts/runtime-control-surface.md)
  - [`runtime-settings-fact-sources.md`](./contracts/runtime-settings-fact-sources.md)
  - [`thread-profile-semantics.md`](./contracts/thread-profile-semantics.md)
- For wrapper or backend work:
  - [`local-command-and-thread-profile-contract.md`](./contracts/local-command-and-thread-profile-contract.md)
  - [`fcodex-shared-backend-runtime.md`](./architecture/fcodex-shared-backend-runtime.md)
  - [`managed-backend-startup-profile.md`](./decisions/managed-backend-startup-profile.md)
  - [`shared-backend-resume-safety.md`](./decisions/shared-backend-resume-safety.md)
- For multi-instance behavior, shared thread visibility, `feishu-codexctl --instance`,
  or cross-instance runtime lease work:
  - [`thread-profile-semantics.md`](./contracts/thread-profile-semantics.md)
  - [`runtime-control-surface.md`](./contracts/runtime-control-surface.md)
  - [`cross-instance-live-runtime-admission.md`](./decisions/cross-instance-live-runtime-admission.md)
  - [`fcodex-shared-backend-runtime.md`](./architecture/fcodex-shared-backend-runtime.md)
  - [`shared-backend-resume-safety.md`](./decisions/shared-backend-resume-safety.md)
- For Feishu attachment ingress, file messages, local staging, or image-input
  upgrade work:
  - [`feishu-attachment-ingress.md`](./decisions/feishu-attachment-ingress.md)
  - [`feishu-output-images.md`](./decisions/feishu-output-images.md)
  - [`codex-permissions-model.md`](./contracts/codex-permissions-model.md)
  - [`group-chat-contract.md`](./contracts/group-chat-contract.md)
- For Feishu card messages, terminal-result round-trip, or best-effort text
  extraction from ordinary cards:
  - [`feishu-card-text-projection.md`](./decisions/feishu-card-text-projection.md)
  - [`feishu-raw-card-retrieval.md`](./decisions/feishu-raw-card-retrieval.md)
  - [`feishu-output-images.md`](./decisions/feishu-output-images.md)
  - [`feishu-thread-lifecycle.md`](./contracts/feishu-thread-lifecycle.md)
  - [`feishu-codex-design.md`](./architecture/feishu-codex-design.md)
- For permission or execution wording:
  - [`codex-permissions-model.md`](./contracts/codex-permissions-model.md)

## Language

- Most technical docs have both English and Simplified Chinese versions.
- The current manual group-chat verification checklist is only available in
  Simplified Chinese.
