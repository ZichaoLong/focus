from __future__ import annotations

import pathlib

from bot.adapters.base import ThreadSummary
from bot.runtime_state import BACKEND_THREAD_STATUS_IDLE


def thread_summary_is_provisional(summary: ThreadSummary) -> bool:
    """Return whether a thread summary still looks like a provisional shell."""

    thread_path = str(summary.path or "").strip()
    if not thread_path:
        return False
    try:
        path_exists = pathlib.Path(thread_path).expanduser().exists()
    except OSError:
        return False
    return (
        not path_exists
        and summary.status == BACKEND_THREAD_STATUS_IDLE
        and not str(summary.preview or "").strip()
    )
