"""Values shared by Focus history retention owners.

See docs/contracts/data-retention.zh-CN.md for scope and deletion semantics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

RETENTION_DAY_OPTIONS = (7, 30, 90)
DEFAULT_RETENTION_DAYS = 30
RETENTION_SWEEP_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class DataRetentionPolicy:
    records_days: int = DEFAULT_RETENTION_DAYS
    attachments_days: int = DEFAULT_RETENTION_DAYS

    def __post_init__(self) -> None:
        for value in (self.records_days, self.attachments_days):
            if type(value) is not int or value not in RETENTION_DAY_OPTIONS:
                raise ValueError("Retention must be 7, 30 or 90 days.")

    def payload(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DataPruneResult:
    records: int = 0
    bytes_freed: int = 0

    def payload(self) -> dict[str, int]:
        return asdict(self)
