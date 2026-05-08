"""
Machine-global thread-wise memory mode store.

Each record is keyed by `thread_id` and describes which thread-wise memory mode
should be applied the next time that thread is resumed from an unloaded state.
"""

from __future__ import annotations

import json
import os
import pathlib
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Iterator

from bot.file_lock import acquire_file_lock, release_file_lock
from bot.instance_layout import global_data_dir
from bot.thread_memory_mode import normalize_thread_memory_mode


@dataclass(frozen=True, slots=True)
class ThreadMemoryModeRecord:
    thread_id: str
    mode: str
    updated_at: float


class ThreadMemoryModeStore:
    def __init__(self, root_dir: pathlib.Path | None = None) -> None:
        self._root_dir = pathlib.Path(root_dir) if root_dir is not None else global_data_dir()
        self._lock = threading.Lock()

    def _file_path(self) -> pathlib.Path:
        return self._root_dir / "thread_memory_modes.json"

    def _lock_path(self) -> pathlib.Path:
        return self._root_dir / "thread_memory_modes.lock"

    def load(self, thread_id: str) -> ThreadMemoryModeRecord | None:
        normalized_thread_id = self._normalize_thread_id(thread_id)
        if not normalized_thread_id:
            return None
        with self._locked_data() as data:
            raw = data.get(normalized_thread_id)
            record = self._record_from_data(normalized_thread_id, raw)
            if record is None and normalized_thread_id in data:
                data.pop(normalized_thread_id, None)
                self._write_all_unlocked(data)
            return record

    def save(self, thread_id: str, *, mode: str) -> ThreadMemoryModeRecord:
        normalized_thread_id = self._normalize_thread_id(thread_id)
        normalized_mode = normalize_thread_memory_mode(mode)
        if not normalized_thread_id:
            raise ValueError("thread_id 不能为空。")
        record = ThreadMemoryModeRecord(
            thread_id=normalized_thread_id,
            mode=normalized_mode,
            updated_at=time.time(),
        )
        with self._locked_data() as data:
            data[normalized_thread_id] = self._serialize_record(record)
            self._write_all_unlocked(data)
        return record

    def clear(self, thread_id: str) -> bool:
        normalized_thread_id = self._normalize_thread_id(thread_id)
        if not normalized_thread_id:
            return False
        with self._locked_data() as data:
            if normalized_thread_id not in data:
                return False
            data.pop(normalized_thread_id, None)
            self._write_all_unlocked(data)
        return True

    @contextmanager
    def _locked_data(self) -> Iterator[dict[str, dict]]:
        with self._lock:
            lock_path = self._lock_path()
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a+", encoding="utf-8") as lock_file:
                acquire_file_lock(lock_file, blocking=True)
                try:
                    yield self._read_all_unlocked()
                finally:
                    release_file_lock(lock_file)

    @staticmethod
    def _normalize_thread_id(thread_id: str) -> str:
        return str(thread_id or "").strip()

    @staticmethod
    def _record_from_data(thread_id: str, raw: object) -> ThreadMemoryModeRecord | None:
        if not isinstance(raw, dict):
            return None
        try:
            mode = normalize_thread_memory_mode(str(raw.get("mode", "") or ""))
            updated_at = float(raw.get("updated_at") or 0.0)
        except (TypeError, ValueError):
            return None
        return ThreadMemoryModeRecord(
            thread_id=thread_id,
            mode=mode,
            updated_at=updated_at,
        )

    @staticmethod
    def _serialize_record(record: ThreadMemoryModeRecord) -> dict[str, object]:
        return asdict(record)

    def _read_all_unlocked(self) -> dict[str, dict]:
        path = self._file_path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(key).strip(): value
            for key, value in raw.items()
            if str(key).strip()
        }

    def _write_all_unlocked(self, data: dict[str, dict]) -> None:
        path = self._file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".json.tmp")
        rendered = {str(key): value for key, value in sorted(data.items())}
        tmp_path.write_text(json.dumps(rendered, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
