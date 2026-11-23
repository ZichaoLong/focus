---
name: navigate-focus-development
description: Navigate the Focus repository through a derived catalog of reviewed capability refs plus live changed-path impact, ref locations, and direct Python imports. Use when Codex must diagnose, review, implement, or refactor Focus code without loading unrelated repository context, or when it must choose and close a scoped change and verification cone.
---

# Navigate Focus Development

From the Focus repository root, follow the [repository development discipline](../../../docs/architecture/development-navigation.zh-CN.md)
to locate the relevant contract, owner and verification scope. Use
`python scripts/focus_nav.py --help` for the current navigation commands and
`python scripts/focus_verify.py --help` for the verification runner.
