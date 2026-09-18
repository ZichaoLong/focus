from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest.mock import patch

from bot.installation.update import FocusUpdateController, UpdateError, validate_commit, validate_source
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


if __name__ == "__main__":
    unittest.main()
