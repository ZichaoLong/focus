"""One durable, instance-wide history retention preference.

The store is shared with diagnostic writers in other processes. Missing means
defaults; corruption never authorizes deletion. See the data-retention contract.
"""

from __future__ import annotations

import json
import pathlib

from bot.atomic_file import atomic_write_text
from bot.data_retention_contract import DataRetentionPolicy
from bot.file_lock import acquire_file_lock, open_lock_file, release_file_lock


class DataRetentionStore:
    def __init__(self, data_dir: pathlib.Path) -> None:
        self._path = pathlib.Path(data_dir) / "data_retention.json"

    def load(self) -> DataRetentionPolicy:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return DataRetentionPolicy()
        if (not isinstance(raw, dict) or set(raw) != {"schema_version", "records_days", "attachments_days"}
                or type(raw["schema_version"]) is not int or raw["schema_version"] != 1):
            raise ValueError("Invalid data_retention.json schema; retention is unavailable.")
        return DataRetentionPolicy(raw["records_days"], raw["attachments_days"])

    def update(self, changes: dict[str, object]) -> DataRetentionPolicy:
        if not changes or not set(changes) <= {"records_days", "attachments_days"}:
            raise ValueError("Only records_days and attachments_days may be changed.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open_lock_file(self._path.with_suffix(".lock")) as handle:
            acquire_file_lock(handle, blocking=True)
            try:
                values = {**self.load().payload(), **changes}
                policy = DataRetentionPolicy(**values)
                atomic_write_text(self._path, json.dumps({"schema_version": 1, **policy.payload()}), mode=0o600)
                return policy
            finally:
                release_file_lock(handle)
