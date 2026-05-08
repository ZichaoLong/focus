import pathlib
import subprocess
import unittest
from unittest.mock import patch

import install


class InstallTests(unittest.TestCase):
    def test_ensure_venv_pip_skips_ensurepip_when_pip_exists(self) -> None:
        venv_python = pathlib.Path("/tmp/fc-venv/bin/python")
        calls: list[list[str]] = []

        def fake_run(command, check=False, **kwargs):
            calls.append(list(command))
            self.assertEqual(command, [str(venv_python), "-m", "pip", "--version"])
            self.assertFalse(check)
            return subprocess.CompletedProcess(command, 0)

        with patch("install.subprocess.run", side_effect=fake_run):
            install._ensure_venv_pip(venv_python)

        self.assertEqual(calls, [[str(venv_python), "-m", "pip", "--version"]])

    def test_ensure_venv_pip_bootstraps_missing_pip_with_ensurepip(self) -> None:
        venv_python = pathlib.Path("/tmp/fc-venv/bin/python")
        calls: list[list[str]] = []
        pip_checks = 0

        def fake_run(command, check=False, **kwargs):
            nonlocal pip_checks
            rendered = list(command)
            calls.append(rendered)
            if rendered == [str(venv_python), "-m", "pip", "--version"]:
                pip_checks += 1
                return subprocess.CompletedProcess(command, 1 if pip_checks == 1 else 0)
            if rendered == [str(venv_python), "-m", "ensurepip", "--upgrade"]:
                self.assertTrue(check)
                return subprocess.CompletedProcess(command, 0)
            raise AssertionError(f"unexpected command: {rendered}")

        with patch("install.subprocess.run", side_effect=fake_run):
            install._ensure_venv_pip(venv_python)

        self.assertEqual(
            calls,
            [
                [str(venv_python), "-m", "pip", "--version"],
                [str(venv_python), "-m", "ensurepip", "--upgrade"],
                [str(venv_python), "-m", "pip", "--version"],
            ],
        )

    def test_ensure_venv_pip_surfaces_clear_error_when_ensurepip_fails(self) -> None:
        venv_python = pathlib.Path("/tmp/fc-venv/bin/python")

        def fake_run(command, check=False, **kwargs):
            rendered = list(command)
            if rendered == [str(venv_python), "-m", "pip", "--version"]:
                return subprocess.CompletedProcess(command, 1)
            if rendered == [str(venv_python), "-m", "ensurepip", "--upgrade"]:
                raise subprocess.CalledProcessError(1, command)
            raise AssertionError(f"unexpected command: {rendered}")

        with patch("install.subprocess.run", side_effect=fake_run):
            with self.assertRaises(SystemExit) as raised:
                install._ensure_venv_pip(venv_python)

        self.assertIn("venv/ensurepip", str(raised.exception))
