"""Request-local item windows for the paginated browser transcript.

See docs/contracts/focus-web-transcript-window.zh-CN.md. Selection and read
admission belong to WebThreadInspectionService; this module only reads and
projects its frozen inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from bot.adapters.base import ThreadItemsPage
from bot.codex_protocol.connection import CodexRpcError
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.document_registry import WebDocumentOperationReceipt
from bot.web_runtime.projection import bounded_summary_prompt_text, project_turns
from bot.web_runtime.transcript_source import decode_transcript_source, encode_transcript_source
from bot.web_runtime.thread_read_model import WebThreadReadObservationReceipt
from bot.web_runtime.transcript_budget import (
    PREVIEW_METADATA_KEY,
    TRANSCRIPT_PAGE_BYTES,
    TRANSCRIPT_PAGE_ITEMS,
    TranscriptPreview,
    bounded_transcript_item,
)


@dataclass(frozen=True, slots=True)
class WebThreadTranscriptPreparation:
    client_id: str
    thread_id: str
    turn_id: str | None
    cursor: str | None
    direction: str
    item_id: str | None
    full: bool
    document: WebDocumentOperationReceipt
    observation: WebThreadReadObservationReceipt
    connection_generation: int
    deadline: float
    runtime_epoch: str
    revision: int
    view: str = "transcript"
    source_cursor: str | None = None


def project_transcript_item(
    turn_id: str,
    item: dict[str, Any],
    *,
    status: str = "",
    full: bool = False,
    attachment_url_for_path: Callable[[str], str] | None = None,
    attachment_url_for_id: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Project stable item identities independently of preceding turn items."""

    item_id = str(item.get("id", "") or "").strip()
    if not item_id:
        return []
    source = item if full else bounded_transcript_item(item)
    metadata = source.get(PREVIEW_METADATA_KEY)
    projected = project_turns(
        [{"id": turn_id, "status": status, "items": [source]}],
        defer_tool_output=not full,
        attachment_url_for_path=attachment_url_for_path,
        attachment_url_for_id=attachment_url_for_id,
    )
    # A raw-turn projector reserves an empty response after a live user item.
    # An item window only includes rows belonging to the item itself.
    projected = [turn for turn in projected if not (
        turn.get("role") == "assistant" and not turn.get("blocks")
        and not turn.get("text") and not turn.get("tools")
    )]
    for index, turn in enumerate(projected):
        turn["id"] = f"{turn_id}:item:{item_id}:{index}"
        turn["rawTurnId"] = turn_id
        turn["itemId"] = item_id
        if isinstance(metadata, TranscriptPreview) and metadata.truncated:
            turn["contentDeferred"] = True
    if not full and len(json.dumps(projected, ensure_ascii=False).encode("utf-8")) > (TRANSCRIPT_PAGE_BYTES - 64 * 1024) // TRANSCRIPT_PAGE_ITEMS:
        # Multi-file tools and duplicated presentation fields can exceed the
        # source character budget. Keep one explicit plain-text preview.
        first = projected[0] if projected else {}
        projected = [{
            "id": f"{turn_id}:item:{item_id}:0", "rawTurnId": turn_id,
            "itemId": item_id, "role": first.get("role", "assistant"),
            "no": 0, "text": str(first.get("text") or item.get("type", ""))[:4096],
            "contentDeferred": True,
        }]
    return projected


def read_transcript_window(
    prepared: WebThreadTranscriptPreparation,
    *,
    list_thread_items: Callable[..., ThreadItemsPage],
    remaining: Callable[[], float],
    attachment_url_for_path: Callable[[str], str] | None = None,
    attachment_url_for_id: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "turn_id": prepared.turn_id,
        "expected_connection_generation": prepared.connection_generation,
    }
    cursor, direction = prepared.cursor, prepared.direction
    limit = 100 if prepared.view == "prompts" else TRANSCRIPT_PAGE_ITEMS
    exact_page = False
    if prepared.source_cursor:
        source = decode_transcript_source(prepared.source_cursor)
        cursor, direction, limit = source["cursor"], source["sort_direction"], source["limit"]
        kwargs["turn_id"] = source["turn_id"]
        exact_page = True
    elif prepared.item_id and not cursor:
        try:
            # New servers provide an exclusive item anchor. Older releases
            # accept only opaque strings; those continue in bounded pages.
            predecessor = list_thread_items(
                prepared.thread_id, **kwargs, anchor_item_id=prepared.item_id,
                sort_direction="desc", limit=1, timeout=remaining(),
            )
        except CodexRpcError as exc:
            if exc.error.get("code") != -32600 or "expected a string" not in str(exc):
                raise
        else:
            if (not isinstance(predecessor, ThreadItemsPage) or len(predecessor.items) > 1
                    or any(entry.turn_id != prepared.turn_id or not entry.item.get("id")
                           for entry in predecessor.items)):
                raise WebRuntimeError("Invalid transcript anchor.", code="transcript_protocol_error", status=502)
            kwargs["anchor_item_id"] = (
                str(predecessor.items[0].item["id"]) if predecessor.items else None
            )
            exact_page = True
            limit = 1 if prepared.full else TRANSCRIPT_PAGE_ITEMS
        direction = "asc"
    elif prepared.item_id:
        direction = "asc"
    # A navigation locator identifies one message, not a turn-sized browsing
    # boundary. Old string-only servers scan the thread in cancellable batches.
    # Indexed anchors first resolve exactly one scoped item, then reuse its
    # inclusive opaque cursor across the thread. Never fabricate a cursor.
    navigation_target = not prepared.full and bool(prepared.turn_id)
    if navigation_target and not exact_page and prepared.item_id:
        kwargs["turn_id"] = None
    if navigation_target and exact_page:
        limit = 1
    for _ in range(4 if prepared.view == "prompts" else 1):
        page = list_thread_items(
            prepared.thread_id, **kwargs, cursor=cursor, sort_direction=direction,
            limit=limit, timeout=remaining(),
        )
        if not isinstance(page, ThreadItemsPage) or len(page.items) > limit:
            raise WebRuntimeError("Invalid transcript page.", code="transcript_protocol_error", status=502)
        if prepared.view != "prompts" or not page.next_cursor or any(
            entry.item.get("type") == "userMessage" for entry in page.items
        ):
            break
        if page.next_cursor == cursor:
            raise WebRuntimeError("Transcript cursor did not advance.", code="transcript_protocol_error", status=502)
        cursor = page.next_cursor
    remaining()
    if not isinstance(page, ThreadItemsPage) or len(page.items) > limit:
        raise WebRuntimeError("Invalid transcript page.", code="transcript_protocol_error", status=502)
    if kwargs["turn_id"] and any(entry.turn_id != kwargs["turn_id"] for entry in page.items):
        raise WebRuntimeError("Mismatched transcript turn.", code="transcript_protocol_error", status=502)
    if navigation_target and kwargs["turn_id"] and page.items:
        if prepared.item_id and not any(entry.turn_id == prepared.turn_id
                and entry.item.get("id") == prepared.item_id for entry in page.items):
            raise WebRuntimeError("This message is no longer available.", code="transcript_item_missing", status=404)
        if not page.backwards_cursor:
            raise WebRuntimeError("Missing transcript anchor cursor.", code="transcript_protocol_error", status=502)
        cursor = page.backwards_cursor
        kwargs = {"turn_id": None, "expected_connection_generation": prepared.connection_generation}
        direction, limit = "asc", TRANSCRIPT_PAGE_ITEMS
        page = list_thread_items(prepared.thread_id, **kwargs, cursor=cursor,
            sort_direction=direction, limit=limit, timeout=remaining())
        if not isinstance(page, ThreadItemsPage) or len(page.items) > limit:
            raise WebRuntimeError("Invalid transcript page.", code="transcript_protocol_error", status=502)
        remaining()
    entries = list(reversed(page.items)) if direction == "desc" else page.items
    target = next((entry for entry in entries if entry.turn_id == prepared.turn_id
                   and entry.item.get("id") == prepared.item_id), None) if prepared.item_id else None
    pending = bool(prepared.item_id and target is None and not exact_page and page.next_cursor)
    if prepared.item_id and target is None and not pending:
        raise WebRuntimeError("This message is no longer available.", code="transcript_item_missing", status=404)
    if prepared.item_id:
        # Retain the entire scan page around a located item. Its cursors bound
        # that page; trimming the prefix would skip context when paging back.
        entries = [] if target is None else ([target] if prepared.full else entries)
    source_cursor = encode_transcript_source(page.backwards_cursor, kwargs["turn_id"], direction, limit)
    turns: list[dict[str, Any]] = []
    for entry in entries:
        if prepared.view == "prompts" and entry.item.get("type") != "userMessage":
            continue
        rows = project_transcript_item(
            entry.turn_id, entry.item, full=prepared.full,
            attachment_url_for_path=attachment_url_for_path if prepared.view == "transcript" else None,
            attachment_url_for_id=attachment_url_for_id if prepared.view == "transcript" else None,
        )
        for row in rows:
            if source_cursor:
                row["sourceCursor"] = source_cursor
            if prepared.view == "prompts":
                title, clipped = bounded_summary_prompt_text(row.get("text", ""))
                row = {key: row[key] for key in ("id", "role", "no", "rawTurnId", "itemId")}
                row["text"] = title + ("…" if clipped else "")
            turns.append(row)
    payload = {
        "runtime_epoch": prepared.runtime_epoch, "revision": prepared.revision,
        "thread_id": prepared.thread_id, "turn_id": prepared.turn_id,
        "view": prepared.view, "target_pending": pending, "turns": turns,
        "older_cursor": page.next_cursor if direction == "desc" else page.backwards_cursor,
        "newer_cursor": page.backwards_cursor if direction == "desc" else page.next_cursor,
        "full_text": None,
    }
    if prepared.full and target is not None:
        item = target.item
        item_type = item.get("type")
        if item_type == "agentMessage":
            text = item.get("text", "")
        elif item_type == "userMessage":
            text = "\n".join(turn.get("text", "") for turn in turns)
        elif item_type == "reasoning":
            text = "\n\n".join(
                str(block.get("thinking", ""))
                for turn in turns for block in turn.get("blocks", [])
                if block.get("kind") == "thinking"
            )
        else:
            text = json.dumps(item, ensure_ascii=False, indent=2)
        payload["full_text"] = str(text)
        payload["turns"] = []
    elif len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > TRANSCRIPT_PAGE_BYTES:
        raise WebRuntimeError("Transcript page is too large.", code="transcript_page_too_large", status=502)
    return payload
