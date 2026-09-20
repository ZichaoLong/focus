from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from bot.installation.update import FocusUpdateController, UpdateError, validate_commit, validate_source
from bot.installation.update_launcher import launch_update_worker
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


class UpdateJournalTests(unittest.TestCase):
    def test_default_snapshot_is_machine_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            controller = FocusUpdateController(global_data_root=pathlib.Path(raw))
            snapshot = controller.snapshot()
            self.assertEqual(snapshot["source"]["branch"], "main")
            self.assertEqual(snapshot["state"], "idle")
            self.assertEqual(snapshot["preflight"], {})
            self.assertIn("operation_source", snapshot)

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
        self.assertIn("--no-block", command)
        self.assertIn("--user", command)
        self.assertIn("focus-update-test-check", command)


if __name__ == "__main__":
    unittest.main()
