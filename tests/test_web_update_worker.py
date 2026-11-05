from __future__ import annotations

import contextlib
import pathlib
import subprocess
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from bot.installation import update_worker as worker
from bot.installation.python_runtime import PythonRuntimeError, runtime_policy, venv_python
from bot.installation.update import UpdateJournal
from bot.installation.update_launcher import launch_update_worker
from bot.installation.update_process import UpdateError


class WebUpdateWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = pathlib.Path(self.temporary.name)
        self.journal = UpdateJournal(self.data / "_global")
        self.journal.root.mkdir()
        operation = self.journal.read()
        operation.update(operation_id="a" * 32, target="stable", state="checking", operation_source=None,
                         unit="focus-update-test-check.service")
        self.journal.write(operation)
        self.operation = self.journal.read()
        self.bundle = self.data / "download.zip"
        self.bundle.write_bytes(b"validated bundle")
        self.policy = runtime_policy()
        self.python = self.data / ".python" / "prepared-python"
        self.events = []
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        downloaded = SimpleNamespace(artifact_path=self.bundle, metadata=SimpleNamespace(source_revision="b" * 40))
        self.stack.enter_context(patch.object(worker.installer, "_resolved_install_bundle",
                                            return_value=contextlib.nullcontext(downloaded)))
        self.stack.enter_context(patch.object(worker, "validate_install_bundle", return_value=SimpleNamespace(
            wheel_path=self.data / "focus.whl", dependency_lock_path=self.data / "requirements.lock")))
        self.stack.enter_context(patch.object(worker, "default_data_root", return_value=self.data))
        self.stack.enter_context(patch.object(worker, "runtime_policy", return_value=self.policy))
        self.ensure = self.stack.enter_context(patch.object(worker, "ensure_python", return_value=self.python))
        self.existing = self.stack.enter_context(patch.object(worker, "existing_python", return_value=self.python))
        self.stack.enter_context(patch.object(worker, "verify_python", return_value={
            "version": self.policy.python_version, "base_prefix": str(self.python.parent)}))
        self.stack.enter_context(patch.object(worker, "_disk", return_value={"free_bytes": 10**10, "free_inodes": 100000}))
        self.stack.enter_context(patch.object(worker, "create_venv", side_effect=self._create_environment))
        self.stack.enter_context(patch.object(worker, "run", side_effect=self._run))
        self.offline = self.stack.enter_context(patch.object(worker, "install_offline", side_effect=lambda *a: self.events.append("offline-install")))
        self.pip_check = self.stack.enter_context(patch.object(worker.installer, "_run_pip_check", side_effect=lambda *a: self.events.append("pip-check")))
        self.transaction = Mock(stop_phase_started=False)
        self.transaction.prepare.side_effect = lambda: self.events.append("stop")
        self.transaction.complete.side_effect = lambda: self.events.append("restart")
        self.factory = self.stack.enter_context(patch.object(worker, "create_managed_install_transaction", return_value=self.transaction))
        self.body = self.stack.enter_context(patch.object(worker.installer, "install_bundle_body", side_effect=lambda *a, **kw: self.events.append("install")))

    def _create_environment(self, python, directory) -> None:
        self.assertEqual(python, self.python)
        executable = venv_python(directory)
        executable.parent.mkdir(parents=True)
        executable.write_text("prepared executable", encoding="utf-8")

    def _run(self, command, *, label, **kwargs) -> str:
        if label == "dependency download":
            directory = pathlib.Path(command[command.index("--dest") + 1])
            with zipfile.ZipFile(directory / "focus-5.1.0-py3-none-any.whl", "w") as archive:
                archive.writestr("bot/__init__.py", "")
            self.assertEqual(pathlib.Path(command[0]), venv_python(self.journal.directory("a" * 32) / "preflight-venv"))
            self.assertIn("--only-binary=:all:", command)
        else:
            self.events.append(label)
        return ""

    def _ready(self) -> dict:
        worker._check(self.journal, self.operation)
        value = self.journal.read()
        self.assertEqual(value["state"], "ready", value["error"])
        value.update(state="applying", phase="apply_validate")
        self.journal.write(value)
        return self.journal.read()

    def _apply(self, operation) -> None:
        directory = self.journal.directory(operation["operation_id"]) / "preflight-venv"
        with patch.object(worker.sys, "prefix", str(directory)):
            with patch.object(worker.sys, "executable", str(venv_python(directory))):
                worker._apply(self.journal, operation)

    def test_check_installs_and_starts_candidate_before_declaring_ready(self) -> None:
        worker._check(self.journal, self.operation)
        value = self.journal.read()
        self.assertEqual(value["state"], "ready", value["error"])
        self.assertEqual(self.events, ["offline-install", "pip-check", "Focus runtime import check", "Focus CLI startup check"])
        self.assertEqual(value["preflight"]["python_runtime"]["version"], self.policy.python_version)
        self.factory.assert_not_called()
        self.body.assert_not_called()

    def test_runtime_or_offline_install_failure_keeps_service_untouched(self) -> None:
        for failing in (self.ensure, self.offline, self.pip_check):
            with self.subTest(failing=failing):
                failing.side_effect = PythonRuntimeError("preflight failed")
                worker._check(self.journal, self.operation)
                observed = self.journal.read()
                self.assertEqual(observed["state"], "failed")
                self.assertFalse(observed["installation_started"])
                self.factory.assert_not_called()
                self.body.assert_not_called()
                failing.side_effect = None
                self.journal.write(self.operation)

    def test_apply_rechecks_before_stopping_and_uses_the_prepared_runtime(self) -> None:
        operation = self._ready()
        self.events.clear()
        self.ensure.reset_mock()
        self._apply(operation)
        self.assertEqual(self.journal.read()["state"], "succeeded")
        self.assertEqual(self.events, ["pip-check", "stop", "install", "restart"])
        self.ensure.assert_not_called()
        self.existing.assert_called_once_with(self.policy, self.data)
        self.assertEqual(self.body.call_args.kwargs["runtime_python"], self.python)

    def test_missing_runtime_is_rejected_before_shutdown_without_downloading(self) -> None:
        operation = self._ready()
        self.existing.side_effect = PythonRuntimeError("missing prepared runtime")
        self._apply(operation)
        self.assertEqual(self.journal.read()["state"], "failed")
        self.factory.assert_not_called()
        self.body.assert_not_called()

    def test_changed_bundle_is_rejected_before_shutdown(self) -> None:
        operation = self._ready()
        pathlib.Path(operation["bundle_path"]).write_bytes(b"changed")
        self._apply(operation)
        self.assertIn("bundle changed", self.journal.read()["error"])
        self.factory.assert_not_called()

    def test_apply_cannot_replace_its_own_environment(self) -> None:
        operation = self._ready()
        with patch.object(worker.sys, "prefix", str(self.data / ".venv")):
            worker._apply(self.journal, operation)
        self.assertIn("independent environment", self.journal.read()["error"])
        self.factory.assert_not_called()

    def test_launcher_runs_apply_from_the_prepared_candidate(self) -> None:
        self._ready()
        with patch("bot.installation.update_launcher.shutil.which", return_value="systemd-run"):
            with patch("bot.installation.update_launcher.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
                launch_update_worker(self.journal, "a" * 32, "apply")
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--") + 1], str(venv_python(self.journal.directory("a" * 32) / "preflight-venv")))

    def test_launcher_rejects_ready_operations_from_before_runtime_preflight(self) -> None:
        operation = self.journal.read()
        operation.update(state="ready", phase="ready")
        self.journal.write(operation)
        with patch("bot.installation.update_launcher.shutil.which", return_value="systemd-run"):
            with patch("bot.installation.update_launcher.subprocess.run") as run:
                with self.assertRaisesRegex(UpdateError, "fresh check"):
                    launch_update_worker(self.journal, "a" * 32, "apply")
        run.assert_not_called()
