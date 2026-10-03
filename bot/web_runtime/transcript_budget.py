"""Whole-prose residency and tool-summary budgets for paginated items.

See docs/contracts/focus-web-transcript-window.zh-CN.md. The upstream item
store remains history authority; these copies only serve presentation.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from bot.web_runtime.reply_metadata import REPLY_METADATA_KEY, ReplyMetadata


TRANSCRIPT_PAGE_ITEMS = 40
TRANSCRIPT_WINDOW_ITEMS = 80
TOOL_SUMMARY_CHARS = 16_384
TRANSCRIPT_PAGE_BYTES = 2 * 1024 * 1024
TRANSCRIPT_CACHE_BYTES = 8 * 1024 * 1024
PREVIEW_METADATA_KEY = "_focus_transcript_preview"
PROSE_ITEM_TYPES = frozenset({"agentMessage", "userMessage", "reasoning", "hookPrompt", "contextCompaction"})


@dataclass(frozen=True, slots=True)
class TranscriptPreview:
    truncated: bool
    file_change_count: int | None = None


def bounded_transcript_item(item: dict[str, Any]) -> dict[str, Any]:
    """Keep prose whole; bound only the tree used to summarize a tool."""

    if item.get("type") in PROSE_ITEM_TYPES or item.get("liveOnly") is True:
        result = copy.deepcopy(item)
        result.pop(PREVIEW_METADATA_KEY, None)
        return result
    remaining = TOOL_SUMMARY_CHARS
    nodes = 1024
    previous = item.get(PREVIEW_METADATA_KEY)
    truncated = isinstance(previous, TranscriptPreview) and previous.truncated
    file_change_count = (
        previous.file_change_count if isinstance(previous, TranscriptPreview)
        else len(item.get("changes", [])) if item.get("type") == "fileChange" and isinstance(item.get("changes"), list)
        else None
    )
    # Terminal command/file outputs have their own exact detail reader. They
    # must not consume the budget for the card that links to that reader.
    deferred = bool(item.get("id")) and item.get("status") in {"completed", "failed", "declined"}
    command = deferred and item.get("type") == "commandExecution"
    files = deferred and item.get("type") == "fileChange"

    def copy_value(value: Any, depth: int = 0) -> Any:
        nonlocal remaining, nodes, truncated
        nodes -= 1
        if nodes < 0 or depth > 12:
            truncated = True
            return None
        if isinstance(value, str):
            length = min(len(value), max(remaining, 0))
            remaining -= length
            truncated |= length < len(value)
            return value[:length]
        if isinstance(value, list):
            result = []
            for entry in value:
                if remaining <= 0 or nodes <= 0:
                    truncated = True
                    break
                result.append(copy_value(entry, depth + 1))
            return result
        if isinstance(value, dict):
            result = {}
            # Reserve only the item's own routing fields. Nested tool arguments
            # named id/type/status are ordinary content and share the budget.
            if depth == 0:
                for key in ("id", "type", "status", "phase", "role"):
                    if key in value:
                        field = value[key]
                        if isinstance(field, str) and len(field) > 4096:
                            raise ValueError("Invalid transcript routing field")
                        result[key] = field if isinstance(field, str) else copy_value(field, depth + 1)
                # Keep the invocation identifiable even when output arrived
                # first in the source object. These are ordinary budgeted
                # fields, not additional routing authority.
                for key in (
                    "tool", "server", "success", "durationMs", "model", "command",
                    "arguments", "prompt", "query", "searchQuery", "path",
                    "revisedPrompt", "changes", "receiverThreadIds", "agentThreadId",
                ):
                    if key in value:
                        result[key] = copy_value(value[key], depth + 1)
            for key, entry in value.items():
                if key in result or key in {PREVIEW_METADATA_KEY, REPLY_METADATA_KEY}:
                    continue
                if (command and depth == 0 and key == "aggregatedOutput") or (
                    files and depth == 2 and key == "diff"
                ):
                    result[key] = ""
                    continue
                # Detailed actions can repeat a quoted/normalized version of
                # the entire script. They are read with the exact tool detail;
                # the collapsed card only needs the primary command.
                if command and depth == 0 and key == "commandActions":
                    result[key] = []
                    continue
                if len(key) > 256:
                    truncated = True
                    continue
                if nodes <= 0:
                    truncated = True
                    break
                result[key] = copy_value(entry, depth + 1)
            return result
        return value

    result = copy_value(item)
    result[PREVIEW_METADATA_KEY] = TranscriptPreview(truncated, file_change_count)
    if isinstance(item.get(REPLY_METADATA_KEY), ReplyMetadata):
        result[REPLY_METADATA_KEY] = item[REPLY_METADATA_KEY]
    return result


def transcript_item_bytes(value: Any) -> int:
    """Cheap residency estimate; never encode all live prose on every delta."""

    if isinstance(value, str):
        return len(value) * 2
    if isinstance(value, dict):
        return sum(len(key) * 2 + transcript_item_bytes(entry) for key, entry in value.items())
    if isinstance(value, (list, tuple)):
        return sum(transcript_item_bytes(entry) for entry in value)
    return 16


def bound_transcript_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evict complete older items, admitting the latest even if oversized."""

    kept: list[dict[str, Any]] = []
    size = 0
    for item in reversed(items[-TRANSCRIPT_WINDOW_ITEMS:]):
        cost = transcript_item_bytes(item)
        if kept and size + cost > TRANSCRIPT_CACHE_BYTES:
            break
        kept.append(item)
        size += cost
    return list(reversed(kept))
