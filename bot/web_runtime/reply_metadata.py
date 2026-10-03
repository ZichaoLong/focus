"""Per-message timing from item notifications; never synthesized from turn time."""

from dataclasses import dataclass
from typing import Any

REPLY_METADATA_KEY = "_focus_reply_metadata"


@dataclass(frozen=True, slots=True)
class ReplyMetadata:
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    state: str = "unknown"


def notification_reply_metadata(method: str, params: dict[str, Any]) -> ReplyMetadata:
    def timestamp(key: str) -> int | None:
        value = params.get(key)
        return value if type(value) is int and 0 <= value <= 8_640_000_000_000_000 else None

    return ReplyMetadata(
        timestamp("startedAtMs"), timestamp("completedAtMs"),
        "complete" if method == "item/completed" else "generating",
    )


def merge_reply_metadata(previous: dict[str, Any], incoming: dict[str, Any]) -> None:
    old = previous.get(REPLY_METADATA_KEY)
    new = incoming.get(REPLY_METADATA_KEY)
    if not isinstance(old, ReplyMetadata):
        return
    if not isinstance(new, ReplyMetadata):
        incoming[REPLY_METADATA_KEY] = old
        return
    incoming[REPLY_METADATA_KEY] = ReplyMetadata(
        new.started_at_ms if new.started_at_ms is not None else old.started_at_ms,
        new.completed_at_ms if new.completed_at_ms is not None else old.completed_at_ms,
        "complete" if old.state == "complete" else new.state,
    )


def project_reply_metadata(
    item: dict[str, Any], *, started_at_ms: int | None = None, completed_at_ms: int | None = None,
    turn_status: str = "",
) -> dict[str, Any]:
    cached = item.get(REPLY_METADATA_KEY)
    if not isinstance(cached, ReplyMetadata):
        cached = ReplyMetadata(started_at_ms, completed_at_ms,
            "complete" if completed_at_ms is not None else "unknown")
    state = cached.state
    if state == "generating" and turn_status in {"completed", "interrupted", "failed"}:
        state = "unknown"
    return {
        "state": state,
        **({"startedAtMs": cached.started_at_ms} if cached.started_at_ms is not None else {}),
        **({"completedAtMs": cached.completed_at_ms} if cached.completed_at_ms is not None else {}),
    }
