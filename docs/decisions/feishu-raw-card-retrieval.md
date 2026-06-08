# Feishu Raw Card Retrieval, JSON 2.0 Terminal Cards, and Forwarded-Card Read Decisions

Chinese original: `docs/decisions/feishu-raw-card-retrieval.zh-CN.md`

See also:

- `docs/decisions/feishu-card-text-projection.md`: current best-effort text projection boundary
- `docs/architecture/feishu-codex-design.md`: current architecture and module boundaries
- `docs/contracts/feishu-thread-lifecycle.md`: execution-card and terminal-finalization lifecycle
- `docs/doc-index.md`: document index

## 1. Problem Statement

Users want both of these outcomes at the same time:

- terminal cards should display headings, lists, quotes, code, and links correctly in Feishu
- after direct send, direct forward, or merge-forward, `feishu-codex` should still read the card as faithfully as possible instead of falling back to text guessing

Two oversimplified claims appeared in earlier discussion:

- "JSON 1.0 is better for faithful reads, while JSON 2.0 only improves display"
- "once a message is `merge_forward`, we directly have the full original card JSON"

Neither is accurate.

With the current Feishu API contract:

- default card returns are receive-side projections, not the original sent card JSON
- `message/get` and `message/list` can return the original card JSON when `card_msg_content_type=user_card_content` is requested
- that capability covers both card JSON 1.0 and 2.0
- the outer `merge_forward` message body is fixed as `Merged and Forwarded Message`
- merge-forward should be handled by expanding child messages first, then querying those child messages individually

So the real design question is not "1.0 vs 2.0", but:

- when should the system prefer `message_id`-based raw-card retrieval
- when is only best-effort projection available
- how should the repository record what was actually received across restart, forwarding, cross-session reads, and incomplete historical logs

## 2. Decision Summary

This repository adopts the following decisions:

1. Terminal-card display moves to a JSON 2.0 first direction.
2. Faithful reads should not depend on default event bodies or default history-list shapes; they should prefer:
   - the target `message_id`
   - `message/get` or `message/list`
   - `card_msg_content_type=user_card_content`
3. The read architecture is three-tiered:
   - exact lookup by `message_id`: read raw card
   - `merge_forward`: expand children, then try raw-card reads on those children
   - everything else: best-effort projection
4. `merge_forward` is not the original full card JSON itself; it is only the entry point into child-message expansion.
5. Ordinary forwarding does not guarantee preservation of the original source message ID, but if the forwarded message itself is still `interactive`, its own `message_id` may still be enough to read the full card JSON.
6. `/last text` remains a fallback convenience path, not the only authoritative path.
7. This phase does not introduce a new `/text` command; priority goes to directly reading the forwarded card itself.
8. For restart-safe verification, the system must keep explicit ingress observations:
   - raw event `msg_type`
   - outer message `message_id`
   - child `message_id` values obtained after `merge_forward` expansion
   - whether raw card JSON was obtained
   - whether the final path used raw-card retrieval or projection fallback

## 3. Why JSON 2.0 Plus Raw-Card Retrieval

### 3.1 JSON 1.0 Mainly Fails at the Display Layer

In the current project, Feishu client support for JSON 1.0 markdown-subset headings is weak on the terminal-card body path.

That causes two direct costs:

- `#` and `##` style heading levels render poorly for users
- send-side display sanitization becomes necessary, which folds information

So the real advantage of staying on JSON 1.0 is not stronger fidelity by itself, but only:

- the existing best-effort projection path already knows how to consume it
- default history shapes are more likely to produce usable text projections

That is not a strong long-term design advantage.

### 3.2 JSON 2.0 Mainly Improves Display and Structure

JSON 2.0 is better for:

- structured terminal output
- correct display of heading levels, lists, quotes, code, and links
- a single card contract that serves both user-visible rendering and machine-readable structure

So terminal-card display should prefer JSON 2.0.

### 3.3 Fidelity Depends on Raw-Card Retrieval, Not on 1.0 vs 2.0

If the system only consumes:

- the receive event body
- default `message/list`
- the current `project_interactive_card_text(...)`

then both 1.0 and 2.0 are still using Feishu's projected receive shape. That is a projection path, not a high-fidelity read path.

The path becomes a raw-card read only when `card_msg_content_type=user_card_content` is requested.

At that point:

- both 1.0 and 2.0 can be read faithfully
- 2.0 is no longer inherently weaker than 1.0

So the real boundary is:

- whether a usable `message_id` exists
- whether the system actually performed raw-card retrieval

## 4. Terms

### 4.1 Default Projection Read

This means consuming:

- the default `content` inside receive events
- or the default card shape returned by `message/list` or `message/get`

and then extracting text through the repository's projection logic.

This is best-effort and does not promise full fidelity.

### 4.2 Raw-Card Read

This means calling:

- `message/get`
- or `message/list`

with:

- `card_msg_content_type=user_card_content`

so the original sent card JSON is returned.

### 4.3 High-Fidelity Read

In this decision, "high fidelity" means:

- the terminal body can be recovered
- heading levels can be recovered
- lists, quotes, code, and links can be recovered
- recovery comes from card structure rather than plain-text guessing

This does not require byte-for-byte restoration of the original markdown string.

### 4.4 Ordinary Forward

This is Feishu's normal "forward message" behavior that creates a new message.

It has its own `message_id`. The public contract does not guarantee preservation of the original source message ID.

### 4.5 `merge_forward`

This is Feishu's merge-forward message type.

Its outer message content is fixed as:

- `Merged and Forwarded Message`

The correct follow-up is to query and process its child messages.

## 5. Contract Boundaries

### 5.1 `message/get` and `message/list`

The current Feishu contract states:

- without `card_msg_content_type`:
  - callers get the default card shape
  - callers do not get the original sent card JSON
- with `user_card_content`:
  - callers get the original sent card JSON
  - this applies to both 1.0 and 2.0 cards

So the earlier assumption that "JSON 2.0 cannot be read back faithfully" should be treated as obsolete.

### 5.2 `merge_forward`

The current Feishu contract states:

- a merge-forward message body is fixed as `Merged and Forwarded Message`
- child messages can be retrieved through the message-content APIs
- `message/get` on a merge-forward returns one outer merge-forward item plus child items
- child items include `message_id`
- merge-forward scenarios may also return `upper_message_id`

But the contract does not promise:

- that a child `message_id` is always identical to the original source message ID
- that every message type remains information-complete after merge-forwarding

So the repository may only claim:

- `merge_forward` provides an official child-expansion path
- it does not prove "merge-forward can never lose information"

### 5.3 Ordinary Forward

Feishu's ordinary forward contract states:

- forwarding creates a new message
- the new message has its own `message_id`
- the new message type may still be `interactive`

But the contract does not promise:

- the original source message ID
- a universal source-reference metadata field

So the formal boundary is:

- the original source message ID may be lost
- if the forwarded message itself remains `interactive`, its own `message_id` may still be enough to retrieve the full card JSON

## 6. Read Architecture Decision

### 6.1 Overall Rule

Read paths should not branch on "1.0 vs 2.0". They should branch on whether exact traceability exists:

1. exact raw-card read by `message_id`
2. `merge_forward` with child expansion
3. projection-only fallback

### 6.2 Ordinary `interactive` Messages

When an ordinary `interactive` message arrives:

1. keep best-effort projection as the cheap immediate path
2. when high-fidelity read is needed, query `message/get` with that message's own `message_id`
3. if raw card JSON is returned, parse terminal-card identity through the repository contract
   and restore authoritative text from the local terminal result store when the card carries
   `fc_tr_<result_id>_<checksum>`
4. otherwise, fall back to text projection

The key point is:

- ordinary forwarding does not need the original source message ID to be useful
- it is enough that the newly forwarded `interactive` message can still be queried as a complete card

### 6.3 `merge_forward`

When a `merge_forward` message arrives:

1. do not treat the outer message body as meaningful content
2. expand child messages first
3. for each child:
   - if the child is `interactive`, prefer raw-card retrieval by that child's `message_id`
   - otherwise consume the child's ordinary message content
4. then aggregate child messages into the forwarded-message read surface

### 6.4 Remaining Cases

If the repository cannot get:

- a usable `message_id`
- or raw-card retrieval for that message fails

then the system should explicitly downgrade to projection fallback.

Projection fallback remains an important compatibility path, especially for:

- cards sent by other bots
- historical messages stored before this repository had raw-card support
- partially available history records

## 7. Operational Consequences

This decision leads to the following concrete repository expectations:

- terminal-card sending may prefer JSON 2.0 for display quality
- terminal-card reading should prefer raw-card retrieval whenever `message_id` is available,
  but new self-authored terminal cards treat the card body as a degraded projection unless
  their `result_id` resolves in the local thread-scoped terminal result store
- merge-forward support should be implemented as outer-message expansion plus per-child read
- `/last text` should align with the same card-reading stack instead of using a separate weaker path
- ingress logging should preserve enough facts to verify what message type and read path the system actually saw

## 8. Non-Goals

This decision does not promise:

- perfect byte-for-byte reconstruction of every historical forwarded card
- guaranteed preservation of the original source message ID across ordinary forwarding
- a new `/text` command in this phase
- that raw-card retrieval is always available for every card created by every other bot

## 9. Maintenance Rule

If the repository changes:

- terminal-card send format
- raw-card retrieval strategy
- merge-forward expansion behavior
- `/last text` read semantics
- ingress logging facts

then this document and `docs/decisions/feishu-card-text-projection*.md` should be reviewed together.
