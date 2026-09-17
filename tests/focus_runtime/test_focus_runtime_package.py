from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest.mock import Mock

import bot.focus_runtime as focus_runtime_package
import bot.focus_runtime.runtime as focus_runtime_module
from bot.focus_runtime.runtime_identity import RuntimeIdentityProjection
from bot.installed_build_identity import (
    InstalledBuildIdentity,
    write_installed_build_identity,
)
from bot.version import __version__


_RUNTIME_OWNER_PATH = pathlib.Path(focus_runtime_module.__file__).resolve()
_PACKAGE_ROOT = _RUNTIME_OWNER_PATH.parent
_LEGACY_RUNTIME_PATH = _PACKAGE_ROOT.with_suffix(".py")


class FocusRuntimePackageTests(unittest.TestCase):
    def test_runtime_has_one_real_module_path_without_package_reexport(self) -> None:
        self.assertFalse(_LEGACY_RUNTIME_PATH.exists())
        self.assertTrue(_RUNTIME_OWNER_PATH.is_file())
        self.assertEqual((_PACKAGE_ROOT / "__init__.py").read_bytes(), b"")
        self.assertFalse(hasattr(focus_runtime_package, "FocusRuntime"))

    def test_runtime_preserves_its_operational_logger_category(self) -> None:
        self.assertEqual(focus_runtime_module.logger.name, "bot.focus_runtime")

    def test_runtime_identity_combines_matching_install_and_ready_handshake(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            global_data_root = pathlib.Path(tmpdir)
            identity = InstalledBuildIdentity(
                version=__version__,
                channel="development",
                build_id="build-123",
                source_revision="a" * 40,
            )
            write_installed_build_identity(global_data_root, identity)
            current_app_server_identity = Mock(
                return_value={"user_agent": "codex_cli_rs/0.146.0"}
            )
            projection = RuntimeIdentityProjection(
                global_data_root=global_data_root,
                current_app_server_identity=current_app_server_identity,
            )

            self.assertEqual(
                projection.snapshot(),
                {
                    "focus_version": __version__,
                    "installed_build": identity.wire_payload(),
                    "codex_app_server": {
                        "user_agent": "codex_cli_rs/0.146.0",
                    },
                },
            )
            current_app_server_identity.assert_called_once_with(timeout=0.25)

    def test_runtime_identity_fails_closed_for_mismatch_and_lock_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            global_data_root = pathlib.Path(tmpdir)
            write_installed_build_identity(
                global_data_root,
                InstalledBuildIdentity(
                    version="0.0.1",
                    channel="local",
                    build_id="stale-build",
                    source_revision="b" * 40,
                ),
            )
            with self.assertLogs("bot.focus_runtime", level="WARNING"):
                projection = RuntimeIdentityProjection(
                    global_data_root=global_data_root,
                    current_app_server_identity=Mock(side_effect=TimeoutError),
                )

            self.assertEqual(
                projection.snapshot(),
                {
                    "focus_version": __version__,
                    "installed_build": None,
                    "codex_app_server": None,
                },
            )


if __name__ == "__main__":
    unittest.main()
