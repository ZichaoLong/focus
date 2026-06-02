from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from bot.codex_config_reader import (
    codex_home_dir,
    materialize_profile_v2_text,
    normalize_profile_v2_name,
)


@dataclass(frozen=True, slots=True)
class PreparedManagedCodexHome:
    path: Path
    real_codex_home: Path
    startup_profile: str


def prepare_managed_codex_home(
    *,
    app_server_data_dir: Path,
    startup_profile: str,
) -> PreparedManagedCodexHome:
    normalized_profile = normalize_profile_v2_name(startup_profile)
    if not normalized_profile:
        raise ValueError("startup profile 不能为空。")

    real_codex_home = codex_home_dir()
    if real_codex_home is None:
        raise RuntimeError("无法解析 CODEX_HOME。")

    merged_config_text = materialize_profile_v2_text(normalized_profile)
    synthetic_home = app_server_data_dir / "managed-codex-home"
    _recreate_directory(synthetic_home)

    if real_codex_home.is_dir():
        for child in real_codex_home.iterdir():
            if child.name == "config.toml":
                continue
            _link_or_copy(child, synthetic_home / child.name)

    config_path = synthetic_home / "config.toml"
    config_path.write_text(merged_config_text, encoding="utf-8")

    return PreparedManagedCodexHome(
        path=synthetic_home,
        real_codex_home=real_codex_home,
        startup_profile=normalized_profile,
    )


def _recreate_directory(path: Path) -> None:
    if path.exists():
        for child in path.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    path.mkdir(parents=True, exist_ok=True)


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.symlink(source, destination, target_is_directory=source.is_dir())
        return
    except OSError:
        pass

    if source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
        return
    shutil.copy2(source, destination)
