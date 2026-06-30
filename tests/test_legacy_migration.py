import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import bot.legacy_migration as legacy_migration
from bot.legacy_migration import migrate_from_feishu_codex


class LegacyMigrationTests(unittest.TestCase):
    def test_migrate_from_feishu_codex_transfers_persistent_state_and_timers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            home = root / "home"
            old_config = home / ".config" / "feishu-codex"
            old_data = home / ".local" / "share" / "feishu-codex"
            target_config = root / "focus-config"
            target_data = root / "focus-data"
            target_bin = root / "bin"
            systemd_dir = home / ".config" / "systemd" / "user"
            old_config.mkdir(parents=True)
            old_data.mkdir(parents=True)
            target_config.mkdir(parents=True)
            (target_data / ".venv").mkdir(parents=True)
            target_bin.mkdir(parents=True)
            systemd_dir.mkdir(parents=True)

            (old_config / "system.yaml").write_text("old-system\n", encoding="utf-8")
            (old_config / "codex.yaml").write_text("old-codex\n", encoding="utf-8")
            (old_config / "init.token").write_text("old-token\n", encoding="utf-8")
            (old_config / "feishu-codex.env").write_text("OLD_ENV=1\n", encoding="utf-8")
            (old_config / "instances" / "explorer").mkdir(parents=True)
            (old_config / "instances" / "explorer" / "feishu-codex.env").write_text(
                "OLD_INSTANCE_ENV=1\n",
                encoding="utf-8",
            )
            (target_config / "system.yaml").write_text("generated-focus-system\n", encoding="utf-8")

            (old_data / "chat_bindings.json").write_text('{"bindings": true}\n', encoding="utf-8")
            (old_data / "terminal_results.json").write_text('{"results": []}\n', encoding="utf-8")
            (old_data / "service-instance.json").write_text('{"runtime": true}\n', encoding="utf-8")
            (old_data / "app_server_runtime.json").write_text('{"url": "ws://old"}\n', encoding="utf-8")
            (old_data / "_global").mkdir()
            (old_data / "_global" / "instance_registry.json").write_text('{"old": true}\n', encoding="utf-8")
            (old_data / "instances" / "explorer").mkdir(parents=True)
            (old_data / "instances" / "explorer" / "chat_bindings.json").write_text(
                '{"instance": "explorer"}\n',
                encoding="utf-8",
            )

            task_dir = old_data / "scheduled-tasks" / "morning"
            task_dir.mkdir(parents=True)
            (task_dir / "prompt.txt").write_text("follow up with feishu-codexctl\n", encoding="utf-8")
            (task_dir / "task.json").write_text(
                json.dumps(
                    {
                        "task_id": "morning",
                        "instance": "explorer",
                        "binding_id": "binding-1",
                        "on_calendar": "Mon *-*-* 09:00:00",
                        "description": "morning task",
                        "prompt_file": str(task_dir / "prompt.txt"),
                        "synthetic_source": "schedule",
                        "display_mode": "silent",
                        "created_at": "2026-06-30T00:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            (systemd_dir / "feishu-codex-scheduled-morning.timer").write_text("old timer\n", encoding="utf-8")
            (systemd_dir / "feishu-codex-scheduled-morning.service").write_text("old service\n", encoding="utf-8")
            (home / ".local" / "bin").mkdir(parents=True)
            (home / ".local" / "bin" / "feishu-codexctl").write_text("#!/bin/sh\n", encoding="utf-8")

            systemctl_calls: list[tuple[str, ...]] = []
            install_calls = 0

            def fake_install() -> int:
                nonlocal install_calls
                install_calls += 1
                (target_bin / "focusctl").write_text("#!/bin/sh\n", encoding="utf-8")
                return 0

            def fake_systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
                systemctl_calls.append(tuple(args))
                return subprocess.CompletedProcess(["systemctl", "--user", *args], 0, "", "")

            def fake_which(command: str) -> str | None:
                return "/usr/bin/systemctl" if command == "systemctl" else None

            env = {
                "HOME": str(home),
                "FC_CONFIG_ROOT": str(old_config),
                "FC_DATA_ROOT": str(old_data),
                "FC_BIN_DIR": str(home / ".local" / "bin"),
                "FC_ENV_FILE": str(old_config / "feishu-codex.env"),
                "FOCUS_CONFIG_ROOT": str(target_config),
                "FOCUS_DATA_ROOT": str(target_data),
                "FOCUS_BIN_DIR": str(target_bin),
                "XDG_DATA_HOME": str(home / ".local" / "share"),
                "XDG_CONFIG_HOME": str(home / ".config"),
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("bot.legacy_migration.is_linux", return_value=True):
                    with patch("bot.legacy_migration.is_macos", return_value=False):
                        with patch("bot.legacy_migration.is_windows", return_value=False):
                            with patch("bot.legacy_migration.shutil.which", side_effect=fake_which):
                                with patch("bot.legacy_migration._run_systemctl", side_effect=fake_systemctl):
                                    summary = migrate_from_feishu_codex(install_new_surface=fake_install)

            self.assertEqual(install_calls, 1)
            self.assertEqual(summary.instances, ["default", "explorer"])
            self.assertEqual((target_config / "system.yaml").read_text(encoding="utf-8"), "old-system\n")
            self.assertTrue((target_config / "focus.env").exists())
            self.assertTrue((target_config / "instances" / "explorer" / "focus.env").exists())
            self.assertTrue((target_data / "chat_bindings.json").exists())
            self.assertTrue((target_data / "terminal_results.json").exists())
            self.assertTrue((target_data / "instances" / "explorer" / "chat_bindings.json").exists())
            self.assertFalse((target_data / "service-instance.json").exists())
            self.assertFalse((target_data / "app_server_runtime.json").exists())
            self.assertFalse((target_data / "_global" / "instance_registry.json").exists())
            self.assertFalse((systemd_dir / "feishu-codex-scheduled-morning.timer").exists())
            self.assertTrue((systemd_dir / "focus-scheduled-morning.timer").exists())
            migrated_prompt = home / ".local" / "share" / "focus" / "scheduled-tasks" / "morning" / "prompt.txt"
            self.assertEqual(migrated_prompt.read_text(encoding="utf-8"), "follow up with focusctl\n")
            self.assertIn(("enable", "focus-scheduled-morning.timer"), systemctl_calls)
            self.assertIn(("start", "focus-scheduled-morning.timer"), systemctl_calls)
            self.assertIn(("disable", "--now", "feishu-codex-scheduled-morning.timer"), systemctl_calls)
            self.assertFalse((home / ".local" / "bin" / "feishu-codexctl").exists())
            self.assertFalse(old_config.exists())
            self.assertFalse(old_data.exists())
            self.assertIsNotNone(summary.backup_dir)
            assert summary.backup_dir is not None
            self.assertTrue((summary.backup_dir / "legacy" / "config" / "system.yaml").exists())

    def test_migrate_from_feishu_codex_uses_legacy_fc_path_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            home = root / "home"
            old_config = root / "legacy-config"
            old_data = root / "legacy-data"
            old_bin = root / "legacy-bin"
            old_completion = root / "legacy-completions"
            old_env = root / "legacy-env" / "custom.env"
            target_config = root / "focus-config"
            target_data = root / "focus-data"
            target_bin = root / "focus-bin"
            old_config.mkdir(parents=True)
            old_data.mkdir(parents=True)
            old_bin.mkdir(parents=True)
            old_completion.mkdir(parents=True)
            old_env.parent.mkdir(parents=True)
            target_config.mkdir(parents=True)
            (target_data / ".venv").mkdir(parents=True)
            target_bin.mkdir(parents=True)

            (old_config / "system.yaml").write_text("custom-system\n", encoding="utf-8")
            (old_data / "chat_bindings.json").write_text('{"custom": true}\n', encoding="utf-8")
            old_env.write_text("CUSTOM_ENV=1\n", encoding="utf-8")
            (old_bin / "feishu-codexctl").write_text("#!/bin/sh\n", encoding="utf-8")
            (old_completion / "feishu-codexctl").write_text("complete\n", encoding="utf-8")

            def fake_install() -> int:
                (target_bin / "focusctl").write_text("#!/bin/sh\n", encoding="utf-8")
                return 0

            env = {
                "HOME": str(home),
                "FC_CONFIG_ROOT": str(old_config),
                "FC_DATA_ROOT": str(old_data),
                "FC_BIN_DIR": str(old_bin),
                "FC_ENV_FILE": str(old_env),
                "FC_BASH_COMPLETION_DIR": str(old_completion),
                "FOCUS_CONFIG_ROOT": str(target_config),
                "FOCUS_DATA_ROOT": str(target_data),
                "FOCUS_BIN_DIR": str(target_bin),
            }
            with patch.dict(os.environ, env, clear=False):
                with patch("bot.legacy_migration.is_linux", return_value=False):
                    with patch("bot.legacy_migration.is_macos", return_value=False):
                        with patch("bot.legacy_migration.is_windows", return_value=False):
                            summary = migrate_from_feishu_codex(install_new_surface=fake_install)

            self.assertEqual((target_config / "system.yaml").read_text(encoding="utf-8"), "custom-system\n")
            self.assertEqual((target_config / "focus.env").read_text(encoding="utf-8"), "CUSTOM_ENV=1\n")
            self.assertEqual((target_data / "chat_bindings.json").read_text(encoding="utf-8"), '{"custom": true}\n')
            self.assertFalse(old_config.exists())
            self.assertFalse(old_data.exists())
            self.assertFalse(old_env.exists())
            self.assertFalse((old_bin / "feishu-codexctl").exists())
            self.assertFalse((old_completion / "feishu-codexctl").exists())
            self.assertEqual(summary.config_files, 2)
            self.assertEqual(summary.data_files, 1)

    def test_migrate_from_feishu_codex_rejects_target_env_file_inside_legacy_config_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            home = root / "home"
            old_config = root / "legacy-config"
            old_data = root / "legacy-data"
            target_config = root / "focus-config"
            target_data = root / "focus-data"
            old_config.mkdir(parents=True)
            target_config.mkdir(parents=True)
            (old_config / "system.yaml").write_text("old-system\n", encoding="utf-8")
            install_calls = 0

            def fake_install() -> int:
                nonlocal install_calls
                install_calls += 1
                return 0

            env = {
                "HOME": str(home),
                "FC_CONFIG_ROOT": str(old_config),
                "FC_DATA_ROOT": str(old_data),
                "FOCUS_CONFIG_ROOT": str(target_config),
                "FOCUS_DATA_ROOT": str(target_data),
                "FOCUS_ENV_FILE": str(old_config / "focus.env"),
                "FOCUS_BIN_DIR": str(root / "focus-bin"),
                "XDG_DATA_HOME": str(root / "xdg-data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("bot.legacy_migration.is_linux", return_value=False),
                patch("bot.legacy_migration.is_macos", return_value=False),
                patch("bot.legacy_migration.is_windows", return_value=False),
                self.assertRaises(legacy_migration.LegacyMigrationError) as raised,
            ):
                migrate_from_feishu_codex(install_new_surface=fake_install)

            self.assertEqual(raised.exception.stage, "preflight")
            self.assertIn("FOCUS env file", str(raised.exception))
            self.assertEqual(install_calls, 0)
            self.assertFalse((old_config / "focus.env").exists())

    def test_migrate_from_feishu_codex_rejects_target_bin_dir_inside_legacy_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            home = root / "home"
            old_config = root / "legacy-config"
            old_data = root / "legacy-data"
            target_config = root / "focus-config"
            target_data = root / "focus-data"
            old_config.mkdir(parents=True)
            target_config.mkdir(parents=True)
            (old_config / "system.yaml").write_text("old-system\n", encoding="utf-8")
            install_calls = 0

            def fake_install() -> int:
                nonlocal install_calls
                install_calls += 1
                (old_data / "bin").mkdir(parents=True, exist_ok=True)
                return 0

            env = {
                "HOME": str(home),
                "FC_CONFIG_ROOT": str(old_config),
                "FC_DATA_ROOT": str(old_data),
                "FOCUS_CONFIG_ROOT": str(target_config),
                "FOCUS_DATA_ROOT": str(target_data),
                "FOCUS_BIN_DIR": str(old_data / "bin"),
                "XDG_DATA_HOME": str(root / "xdg-data"),
            }
            with (
                patch.dict(os.environ, env, clear=True),
                patch("bot.legacy_migration.is_linux", return_value=False),
                patch("bot.legacy_migration.is_macos", return_value=False),
                patch("bot.legacy_migration.is_windows", return_value=False),
                self.assertRaises(legacy_migration.LegacyMigrationError) as raised,
            ):
                migrate_from_feishu_codex(install_new_surface=fake_install)

            self.assertEqual(raised.exception.stage, "preflight")
            self.assertIn("FOCUS bin dir", str(raised.exception))
            self.assertEqual(install_calls, 0)
            self.assertFalse((old_data / "bin").exists())

    def test_migrate_scheduled_prompt_warns_for_concrete_helper_path(self) -> None:
        migrated, warnings = legacy_migration._migrate_scheduled_prompt_text(
            "run /old/feishu-codex/.agents/skills/feishu-scheduled-prompts/scripts/"
            "manage_scheduled_prompt.py remove --task-id x with feishu-codexctl\n",
            task_id="x",
        )

        self.assertIn("focusctl", migrated)
        self.assertNotIn("feishu-codexctl", migrated)
        self.assertTrue(any("manage_scheduled_prompt.py" in warning for warning in warnings))
        self.assertTrue(any("old feishu-codex path/env markers" in warning for warning in warnings))

    def test_remove_legacy_windows_user_path_uses_legacy_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            appdata = root / "roaming"
            old_bin = root / "local" / "feishu-codex" / "bin"
            metadata_path = appdata / "feishu-codex" / "config" / "install-state" / "windows-user-path.json"
            metadata_path.parent.mkdir(parents=True)
            metadata_path.write_text(
                json.dumps({"bin_dir": str(old_bin), "added_to_user_path": True}),
                encoding="utf-8",
            )
            writes: list[tuple[str, int | None]] = []

            with patch.dict(
                os.environ,
                {
                    "APPDATA": str(appdata),
                    "FC_CONFIG_ROOT": str(appdata / "feishu-codex" / "config"),
                },
                clear=False,
            ):
                with patch("bot.legacy_migration.is_windows", return_value=True):
                    with patch(
                        "bot.legacy_migration._read_windows_user_path_value",
                        return_value=(f"C:\\Tools;{old_bin};C:\\Keep", 7),
                    ):
                        with patch(
                            "bot.legacy_migration._write_windows_user_path_value",
                            side_effect=lambda raw_path, value_type=None: writes.append((raw_path, value_type)),
                        ):
                            legacy_migration._remove_legacy_windows_user_path()

            self.assertEqual(writes, [("C:\\Tools;C:\\Keep", 7)])
            self.assertFalse(metadata_path.exists())


if __name__ == "__main__":
    unittest.main()
