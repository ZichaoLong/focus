"""Small failure records for the wrapper/proxy, independent of RPC authority."""

from __future__ import annotations

import json
import os
import pathlib
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

from bot.diagnostic_logs import append_log, prune_logs
from bot.instance_layout import current_instance_name
from bot.version import __version__

_REDACT = re.compile(
    r"(?i)(bearer\s+)[^\s,;\"']+|"
    r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|password|secret)"
    r"[\"']?\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s,;\"'}]+"
)


def _summary(value: object, limit: int = 768) -> str:
    text = str(value if value is not None else "")[:8192]
    text = _REDACT.sub(lambda match: (match[1] or match[2]) + "[redacted]", text)
    return " ".join(text.split())[:limit]


class FcodexDiagnostics:
    def __init__(self, data_dir: pathlib.Path, *, instance_name: str = "") -> None:
        self.data_dir = pathlib.Path(data_dir)
        self.instance = instance_name or current_instance_name(data_dir=data_dir)
        self.backend_version = ""
        self._lock = threading.Lock()
        self._recent: OrderedDict[tuple[str, ...], tuple[float, int, dict]] = (
            OrderedDict()
        )
        try:
            prune_logs(self.data_dir)
        except Exception:
            pass

    def record(
        self,
        stage: str,
        *,
        method: str = "",
        thread_id: str = "",
        code: object = None,
        message: object = "",
        request_id: object = None,
    ) -> None:
        try:
            now = time.monotonic()
            method = _summary(method, 128)
            thread_id = _summary(thread_id, 128)
            code = _summary(code, 96)
            message = _summary(message)
            key = (stage, method, thread_id, code, message)
            with self._lock:
                previous = self._recent.pop(key, None)
                if previous is not None and now - previous[0] < 60:
                    self._recent[key] = (previous[0], previous[1] + 1, previous[2])
                    return
                record = {
                    "at": datetime.now(timezone.utc).isoformat(),
                    "instance": self.instance,
                    "pid": os.getpid(),
                    "focus_version": __version__,
                    "backend_version": _summary(self.backend_version, 256),
                    "stage": stage,
                    "method": method,
                    "thread_id": thread_id,
                    "request_id": _summary(request_id, 128),
                    "code": code,
                    "message": message,
                    "suppressed": previous[1] if previous else 0,
                }
                if not self._write(record):
                    # A transient full/busy sink must not suppress the next
                    # useful failure after storage becomes writable again.
                    if previous is not None:
                        self._recent[key] = (previous[0], previous[1] + 1, previous[2])
                    return
                self._recent[key] = (now, 0, record)
                if len(self._recent) > 128:
                    _, (_, count, older) = self._recent.popitem(last=False)
                    if count:
                        self._write({**older, "suppressed": count})
        except Exception:
            pass

    def _write(self, record: dict) -> bool:
        return append_log(
            self.data_dir, "fcodex.log", json.dumps(record, ensure_ascii=False) + "\n"
        )

    def close(self) -> None:
        try:
            with self._lock:
                for _, count, record in self._recent.values():
                    if count:
                        self._write({**record, "suppressed": count})
                self._recent.clear()
        except Exception:
            pass
