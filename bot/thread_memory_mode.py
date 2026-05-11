from __future__ import annotations

from dataclasses import dataclass
from typing import Any

THREAD_MEMORY_MODE_OFF = "off"
THREAD_MEMORY_MODE_READ = "read"
THREAD_MEMORY_MODE_READ_WRITE = "read_write"

THREAD_MEMORY_MODES = (
    THREAD_MEMORY_MODE_OFF,
    THREAD_MEMORY_MODE_READ,
    THREAD_MEMORY_MODE_READ_WRITE,
)

@dataclass(frozen=True, slots=True)
class ResolvedThreadMemoryMode:
    mode: str
    use_memories: bool
    generate_memories: bool


def normalize_thread_memory_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in THREAD_MEMORY_MODES:
        raise ValueError("memory mode 仅支持：`off`、`read`、`read_write`")
    return normalized


def resolve_thread_memory_mode(mode: str) -> ResolvedThreadMemoryMode:
    normalized = normalize_thread_memory_mode(mode)
    if normalized == THREAD_MEMORY_MODE_OFF:
        return ResolvedThreadMemoryMode(
            mode=normalized,
            use_memories=False,
            generate_memories=False,
        )
    if normalized == THREAD_MEMORY_MODE_READ:
        return ResolvedThreadMemoryMode(
            mode=normalized,
            use_memories=True,
            generate_memories=False,
        )
    return ResolvedThreadMemoryMode(
        mode=normalized,
        use_memories=True,
        generate_memories=True,
    )


def build_thread_memory_config_override(
    mode: str,
    *,
    profile_name_hint: str = "",
) -> dict[str, Any]:
    del profile_name_hint
    resolved = resolve_thread_memory_mode(mode)
    memories_config = {
        "use_memories": resolved.use_memories,
        "generate_memories": resolved.generate_memories,
    }
    return {
        "memories": dict(memories_config),
    }


def deep_merge_config_overrides(*parts: dict[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for part in parts:
        if not isinstance(part, dict):
            continue
        _deep_merge_into(merged, part)
    return merged


def _deep_merge_into(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_into(target[key], value)
            continue
        if isinstance(value, dict):
            target[key] = {nested_key: nested_value for nested_key, nested_value in value.items()}
            continue
        target[key] = value
