from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PendingThreadwiseSeed:
    thread_id: str
    profile: str = ""
    model: str = ""
    model_provider: str = ""
    memory_mode: str = ""

    @property
    def has_profile_slice(self) -> bool:
        return bool(self.profile)

    @property
    def has_memory_mode(self) -> bool:
        return bool(self.memory_mode)

    @property
    def has_any(self) -> bool:
        return self.has_profile_slice or self.has_memory_mode
