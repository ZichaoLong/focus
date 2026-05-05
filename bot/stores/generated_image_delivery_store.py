from __future__ import annotations

import json
import os
import pathlib
import threading
from dataclasses import asdict, dataclass

_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GeneratedImageDeliveryRecord:
    sender_id: str
    chat_id: str
    thread_id: str
    turn_id: str
    item_id: str
    local_path: str
    message_id: str
    delivered_at: float


class GeneratedImageDeliveryStore:
    def __init__(self, data_dir: pathlib.Path) -> None:
        self._data_dir = pathlib.Path(data_dir)
        self._lock = threading.Lock()

    def has_delivery(
        self,
        *,
        sender_id: str,
        chat_id: str,
        thread_id: str,
        turn_id: str,
        item_id: str,
    ) -> bool:
        key = self._delivery_key(
            sender_id=sender_id,
            chat_id=chat_id,
            thread_id=thread_id,
            turn_id=turn_id,
            item_id=item_id,
        )
        if key is None:
            return False
        with self._lock:
            return any(self._record_key(record) == key for record in self._read_all())

    def record(self, record: GeneratedImageDeliveryRecord) -> None:
        normalized = self._normalize_record(record)
        key = self._record_key(normalized)
        with self._lock:
            records = [item for item in self._read_all() if self._record_key(item) != key]
            records.append(normalized)
            self._write_all(records)

    def list_all(self) -> tuple[GeneratedImageDeliveryRecord, ...]:
        with self._lock:
            items = sorted(
                self._read_all(),
                key=lambda item: (
                    item.sender_id,
                    item.chat_id,
                    item.thread_id,
                    item.turn_id,
                    item.item_id,
                ),
            )
        return tuple(items)

    def _file_path(self) -> pathlib.Path:
        return self._data_dir / "generated_image_deliveries.json"

    def _read_all(self) -> list[GeneratedImageDeliveryRecord]:
        path = self._file_path()
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise RuntimeError("generated_image_deliveries.json 格式损坏：顶层必须是对象。")
        schema_version = int(raw.get("schema_version", 0) or 0)
        if schema_version != _SCHEMA_VERSION:
            raise RuntimeError(
                f"generated_image_deliveries.json schema_version={schema_version}，期望 {_SCHEMA_VERSION}。"
            )
        raw_items = raw.get("deliveries")
        if not isinstance(raw_items, list):
            raise RuntimeError("generated_image_deliveries.json 格式损坏：deliveries 必须是数组。")
        return [self._record_from_dict(item) for item in raw_items]

    def _write_all(self, records: list[GeneratedImageDeliveryRecord]) -> None:
        path = self._file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "deliveries": [asdict(record) for record in records],
        }
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)

    @staticmethod
    def _delivery_key(
        *,
        sender_id: str,
        chat_id: str,
        thread_id: str,
        turn_id: str,
        item_id: str,
    ) -> tuple[str, str, str, str, str] | None:
        normalized_sender_id = str(sender_id or "").strip()
        normalized_chat_id = str(chat_id or "").strip()
        normalized_thread_id = str(thread_id or "").strip()
        normalized_turn_id = str(turn_id or "").strip()
        normalized_item_id = str(item_id or "").strip()
        if not (
            normalized_sender_id
            and normalized_chat_id
            and normalized_thread_id
            and normalized_turn_id
            and normalized_item_id
        ):
            return None
        return (
            normalized_sender_id,
            normalized_chat_id,
            normalized_thread_id,
            normalized_turn_id,
            normalized_item_id,
        )

    @classmethod
    def _record_key(cls, record: GeneratedImageDeliveryRecord) -> tuple[str, str, str, str, str]:
        key = cls._delivery_key(
            sender_id=record.sender_id,
            chat_id=record.chat_id,
            thread_id=record.thread_id,
            turn_id=record.turn_id,
            item_id=record.item_id,
        )
        assert key is not None
        return key

    @staticmethod
    def _normalize_record(record: GeneratedImageDeliveryRecord) -> GeneratedImageDeliveryRecord:
        return GeneratedImageDeliveryRecord(
            sender_id=str(record.sender_id or "").strip(),
            chat_id=str(record.chat_id or "").strip(),
            thread_id=str(record.thread_id or "").strip(),
            turn_id=str(record.turn_id or "").strip(),
            item_id=str(record.item_id or "").strip(),
            local_path=str(record.local_path or "").strip(),
            message_id=str(record.message_id or "").strip(),
            delivered_at=float(record.delivered_at),
        )

    @classmethod
    def _record_from_dict(cls, raw: object) -> GeneratedImageDeliveryRecord:
        if not isinstance(raw, dict):
            raise RuntimeError("generated_image_deliveries.json 格式损坏：delivery 项必须是对象。")
        try:
            return cls._normalize_record(
                GeneratedImageDeliveryRecord(
                    sender_id=str(raw["sender_id"]),
                    chat_id=str(raw["chat_id"]),
                    thread_id=str(raw["thread_id"]),
                    turn_id=str(raw["turn_id"]),
                    item_id=str(raw["item_id"]),
                    local_path=str(raw.get("local_path", "")),
                    message_id=str(raw.get("message_id", "")),
                    delivered_at=float(raw["delivered_at"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("generated_image_deliveries.json 格式损坏：delivery 项字段非法。") from exc
