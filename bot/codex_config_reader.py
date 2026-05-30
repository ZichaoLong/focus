"""
Read shared user-level CODEX_HOME config for thread-wise profile slices.

This is an intentional feishu-codex contract choice:

- explicit thread-wise profile mutation resolves against the shared user-level
  CODEX_HOME only
- it deliberately does not follow per-cwd / project-local config layers used by
  upstream bare Codex

Upstream profile-v2 now maps `--profile work` to `${CODEX_HOME}/work.config.toml`
layered on top of `${CODEX_HOME}/config.toml`. feishu-codex keeps the same
thread-wise contract boundary, but only materializes the effective
`model` / `model_provider` slice locally and never forwards legacy
`config.profile` to app-server.
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re

logger = logging.getLogger(__name__)

_PROFILE_V2_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class ResolvedProfileConfig:
    model: str = ""
    model_provider: str = ""


@dataclass(frozen=True)
class _LoadedUserConfig:
    path: Path
    data: dict[str, object]


def list_profile_v2_names() -> list[str]:
    codex_home = _codex_home_dir()
    if codex_home is None or not codex_home.is_dir():
        return []
    names: list[str] = []
    for path in sorted(codex_home.glob("*.config.toml")):
        if not path.is_file():
            continue
        if path.name == "config.toml":
            continue
        if not path.name.endswith(".config.toml"):
            continue
        name = path.name[: -len(".config.toml")]
        if _is_valid_profile_v2_name(name):
            names.append(name)
    return names


def resolve_profile_from_codex_config(profile_name: str) -> ResolvedProfileConfig:
    """Extract the effective model/model_provider for *profile_name*.

    This intentionally mirrors only the shared user-level subset that matters
    for feishu-codex thread-wise resume persistence:

    - selected `${CODEX_HOME}/<name>.config.toml`
    - falling back to top-level `${CODEX_HOME}/config.toml`

    It does not load or merge per-project config from cwd.
    """
    normalized_profile = _normalize_profile_v2_name(profile_name)
    if not normalized_profile:
        return ResolvedProfileConfig()
    layers = _load_profile_v2_layers(normalized_profile)
    if layers is None:
        return ResolvedProfileConfig()
    base_config, profile_config = layers
    return ResolvedProfileConfig(
        model=(
            _read_string(profile_config.data, "model")
            or _read_string(base_config.data, "model")
        ),
        model_provider=(
            _read_string(profile_config.data, "model_provider", "modelProvider")
            or _read_string(base_config.data, "model_provider", "modelProvider")
        ),
    )


def resolve_profile_model_metadata(profile_name: str) -> dict[str, object] | None:
    """Load optional model metadata for *profile_name* from its model catalog.

    The returned mapping is normalized to always include a `model` key when a
    match is found so callers can splice it directly into `model/list`
    responses.
    """
    normalized_profile = _normalize_profile_v2_name(profile_name)
    if not normalized_profile:
        return None
    layers = _load_profile_v2_layers(normalized_profile)
    if layers is None:
        return None
    base_config, profile_config = layers

    model_name = (
        _read_string(profile_config.data, "model")
        or _read_string(base_config.data, "model")
    )
    if not model_name:
        return None

    catalog_path_raw = (
        _read_string(profile_config.data, "model_catalog_json", "modelCatalogJson")
        or _read_string(base_config.data, "model_catalog_json", "modelCatalogJson")
    )
    if not catalog_path_raw:
        return None

    catalog_path = Path(catalog_path_raw).expanduser()
    if not catalog_path.is_absolute():
        catalog_path = base_config.path.parent / catalog_path
    try:
        with open(catalog_path, "r", encoding="utf-8") as fh:
            catalog = json.load(fh)
    except Exception:
        logger.debug("failed to read %s", catalog_path, exc_info=True)
        return None

    models = catalog.get("models") if isinstance(catalog, dict) else None
    if not isinstance(models, list):
        return None
    for item in models:
        if not isinstance(item, dict):
            continue
        slug = _read_string(item, "slug", "model")
        display_name = _read_string(item, "display_name", "displayName")
        if model_name not in {slug, display_name}:
            continue
        normalized = dict(item)
        normalized["model"] = slug or model_name
        if display_name:
            normalized["displayName"] = display_name
            normalized["display_name"] = display_name
        return normalized
    return None


def _load_profile_v2_layers(profile_name: str) -> tuple[_LoadedUserConfig, _LoadedUserConfig] | None:
    base_config = _load_base_user_config()
    if base_config is None:
        return None
    _raise_if_matching_legacy_profile_conflict(base_config, profile_name)
    profile_config = _load_selected_profile_v2(profile_name)
    if profile_config is None:
        return None
    return base_config, profile_config


def _load_base_user_config() -> _LoadedUserConfig | None:
    config_path = _base_config_path()
    if config_path is None:
        return None
    try:
        with open(config_path, "rb") as fh:
            config = tomllib.load(fh)
    except Exception:
        logger.debug("failed to read %s", config_path, exc_info=True)
        return None
    return _LoadedUserConfig(path=config_path, data=config)


def _load_selected_profile_v2(profile_name: str) -> _LoadedUserConfig | None:
    path = _selected_profile_v2_path(profile_name)
    if path is None:
        return None
    try:
        with open(path, "rb") as fh:
            config = tomllib.load(fh)
    except Exception:
        logger.debug("failed to read %s", path, exc_info=True)
        return None
    return _LoadedUserConfig(path=path, data=config)


def _raise_if_matching_legacy_profile_conflict(base_config: _LoadedUserConfig, profile_name: str) -> None:
    top_level_profile = _read_string(base_config.data, "profile")
    profiles = base_config.data.get("profiles")
    has_matching_legacy_table = isinstance(profiles, dict) and profile_name in profiles
    if top_level_profile != profile_name and not has_matching_legacy_table:
        return
    raise ValueError(
        "检测到与 profile-v2 同名的 legacy profile 冲突："
        f"`{profile_name}` 同时出现在 `{base_config.path.name}` 的 legacy `profile` / `[profiles.{profile_name}]` "
        "与 profile-v2 文件中。请删除 legacy 配置，并改用 "
        f"`{profile_name}.config.toml`。"
    )


def _codex_home_dir() -> Path | None:
    codex_home_env = os.environ.get("CODEX_HOME", "").strip()
    if codex_home_env:
        return Path(codex_home_env).expanduser()
    return Path.home() / ".codex"


def _base_config_path() -> Path | None:
    codex_home = _codex_home_dir()
    if codex_home is None:
        return None
    path = codex_home / "config.toml"
    return path if path.is_file() else None


def _selected_profile_v2_path(profile_name: str) -> Path | None:
    codex_home = _codex_home_dir()
    if codex_home is None:
        return None
    path = codex_home / f"{profile_name}.config.toml"
    return path if path.is_file() else None


def _normalize_profile_v2_name(profile_name: str) -> str:
    normalized = str(profile_name or "").strip()
    if not normalized:
        return ""
    if _is_valid_profile_v2_name(normalized):
        return normalized
    raise ValueError(f"非法 profile 名称：`{normalized}`。请使用类似 `work` 的纯名字。")


def _is_valid_profile_v2_name(value: str) -> bool:
    return bool(value) and bool(_PROFILE_V2_NAME_RE.fullmatch(value))


def _read_string(mapping: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return ""
