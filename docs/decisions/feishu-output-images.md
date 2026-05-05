# Feishu Outbound Image Delivery Boundary

See also:

- `docs/architecture/feishu-codex-design.md` for the current architecture and
  repository boundaries
- `docs/contracts/feishu-thread-lifecycle.md` for execution-card and terminal
  result-carrier lifecycle rules
- `docs/decisions/feishu-card-text-projection.md` for the current authoritative
  terminal text contract
- `docs/decisions/feishu-attachment-ingress.md` for the opposite direction:
  Feishu attachment ingress into Codex

## 1. Problem Statement

Users want `feishu-codex` to deliver replies that may contain both text and
images on the Feishu side.

There are two distinct output scenarios:

1. Codex emits an explicit image-generation result as part of a turn.
2. Codex causes some image file to exist locally by some other path, such as a
   shell command, a web fetch, an MCP tool, or manual file creation.

This repository already has a clear terminal text contract, but it does not yet
have a corresponding outbound-image contract.

Without tightening that boundary first, "support image replies" is ambiguous:

- should images live inside the running execution card
- should they be sent as separate Feishu image messages
- should any local image file be auto-sent
- should replay / reconcile after restart re-send them
- should other Feishu bots be expected to consume those outbound images

This document narrows that scope.

## 2. Current Facts

### 2.1 Current Repository Behavior

The current repository baseline is:

1. Feishu-to-Codex image ingress already exists.
   - Feishu `image` attachments are downloaded and staged locally.
   - They are passed into Codex as both path-bearing text context and
     `localImage` turn input.
2. Codex-to-Feishu image egress does not yet exist as a first-class feature.
3. The current user-visible turn result path is text-only:
   - running output goes to the execution card
   - authoritative terminal text goes to the terminal result card, or falls
     back to plain text
4. `imageGeneration` is currently treated only as process-log material for the
   execution card rather than as a deliverable Feishu image payload.

So the gap is larger than "the execution card lacks image rendering". The
repository currently lacks an outbound image carrier, outbound image
deduplication, and outbound image reconcile behavior.

### 2.2 Upstream Codex Facts

Upstream Codex already exposes a useful first-class image-generation shape:

- turn items may contain `imageGeneration`
- those items carry:
  - `result`
  - optional `savedPath`
- upstream core tries to save generated image bytes to disk and records
  `savedPath` when that succeeds
- app-server thread snapshots preserve that `savedPath`

Important implications:

1. `result` is currently the upstream image-generation payload and is typically
   base64 image data, but this repository should treat that as an upstream item
   payload rather than inventing its own generic image-decoding contract.
2. `savedPath` is not guaranteed to exist for every `imageGeneration` item.
   Save may fail, or the payload may be invalid.
3. A restart-safe outbound image implementation should not rely only on the
   transient notification stream; it should also be able to recover from
   thread snapshots that still contain `imageGeneration` items with
   `savedPath`.

### 2.3 Feishu Platform Facts

Feishu already supports the primitives needed for a reliable append-only image
delivery path:

- upload an image resource and obtain an `image_key`
- send a message whose `msg_type` is `image`
- reply with an `image` message to a prior message

Official references:

- upload image:
  `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/image/create`
- send message:
  `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/create`
- reply message:
  `https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/reply`

This is a better fit than trying to force outbound images into the current
execution-card patch loop.

## 3. Why Existing Mechanisms Are Not Enough

The current repository already has two strong output layers:

- execution card:
  - human-oriented
  - patchable
  - process-log and staged-reply UI
- terminal result carrier:
  - authoritative text-only result contract
  - stable for Feishu-to-Codex round-trip of `final_reply_text`

Neither of these solves outbound images cleanly:

1. The execution card is currently patch-driven UI, not a general multimedia
   transcript carrier.
2. The authoritative terminal contract is explicitly text-centered today.
3. There is no persisted ledger of "which images for which turn have already
   been delivered to Feishu".
4. There is no current rule for how image outputs should behave under watchdog,
   reconcile, or post-restart recovery.

So image support should not be framed as "just teach the current card to show
images". That would blur the text contract and complicate recovery.

## 4. Phase-1 Decision

The repository should adopt the following first-phase outbound-image contract.

### 4.1 Keep Text as the Only Authoritative Round-Trip Contract

`final_reply_text` remains the only authoritative terminal result contract for
Feishu message round-trip and downstream bot consumption.

Images are an additional human-facing artifact. They do not replace
`final_reply_text`, and they are not consumed by the existing strong text
projection contract.

### 4.2 Support Only Explicit `imageGeneration` Outputs

Phase 1 should support outbound images only when upstream Codex emits explicit
`imageGeneration` items.

This means:

- supported:
  - images generated by Codex through upstream image-generation capability
- not supported in phase 1:
  - arbitrary workspace image files created by unrelated commands
  - arbitrary downloaded images that happen to land in the workspace
  - "guess from assistant text that an image path should be sent"

Reason:

- `imageGeneration` already gives the repository an explicit semantic output
  item
- arbitrary local files do not

### 4.3 Use `savedPath` as the Canonical Delivery Input

For phase 1, the repository should treat `savedPath` as the canonical image
delivery input.

Recommended rule:

1. if an `imageGeneration` item has a non-empty `savedPath` and the file still
   exists locally:
   - it is eligible for Feishu delivery
2. if `savedPath` is absent:
   - do not attempt best-effort delivery in phase 1
   - keep the execution-card process note, but do not invent a fallback decode
     path here

This keeps ownership clear:

- upstream owns image-generation payload decoding and saving
- this repository owns Feishu delivery of already-materialized local artifacts

### 4.4 Delivery Shape: Text First, Then 0..N Image Messages

The recommended Feishu delivery order is:

1. continue emitting the current authoritative terminal text carrier
2. then send zero or more Feishu image replies for the same turn

This gives:

- stable text semantics
- simple image transport
- no need to redesign the current execution-card contract

### 4.5 Execution Card Stays Text-Oriented

The execution card may continue to show process notes such as `图片生成`, but it
should not become the authoritative image carrier in phase 1.

Reasons:

- the current execution card is patch-centric
- image delivery is naturally append-only on Feishu
- mixing terminal authoritative text and mutable image UI into one card would
  complicate reconcile, dedupe, and long-running update behavior

### 4.6 Recovery and Deduplication Are Mandatory

Outbound image support must be recovery-safe.

So the implementation should maintain persisted turn-scoped delivery state, for
example keyed by:

- instance
- chat binding
- thread id
- turn id
- image item id

That state must prevent duplicate image delivery across:

- late reconcile
- watchdog recovery
- service restart
- repeated terminal processing of the same turn

Fast path may send an image as soon as an `item/completed(imageGeneration)`
notification arrives with `savedPath`, but that notification stream must not be
the only authority. Recovery should still be able to re-read the terminal thread
snapshot and deliver any missing image artifacts exactly once.

## 5. Explicit Non-goals

Phase 1 outbound-image support does not try to solve:

1. generic "send any local image file back to Feishu"
2. image-gallery patching inside the running execution card
3. making outbound Feishu images part of the existing strong text-ingress
   projection contract
4. guaranteeing that another Feishu bot can reliably consume those image
   messages as machine-readable input

That last point matters because this repository's current Feishu-side bot
triggering and text-ingress model is intentionally text-centered and does not
define a second strong contract for bot-authored image replies.

## 6. Implications for the Two Common User Expectations

### 6.1 "Codex generated an image"

This should be supported in phase 1, but only through explicit upstream
`imageGeneration` items with a usable `savedPath`.

### 6.2 "Codex downloaded or created an image file locally"

This should not be auto-supported in phase 1 just because a local image file now
exists.

To support that reliably, the repository would need a new explicit outbound
contract, such as:

- a dedicated upstream output item type
- a repository-owned explicit send-image action
- or some other structured declaration that a given local file is meant for
  Feishu delivery

Without that, auto-sending arbitrary local image files would be ambiguous and
unsafe.

## 7. Recommended Next Step

If the repository implements outbound images, the first implementation should be
deliberately narrow:

1. keep the existing text result contract unchanged
2. add Feishu image upload + reply helpers
3. collect terminal `imageGeneration` items from thread snapshots
4. deliver only `savedPath`-backed generated images
5. persist per-turn image-delivery state for reconcile and restart safety

That is the cleanest path that adds real user value without collapsing the
current text contract and execution-card lifecycle into a mixed, ambiguous
multimedia channel.
