from __future__ import annotations

import os
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bot.installation.update import (
    FocusUpdateController,
    UpdateError,
    validate_commit,
    validate_source,
    validate_target,
)
from bot.installation.update_launcher import launch_update_worker
from bot.installation.node_toolchain import resolve_node_toolchain
from bot.installation.update_process import UpdateLaunchOutcomeUnknown


class UpdateInputTests(unittest.TestCase):
    def test_commit_accepts_full_or_prefix(self) -> None:
        self.assertEqual(validate_commit("ABCDEF1"), "abcdef1")
        self.assertEqual(validate_commit(""), "")
        for value in ("main", "abc", "g" * 40, "a" * 41):
            with self.subTest(value=value):
                with self.assertRaises(UpdateError):
                    validate_commit(value)

    def test_source_rejects_local_and_credentials(self) -> None:
        self.assertEqual(validate_source("ssh://git@example.com/focus.git"), "ssh://git@example.com/focus.git")
        for value in ("/tmp/focus", "file:///tmp/focus", "https://user:password@example.com/focus.git", "git://example.com/focus.git"):
            with self.subTest(value=value):
                with self.assertRaises(UpdateError):
                    validate_source(value)

    def test_target_only_exposes_stable_and_main(self) -> None:
        self.assertEqual(validate_target("stable"), "stable")
        self.assertEqual(validate_target("main"), "main")
        with self.assertRaisesRegex(UpdateError, "stable or main"):
            validate_target("development")

    def test_stable_check_does_not_pin_a_commit_or_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            with self.assertRaisesRegex(UpdateError, "do not accept a commit"):
                controller.start_check("stable", "a" * 40)
            with patch("bot.installation.update.unavailable_reason", return_value=""):
                with patch(
                    "bot.installation.update.launch_worker",
                    side_effect=UpdateError("launcher refused"),
                ):
                    result = controller.start_check("stable", "")
            self.assertEqual(result["target"], "stable")
            self.assertIsNone(result["operation_source"])


class UpdateJournalTests(unittest.TestCase):
    def test_default_snapshot_is_machine_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            snapshot = controller.snapshot()
            self.assertEqual(snapshot["source"]["branch"], "main")
            self.assertEqual(snapshot["state"], "idle")
            self.assertEqual(snapshot["preflight"], {})
            self.assertIn("operation_source", snapshot)

    def test_old_main_only_journal_is_migrated_to_target_schema(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            value = controller.journal.read()
            value.update(
                schema="focus-web-update-1",
                operation_id="a" * 32,
                state="ready",
                unit=f"focus-update-{'a' * 32}-check.service",
                resolved_commit="b" * 40,
                operation_source={"url": "https://example.com/focus.git", "branch": "main"},
            )
            value.pop("target")
            controller.journal.path.write_text(json.dumps(value), encoding="utf-8")

            migrated = controller.journal.read()

            self.assertEqual(migrated["schema"], "focus-web-update-3")
            self.assertEqual(migrated["target"], "main")
            self.assertEqual(migrated["phase"], "ready")
            self.assertIsNone(migrated["progress"])

    def test_progress_persists_phase_and_byte_count(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            with patch("bot.installation.update.unavailable_reason", return_value=""):
                with patch("bot.installation.update.launch_worker"):
                    started = controller.start_check("stable", "")
            controller.journal.progress(
                started["operation_id"],
                "checking",
                phase="release_download",
                message="Downloading the stable Focus bundle",
                progress={"current": 128, "total": 256, "unit": "bytes"},
            )

            observed = controller.snapshot()

            self.assertEqual(observed["phase"], "release_download")
            self.assertEqual(observed["progress"], {"current": 128, "total": 256, "unit": "bytes"})
            self.assertEqual(observed["message"], "Downloading the stable Focus bundle")

    def test_launch_failure_is_settled_as_failed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            with patch("bot.installation.update.unavailable_reason", return_value=""):
                with patch(
                    "bot.installation.update.launch_worker",
                    side_effect=UpdateError("launcher refused"),
                ):
                    result = controller.start_check("")
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["preflight"], {})
            self.assertIn("launcher refused", result["error"])

    def test_ambiguous_launch_is_settled_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            with patch("bot.installation.update.unavailable_reason", return_value=""):
                with patch(
                    "bot.installation.update.launch_worker",
                    side_effect=UpdateLaunchOutcomeUnknown("launch timed out"),
                ):
                    result = controller.start_check("")
            self.assertEqual(result["state"], "unknown")
            self.assertIn("launch timed out", result["error"])

    def test_inactive_unknown_check_can_be_replaced_by_explicit_retry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            current = controller.journal.read()
            current.update(
                operation_id="a" * 32,
                target="main",
                state="unknown",
                unit=f"focus-update-{'a' * 32}-check.service",
                error="launcher timed out",
                installation_started=False,
                operation_source={"url": "https://example.com/focus.git", "branch": "main"},
            )
            controller.journal.write(current)
            with patch("bot.installation.update.unit_active", return_value=False):
                with patch("bot.installation.update.unavailable_reason", return_value=""):
                    with patch(
                        "bot.installation.update.launch_worker",
                        side_effect=UpdateError("launcher refused"),
                    ):
                        result = controller.start_check("")
            self.assertEqual(result["state"], "failed")
            self.assertIn("launcher refused", result["error"])

    def test_unknown_apply_cannot_be_replaced_by_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            current = controller.journal.read()
            current.update(
                operation_id="a" * 32,
                target="main",
                state="unknown",
                unit=f"focus-update-{'a' * 32}-apply.service",
                installation_started=False,
                operation_source={"url": "https://example.com/focus.git", "branch": "main"},
            )
            controller.journal.write(current)
            with patch("bot.installation.update.unit_active", return_value=False):
                with patch("bot.installation.update.unavailable_reason", return_value=""):
                    with self.assertRaises(UpdateError):
                        controller.start_check("")

    def test_source_change_removes_ready_staging(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            operation_id = "a" * 32
            staging = controller.journal.directory(operation_id)
            staging.mkdir(parents=True)
            current = controller.journal.read()
            current.update(
                operation_id=operation_id,
                target="main",
                state="ready",
                requested_commit="",
                resolved_commit="b" * 40,
                operation_source={"url": "https://old.example/focus.git", "branch": "main"},
            )
            controller.journal.write(current)

            result = controller.configure_source(
                "https://new.example/focus.git", "change-source"
            )

            self.assertFalse(staging.exists())
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["source"]["url"], "https://new.example/focus.git")

    def test_source_change_requires_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            with self.assertRaises(UpdateError):
                controller.configure_source("https://example.com/focus.git", "")
            result = controller.configure_source("https://example.com/focus.git", "change-source")
            self.assertEqual(result["source"]["url"], "https://example.com/focus.git")

    def test_apply_requires_exact_ready_operation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            with self.assertRaises(UpdateError):
                controller.apply("not-an-operation", "not-an-operation")


class UpdateLauncherTests(unittest.TestCase):
    def test_launcher_preserves_user_bus_without_forwarding_arbitrary_secrets(self) -> None:
        class Journal:
            path = pathlib.Path("/tmp/focus-update-operation.json")

            @staticmethod
            def read() -> dict[str, str]:
                return {"unit": "focus-update-test-check.service"}

        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with patch.dict(
            os.environ,
            {
                "PATH": "/usr/bin",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                "XDG_RUNTIME_DIR": "/run/user/1000",
                "OPENAI_API_KEY": "must-not-reach-the-launcher-environment",
            },
            clear=True,
        ):
            with patch(
                "bot.installation.update_launcher.shutil.which",
                return_value="/usr/bin/systemd-run",
            ):
                with patch(
                    "bot.installation.update_launcher.subprocess.run",
                    return_value=completed,
                ) as run:
                    launch_update_worker(Journal(), "a" * 32, "check")

        launcher_environment = run.call_args.kwargs["env"]
        self.assertEqual(
            launcher_environment,
            {
                "PATH": "/usr/bin",
                "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                "XDG_RUNTIME_DIR": "/run/user/1000",
            },
        )
        self.assertNotIn("OPENAI_API_KEY", launcher_environment)
        command = run.call_args.args[0]
        self.assertIn("--setenv=PATH=/usr/bin", command)
        self.assertIn("--no-block", command)
        self.assertIn("--user", command)
        self.assertIn("focus-update-test-check", command)


class NodeToolchainTests(unittest.TestCase):
    @staticmethod
    def _write_version_script(path: pathlib.Path, version: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version}'\n", encoding="utf-8")
        path.chmod(0o755)

    def test_resolver_uses_stable_fnm_alias_when_manager_path_has_no_node(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            fnm_root = root / "fnm"
            bin_dir = fnm_root / "aliases" / "default" / "bin"
            node = bin_dir / "node"
            npm = bin_dir / "npm"
            self._write_version_script(node, "v22.22.0")
            self._write_version_script(npm, "10.9.2")

            toolchain = resolve_node_toolchain(
                {
                    "HOME": str(root),
                    "FNM_DIR": str(fnm_root),
                    "PATH": str(root / "empty-path"),
                }
            )

        self.assertEqual(toolchain.node, node)
        self.assertEqual(toolchain.npm, npm)
        self.assertEqual(toolchain.source, f"fnm-default:{fnm_root}")
        self.assertEqual(toolchain.node_version, "v22.22.0")
        self.assertEqual(toolchain.npm_version, "10.9.2")
        self.assertTrue(toolchain.environment({"PATH": "/usr/bin"})["PATH"].startswith(f"{bin_dir}:"))

    def test_resolver_prefers_explicit_pair_over_path_and_stable_alias(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            explicit_bin = root / "explicit"
            explicit_node = explicit_bin / "node"
            explicit_npm = explicit_bin / "npm"
            self._write_version_script(explicit_node, "v22.22.0")
            self._write_version_script(explicit_npm, "10.9.2")

            alias_bin = root / "fnm" / "aliases" / "default" / "bin"
            self._write_version_script(alias_bin / "node", "v25.9.0")
            self._write_version_script(alias_bin / "npm", "11.0.0")

            toolchain = resolve_node_toolchain(
                {
                    "HOME": str(root),
                    "FNM_DIR": str(root / "fnm"),
                    "PATH": str(root / "empty-path"),
                    "FOCUS_NODE_BIN": str(explicit_node),
                    "FOCUS_NPM_BIN": str(explicit_npm),
                }
            )

        self.assertEqual(toolchain.source, "explicit-toolchain")
        self.assertEqual(toolchain.node, explicit_node)
        self.assertEqual(toolchain.npm, explicit_npm)
        self.assertEqual(toolchain.node_version, "v22.22.0")

    def test_resolver_pins_the_installation_behind_a_fnm_alias(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            fnm_root = root / "fnm"
            installation = fnm_root / "node-versions" / "v22.22.0" / "installation"
            self._write_version_script(installation / "bin" / "node", "v22.22.0")
            self._write_version_script(installation / "bin" / "npm", "10.9.2")
            default_alias = fnm_root / "aliases" / "default"
            default_alias.parent.mkdir(parents=True)
            default_alias.symlink_to(installation, target_is_directory=True)

            toolchain = resolve_node_toolchain(
                {
                    "HOME": str(root),
                    "FNM_DIR": str(fnm_root),
                    "PATH": str(root / "empty-path"),
                }
            )

            newer_installation = fnm_root / "node-versions" / "v25.9.0" / "installation"
            self._write_version_script(newer_installation / "bin" / "node", "v25.9.0")
            self._write_version_script(newer_installation / "bin" / "npm", "11.0.0")
            default_alias.unlink()
            default_alias.symlink_to(newer_installation, target_is_directory=True)

        self.assertEqual(toolchain.node, installation / "bin" / "node")
        self.assertEqual(toolchain.npm, installation / "bin" / "npm")
        self.assertEqual(toolchain.bin_dir, installation / "bin")
        self.assertEqual(toolchain.node_version, "v22.22.0")

    def test_resolver_reports_missing_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            with self.assertRaisesRegex(UpdateError, "Node/npm is unavailable"):
                resolve_node_toolchain(
                    {
                        "HOME": str(root),
                        "PATH": str(root / "empty-path"),
                        "FNM_DIR": str(root / "missing-fnm"),
                    }
                )

    def test_resolver_does_not_use_process_path_when_environment_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            with self.assertRaisesRegex(UpdateError, "Node/npm is unavailable"):
                resolve_node_toolchain(
                    {
                        "HOME": str(root),
                        "FNM_DIR": str(root / "missing-fnm"),
                    }
                )

    def test_resolver_fails_closed_for_incomplete_explicit_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            node = root / "node"
            self._write_version_script(node, "v22.22.0")
            with self.assertRaisesRegex(UpdateError, "matching Node/npm pair"):
                resolve_node_toolchain(
                    {
                        "PATH": str(root / "empty-path"),
                        "FOCUS_NODE_BIN": str(node),
                    }
                )


if __name__ == "__main__":
    unittest.main()
