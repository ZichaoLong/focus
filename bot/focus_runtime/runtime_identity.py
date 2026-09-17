"""Project trusted Focus and ready Codex app-server build identity."""

from __future__ import annotations

import logging
import pathlib
from collections.abc import Callable
from typing import Any

from bot.installed_build_identity import (
    InstalledBuildIdentity,
    InstalledBuildIdentityError,
    read_installed_build_identity,
)
from bot.version import __version__


logger = logging.getLogger("bot.focus_runtime")


class RuntimeIdentityProjection:
    """Own the browser-safe identity snapshot for one Focus runtime."""

    def __init__(
        self,
        *,
        global_data_root: pathlib.Path,
        current_app_server_identity: Callable[..., dict[str, str] | None],
    ) -> None:
        self._current_app_server_identity = current_app_server_identity
        self._installed_build = self._load_installed_build(global_data_root)

    @staticmethod
    def _load_installed_build(
        global_data_root: pathlib.Path,
    ) -> InstalledBuildIdentity | None:
        try:
            identity = read_installed_build_identity(global_data_root)
        except InstalledBuildIdentityError as exc:
            logger.warning("Focus installed-build identity不可用：%s", exc)
            return None
        if identity is not None and identity.version != __version__:
            logger.warning(
                "Focus installed-build identity版本不匹配：runtime=%s installed=%s",
                __version__,
                identity.version,
            )
            return None
        return identity

    def snapshot(self) -> dict[str, Any]:
        try:
            app_server_identity = self._current_app_server_identity(timeout=0.25)
        except TimeoutError:
            app_server_identity = None
        installed_build = self._installed_build
        return {
            "focus_version": __version__,
            "installed_build": (
                installed_build.wire_payload()
                if installed_build is not None
                else None
            ),
            "codex_app_server": app_server_identity,
        }
