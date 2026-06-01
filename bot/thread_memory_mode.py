from __future__ import annotations

from collections.abc import Mapping
from typing import Any

def thread_memory_mode_from_memories_config(memories_config: Mapping[str, Any] | None) -> str | None:
    if not isinstance(memories_config, Mapping):
        return None
    use_memories = memories_config.get("use_memories")
    generate_memories = memories_config.get("generate_memories")
    if not isinstance(use_memories, bool) or not isinstance(generate_memories, bool):
        return None
    if not use_memories and not generate_memories:
        return "off"
    if use_memories and not generate_memories:
        return "read"
    if use_memories and generate_memories:
        return "read_write"
    return None


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
