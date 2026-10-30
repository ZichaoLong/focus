"""Retention preferences backed solely by the instance's codex.yaml.

Legacy JSON is consumed once under the config lock, never a parallel source.
See docs/contracts/data-retention.zh-CN.md for migration and failure semantics.
"""

from __future__ import annotations

import json
import pathlib
from contextlib import contextmanager

import yaml

from bot.atomic_file import atomic_write_text
from bot.codex_config import CodexConfig
from bot.config import load_config_file
from bot.data_retention_contract import DataRetentionPolicy
from bot.file_lock import acquire_file_lock, open_lock_file, release_file_lock
from bot.instance_layout import (
    current_instance_name,
    infer_instance_name_from_data_dir,
    resolve_instance_paths,
)

_CONFIG_KEYS = {
    "records_days": "records_retention_days",
    "attachments_days": "attachments_retention_days",
}


class DataRetentionStore:
    def __init__(self, data_dir: pathlib.Path, *, config_dir: pathlib.Path | None = None) -> None:
        if config_dir is None:
            instance = infer_instance_name_from_data_dir(data_dir) or current_instance_name()
            config_dir = resolve_instance_paths(instance).config_dir
        self.path = pathlib.Path(config_dir) / "codex.yaml"
        self._legacy_path = pathlib.Path(data_dir) / "data_retention.json"

    @staticmethod
    def _policy(raw: dict) -> DataRetentionPolicy:
        config = CodexConfig.from_dict(raw)
        return DataRetentionPolicy(config.records_retention_days, config.attachments_retention_days)

    def _read(self) -> dict:
        raw = load_config_file("codex", directory=self.path.parent)
        self._policy(raw)
        return raw

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open_lock_file(self.path.with_suffix(".yaml.lock")) as handle:
            acquire_file_lock(handle, blocking=True)
            try:
                yield
            finally:
                release_file_lock(handle)

    def _merge_legacy(self, raw: dict) -> dict:
        # Both explicit YAML fields also form the crash-recovery checkpoint.
        # Once committed, even stale/corrupt legacy bytes cannot override them.
        if all(key in raw for key in _CONFIG_KEYS.values()):
            return raw
        try:
            legacy = json.loads(self._legacy_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return raw
        if (not isinstance(legacy, dict) or set(legacy) != {"schema_version", *_CONFIG_KEYS}
                or type(legacy["schema_version"]) is not int or legacy["schema_version"] != 1):
            raise ValueError("Invalid data_retention.json schema; retention migration is unavailable.")
        policy = DataRetentionPolicy(legacy["records_days"], legacy["attachments_days"])
        return {**{_CONFIG_KEYS[key]: value for key, value in policy.payload().items()}, **raw}

    def _write(self, raw: dict) -> None:
        self._policy(raw)
        atomic_write_text(self.path, yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), mode=0o600)

    def load(self) -> DataRetentionPolicy:
        if not self._legacy_path.exists():
            return self._policy(self._read())
        with self._locked():
            raw = self._read()
            migrated = self._merge_legacy(raw)
            if migrated != raw:
                self._write(migrated)
            self._legacy_path.unlink(missing_ok=True)
            return self._policy(migrated)

    def update(self, changes: dict[str, object]) -> DataRetentionPolicy:
        if not changes or not set(changes) <= _CONFIG_KEYS.keys():
            raise ValueError("Only records_days and attachments_days may be changed.")
        DataRetentionPolicy(**changes)
        with self._locked():
            raw = self._read()
            raw.update({_CONFIG_KEYS[key]: value for key, value in changes.items()})
            raw = self._merge_legacy(raw)
            self._write(raw)
            self._legacy_path.unlink(missing_ok=True)
            return self._policy(raw)
