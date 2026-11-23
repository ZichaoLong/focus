"""Version-one mobile reading projection of already admitted transcript rows."""

import time
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

from bot.adapters.base import ThreadSnapshot
from bot.codex_protocol.client import CodexRpcError


def record_states(threads: list[str], read: Callable[..., ThreadSnapshot], generation: Callable[[], int]) -> list[str]:
    """Inspect already saved ids without loading a thread, its turns or a browser selection."""
    states = ["unknown"] * len(threads)
    try:
        epoch = generation()
    except RuntimeError:
        return states
    deadline = time.monotonic() + 5
    for i, thread in enumerate(threads):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or epoch <= 0:
            break
        try:
            snapshot = read(
                thread, include_turns=False, timeout=min(remaining, 2),
                expected_connection_generation=epoch,
            )
        except CodexRpcError as exc:
            message = str(exc.error.get("message") or "").strip()
            # Direct thread/read searches both persisted directories before its loaded-thread fallback.
            if exc.method == "thread/read" and message in {
                f"thread not found: {thread}", f"thread not loaded: {thread}",
                f"no rollout found for thread id {thread}",
            }:
                states[i] = "missing"
        except (OSError, RuntimeError, ValueError):
            continue
        else:
            path = snapshot.summary.path
            if snapshot.summary.thread_id == thread and path and not snapshot.summary.ephemeral:
                parent = PurePosixPath(path.replace("\\", "/")).parent.name
                states[i] = "archived" if parent == "archived_sessions" else "present"
    try:
        if epoch == generation():
            return states
    except RuntimeError:
        pass
    return ["unknown"] * len(threads)


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
