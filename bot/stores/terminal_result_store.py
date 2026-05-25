from __future__ import annotations

import json
import os
import pathlib
import threading
from dataclasses import asdict, dataclass

_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class TerminalResultRecord:
    message_id: str
    execution_message_id: str
    final_reply_text: str
    recorded_at: float


class TerminalResultStore:
    def __init__(self, data_dir: pathlib.Path) -> None:
        self._data_dir = pathlib.Path(data_dir)
        self._lock = threading.Lock()

    def upsert(self, record: TerminalResultRecord) -> None:
        normalized = self._normalize_record(record)
        if not normalized.message_id or not normalized.final_reply_text:
            return
        with self._lock:
            records = [item for item in self._read_all() if item.message_id != normalized.message_id]
            records.append(normalized)
            self._write_all(records)

    def get(self, message_id: str) -> str:
        normalized_message_id = str(message_id or "").strip()
        if not normalized_message_id:
            return ""
        with self._lock:
            for item in self._read_all():
                if item.message_id == normalized_message_id:
                    return item.final_reply_text
        return ""

    def has_execution_result(self, *, execution_message_id: str, final_reply_text: str) -> bool:
        normalized_execution_message_id = str(execution_message_id or "").strip()
        normalized_text = str(final_reply_text or "").strip()
        if not normalized_execution_message_id or not normalized_text:
            return False
        with self._lock:
            return any(
                item.execution_message_id == normalized_execution_message_id
                and item.final_reply_text == normalized_text
                for item in self._read_all()
            )

    def list_all(self) -> tuple[TerminalResultRecord, ...]:
        with self._lock:
            items = sorted(
                self._read_all(),
                key=lambda item: (item.recorded_at, item.message_id),
            )
        return tuple(items)

    def _file_path(self) -> pathlib.Path:
        return self._data_dir / "terminal_results.json"

    def _read_all(self) -> list[TerminalResultRecord]:
        path = self._file_path()
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("terminal_results.json 格式损坏：顶层必须是对象。")
        schema_version = int(raw.get("schema_version", 0) or 0)
        if schema_version != _SCHEMA_VERSION:
            raise RuntimeError(
                f"terminal_results.json schema_version={schema_version}，期望 {_SCHEMA_VERSION}。"
            )
        raw_items = raw.get("results")
        if not isinstance(raw_items, list):
            raise RuntimeError("terminal_results.json 格式损坏：results 必须是数组。")
        return [self._record_from_dict(item) for item in raw_items]

    def _write_all(self, records: list[TerminalResultRecord]) -> None:
        path = self._file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "results": [asdict(record) for record in records],
        }
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)

    @staticmethod
    def _normalize_record(record: TerminalResultRecord) -> TerminalResultRecord:
        return TerminalResultRecord(
            message_id=str(record.message_id or "").strip(),
            execution_message_id=str(record.execution_message_id or "").strip(),
            final_reply_text=str(record.final_reply_text or "").strip(),
            recorded_at=float(record.recorded_at),
        )

    @classmethod
    def _record_from_dict(cls, raw: object) -> TerminalResultRecord:
        if not isinstance(raw, dict):
            raise RuntimeError("terminal_results.json 格式损坏：result 项必须是对象。")
        try:
            return cls._normalize_record(
                TerminalResultRecord(
                    message_id=str(raw["message_id"]),
                    execution_message_id=str(raw.get("execution_message_id", "")),
                    final_reply_text=str(raw["final_reply_text"]),
                    recorded_at=float(raw["recorded_at"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("terminal_results.json 格式损坏：result 项字段非法。") from exc
