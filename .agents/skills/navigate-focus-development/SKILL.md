---
name: navigate-focus-development
description: Navigate the Focus repository through a derived catalog of reviewed capability refs plus live changed-path impact, ref locations, and direct Python imports. Use when Codex must diagnose, review, implement, or refactor Focus code without loading unrelated repository context, or when it must choose and close a scoped change and verification cone.
---

# Navigate Focus Development

Work from the Focus repository root.

Follow `docs/architecture/development-navigation.zh-CN.md` as the canonical
discipline. This skill is its thin command entry point.

## Locate the change cone

List reviewed capabilities and show the closest match:

```bash
python scripts/focus_nav.py list
python scripts/focus_nav.py show <capability>
```

Read the returned refs first. For evidence that crosses a Python module boundary,
inspect direct imports and importers:

```bash
python scripts/focus_nav.py module bot.example
```

Review explicit changed paths; add `--locations` to resolve refs in current source:

```bash
python scripts/focus_nav.py paths <path>... [--locations]
```

## Verify the capability

Run the reviewed focused tests, sentinels, and guards:

```bash
python scripts/focus_verify.py <capability>
```

Pass `--python <exact-path>` or `--node <exact-path>` when required. Use
`--dry-run` to inspect the fixed argv/cwd plan before execution.

Use the canonical discipline for no-match or stale-index handling, navigation
closure, and wider verification gates.
