"""
Read the shared user-level CODEX_HOME/config.toml for thread-wise profile slices.

This is an intentional feishu-codex contract choice:

- explicit thread-wise profile mutation resolves against the shared user-level
  config only
- it deliberately does not follow per-cwd / project-local config layers used by
  upstream bare Codex

The app-server's thread-start / thread-resume protocol can accept explicit
`model` + `modelProvider` fields. feishu-codex uses this local reader to pin a
thread-stable profile slice at those RPC boundaries.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedProfileConfig:
    model: str = ""
    model_provider: str = ""


def resolve_profile_from_codex_config(profile_name: str) -> ResolvedProfileConfig:
    """Extract the effective model/model_provider for *profile_name*.

    This intentionally mirrors only the shared user-level subset that matters
    for feishu-codex thread-wise resume persistence:

    - profile.model -> top-level model
    - profile.model_provider -> top-level model_provider

    It does not load or merge per-project config from cwd.
    """
    if not profile_name:
        return ResolvedProfileConfig()
    config_path = _codex_config_path()
    if config_path is None:
        return ResolvedProfileConfig()
    try:
        with open(config_path, "rb") as fh:
            config = tomllib.load(fh)
    except Exception:
        logger.debug("failed to read %s", config_path, exc_info=True)
        return ResolvedProfileConfig()
    profile = (config.get("profiles") or {}).get(profile_name)
    if not isinstance(profile, dict):
        return ResolvedProfileConfig()
    return ResolvedProfileConfig(
        model=_read_string(profile, "model") or _read_string(config, "model"),
        model_provider=(
            _read_string(profile, "model_provider", "modelProvider")
            or _read_string(config, "model_provider", "modelProvider")
        ),
    )


def _codex_config_path() -> Path | None:
    codex_home_env = os.environ.get("CODEX_HOME", "").strip()
    codex_home = Path(codex_home_env) if codex_home_env else Path.home() / ".codex"
    config_path = codex_home / "config.toml"
    return config_path if config_path.is_file() else None


def _read_string(mapping: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""
