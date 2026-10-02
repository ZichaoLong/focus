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
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.document_registry import WebDocumentOperationReceipt
from bot.web_runtime.projection import project_turns
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
    if not full and len(json.dumps(projected, ensure_ascii=False).encode("utf-8")) > 32 * 1024:
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
    cursor = prepared.cursor
    direction = prepared.direction
    if prepared.item_id:
        # A reviewed upstream item anchor is exclusive. Read one predecessor,
        # then read forward after it to include the exact target.
        predecessor = list_thread_items(
            prepared.thread_id,
            **kwargs,
            anchor_item_id=prepared.item_id,
            sort_direction="desc",
            limit=1,
            timeout=remaining(),
        )
        if (not isinstance(predecessor, ThreadItemsPage) or len(predecessor.items) > 1
                or any(entry.turn_id != prepared.turn_id or not entry.item.get("id")
                       for entry in predecessor.items)):
            raise WebRuntimeError("Invalid transcript anchor.", code="transcript_protocol_error", status=502)
        cursor = None
        kwargs["anchor_item_id"] = (
            str(predecessor.items[0].item.get("id", ""))
            if predecessor.items else None
        )
        direction = "asc"
    page = list_thread_items(
        prepared.thread_id,
        **kwargs,
        cursor=cursor,
        sort_direction=direction,
        limit=1 if prepared.full else TRANSCRIPT_PAGE_ITEMS,
        timeout=remaining(),
    )
    remaining()
    if not isinstance(page, ThreadItemsPage) or len(page.items) > (1 if prepared.full else TRANSCRIPT_PAGE_ITEMS):
        raise WebRuntimeError("Invalid transcript page.", code="transcript_protocol_error", status=502)
    if prepared.item_id and (
        not page.items or page.items[0].item.get("id") != prepared.item_id
    ):
        raise WebRuntimeError("This message is no longer available.", code="transcript_item_missing", status=404)
    entries = list(reversed(page.items)) if direction == "desc" else page.items
    turns: list[dict[str, Any]] = []
    for entry in entries:
        if prepared.turn_id and entry.turn_id != prepared.turn_id:
            raise WebRuntimeError("Mismatched transcript turn.", code="transcript_protocol_error", status=502)
        turns.extend(project_transcript_item(
            entry.turn_id, entry.item, full=prepared.full,
            attachment_url_for_path=attachment_url_for_path,
            attachment_url_for_id=attachment_url_for_id,
        ))
    payload = {
        "runtime_epoch": prepared.runtime_epoch,
        "revision": prepared.revision,
        "thread_id": prepared.thread_id,
        "turn_id": prepared.turn_id,
        "turns": turns,
        "older_cursor": page.next_cursor if direction == "desc" else page.backwards_cursor,
        "newer_cursor": page.backwards_cursor if direction == "desc" else page.next_cursor,
        "full_text": None,
    }
    if prepared.full:
        item = page.items[0].item
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
