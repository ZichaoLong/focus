"""Version-one mobile reading projection of already admitted transcript rows."""

from typing import Any


def reading_rows(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for turn in turns:
        key = {"turn": turn["rawTurnId"], "item": turn["itemId"]}
        if turn.get("contentDeferred") and turn.get("tools"):
            rows.append({**key, "kind": "tool"})
            continue
        role = turn["role"]
        text = turn.get("text") or ""
        if role in {"user", "assistant"} and text.strip():
            rows.append({**key, "kind": role, "text": text,
                         "partial": turn.get("reply", {}).get("state") == "generating"})
        elif role != "assistant" or any(
            block.get("kind") not in {"text", "thinking"} or str(block.get("thinking", "")).strip()
            for block in turn.get("blocks", [])
        ) or (turn.get("thinking") or "").strip():
            # Preserve the position of a visible separator without archiving its payload.
            rows.append({**key, "kind": "break"})
    return rows
