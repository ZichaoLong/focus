from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PendingThreadwiseSeed:
    thread_id: str
    memory_mode: str = ""

    @property
    def has_memory_mode(self) -> bool:
        return bool(self.memory_mode)

    @property
    def has_any(self) -> bool:
        return self.has_memory_mode
