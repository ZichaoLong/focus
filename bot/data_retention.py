"""Schedule the existing data owners' bounded-history maintenance.

Owns only the sweep's serialization and worker lifetime, not copies of records.
Owner callbacks execute outside RuntimeLoop, under service ingress ownership.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping

from bot.data_retention_contract import DataPruneResult, DataRetentionPolicy, RETENTION_SWEEP_SECONDS
from bot.stores.data_retention_store import DataRetentionStore

logger = logging.getLogger(__name__)
PruneData = Callable[[DataRetentionPolicy, float], DataPruneResult]


class DataRetentionService:
    def __init__(self, store: DataRetentionStore, owners: Mapping[str, PruneData]) -> None:
        self._store = store
        self._owners = dict(owners)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def policy(self) -> dict[str, int]:
        return self._store.load().payload()

    def update(self, changes: dict[str, object]) -> dict[str, int]:
        with self._lock:
            return self._store.update(changes).payload()

    def prune(self, *, now: float | None = None) -> dict[str, object]:
        with self._lock:
            policy = self._store.load()
            timestamp = time.time() if now is None else now
            results: dict[str, dict[str, int]] = {}
            errors: dict[str, str] = {}
            for name, prune in self._owners.items():
                try:
                    results[name] = prune(policy, timestamp).payload()
                except Exception:
                    logger.exception("Data retention failed for %s", name)
                    errors[name] = "cleanup_failed"
            return {"policy": policy.payload(), "results": results, "errors": errors,
                    "records": sum(value["records"] for value in results.values()),
                    "bytes_freed": sum(value["bytes_freed"] for value in results.values())}

    def start(self, run_owned: Callable[[], object]) -> None:
        if self._worker is not None:
            return
        self._stop.clear()

        def maintain() -> None:
            while not self._stop.wait(RETENTION_SWEEP_SECONDS):
                try:
                    run_owned()
                except Exception:
                    logger.warning("Data retention sweep unavailable", exc_info=True)

        self._worker = threading.Thread(target=maintain, name="focus-data-retention", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=10)
            if self._worker.is_alive():
                raise RuntimeError("Data retention worker did not stop.")
            self._worker = None
