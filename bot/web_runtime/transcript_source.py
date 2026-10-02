"""Request-local locators for rereading an upstream item page unchanged.

The envelope wraps, but never synthesizes, the opaque upstream cursor. It is
not an authorization receipt; thread/document admission still runs on reads.
"""

from __future__ import annotations

import json
from typing import Any

from bot.web_runtime.contract import WebRuntimeError


def encode_transcript_source(cursor: str | None, turn_id: str | None, direction: str, limit: int) -> str | None:
    if cursor is None:
        return None
    return json.dumps([cursor, turn_id, direction, limit], separators=(",", ":"))


def decode_transcript_source(value: str) -> dict[str, Any]:
    try:
        parts = json.loads(value)
        if not isinstance(parts, list) or len(parts) != 4:
            raise ValueError
        cursor, turn_id, direction, limit = parts
        if not isinstance(cursor, str) or not cursor or cursor.strip() != cursor or len(cursor) > 4096:
            raise ValueError
        if turn_id is not None and (not isinstance(turn_id, str) or not turn_id or turn_id.strip() != turn_id or len(turn_id) > 4096):
            raise ValueError
        if direction not in ("asc", "desc") or type(limit) is not int or limit not in (40, 100):
            raise ValueError
        return {"cursor": cursor, "turn_id": turn_id, "sort_direction": direction, "limit": limit}
    except (TypeError, ValueError, RecursionError) as exc:
        raise WebRuntimeError("Invalid transcript source locator.", code="invalid_transcript_query", status=400) from exc
