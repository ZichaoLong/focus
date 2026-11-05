from __future__ import annotations

import contextlib
import json
import os
import pathlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from bot.installation import python_runtime as runtime


class PythonRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = runtime.runtime_policy()

    def _python(self, root: pathlib.Path) -> pathlib.Path:
        directory = self.policy.directory(root) / f"cpython-{self.policy.python_version}-test"
        python = directory / ("python.exe" if os.name == "nt" else "bin/python3")
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("test interpreter", encoding="utf-8")
        return python

    def _observation(self, root: pathlib.Path) -> str:
        base = self.policy.directory(root).resolve() / f"cpython-{self.policy.python_version}-test"
        return json.dumps({"implementation": "cpython", "version": self.policy.python_version,
                           "base_prefix": str(base), "stdlib": str(base / "lib"), "executable": str(base / "python")})

    def test_policy_is_carried_by_the_target_wheel(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheel = pathlib.Path(raw) / "target.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("bot/installation/python-runtime.json", json.dumps({
                    "schema_version": 1, "python_version": "3.12.9", "uv_version": "0.11.3",
                }))
            policy = runtime.runtime_policy(wheel)
        self.assertEqual(policy.python_version, "3.12.9")
        self.assertEqual(policy.uv_version, "0.11.3")

    def test_missing_or_unbounded_policy_is_rejected(self) -> None:
        for value in ({}, {"schema_version": 1, "python_version": "../../python", "uv_version": "0.11.3"},
                      {"schema_version": 1, "python_version": "3.10.9", "uv_version": "0.11.3"}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as raw:
                wheel = pathlib.Path(raw) / "target.whl"
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr("bot/installation/python-runtime.json", json.dumps(value))
                with self.assertRaises(runtime.PythonRuntimeError):
                    runtime.runtime_policy(wheel)

    def test_existing_runtime_needs_neither_uv_nor_network(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            expected = self._python(root)
            with patch.object(runtime, "_run", return_value=self._observation(root)) as run:
                with patch.object(runtime, "_uv", side_effect=AssertionError("must not download")):
                    self.assertEqual(runtime.ensure_python(self.policy, root), expected.resolve())
                    self.assertEqual(runtime.existing_python(self.policy, root), expected.resolve())
            self.assertTrue(all("-c" in call.args[0] for call in run.call_args_list))

    def test_probe_rejects_an_external_base_or_standard_library(self) -> None:
        for key in ("base_prefix", "stdlib"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as raw:
                root = pathlib.Path(raw)
                value = json.loads(self._observation(root))
                value[key] = str(root.parent / "external-python")
                with patch.object(runtime, "_run", return_value=json.dumps(value)):
                    with self.assertRaisesRegex(runtime.PythonRuntimeError, "outside"):
                        runtime.verify_python(pathlib.Path("python"), self.policy, root)

    def test_prepare_downloads_only_to_the_versioned_owned_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                if "install" in command:
                    self._python(root)
                    return ""
                return self._observation(root)

            with patch.object(runtime, "_uv", return_value=contextlib.nullcontext(pathlib.Path("pinned-uv"))):
                with patch.object(runtime, "_run", side_effect=run):
                    runtime.ensure_python(self.policy, root)
            command = calls[0]
            self.assertIn("--no-bin", command)
            self.assertIn("--no-registry", command)
            self.assertEqual(command[command.index("--install-dir") + 1], str(self.policy.directory(root.resolve())))
            self.assertEqual(command[-1], f"cpython-{self.policy.python_version}")

    def test_apply_never_downloads_missing_python(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(runtime, "_uv", side_effect=AssertionError("must not download")):
                with self.assertRaisesRegex(runtime.PythonRuntimeError, "missing"):
                    runtime.existing_python(self.policy, pathlib.Path(raw))

    def test_partial_runtime_is_not_repaired_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            (self.policy.directory(root) / f"cpython-{self.policy.python_version}-test").mkdir(parents=True)
            with patch.object(runtime, "_uv", side_effect=AssertionError("must not replace a live runtime")):
                with self.assertRaisesRegex(runtime.PythonRuntimeError, "incomplete"):
                    runtime.ensure_python(self.policy, root)

    def test_environment_preserves_network_authority_without_runtime_overrides(self) -> None:
        with patch.dict(os.environ, {"HTTPS_PROXY": "https://proxy.test", "PIP_INDEX_URL": "https://index.test",
                                    "SSL_CERT_FILE": "/cert.pem", "PYTHONHOME": "/conda",
                                    "UV_PYTHON_INSTALL_DIR": "/external", "UV_PYTHON_DOWNLOADS_JSON_URL": "https://other"}, clear=True):
            self.assertEqual(runtime._environment(), {"HTTPS_PROXY": "https://proxy.test",
                                                     "PIP_INDEX_URL": "https://index.test", "SSL_CERT_FILE": "/cert.pem"})

    def test_bootstrap_uses_a_temporary_pinned_uv_without_installing_packages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)

            def run(command, **kwargs):
                if "download" in command:
                    directory = pathlib.Path(command[command.index("--dest") + 1])
                    executable = "uv.exe" if os.name == "nt" else "uv"
                    with zipfile.ZipFile(directory / "uv.whl", "w") as archive:
                        archive.writestr(f"uv-{self.policy.uv_version}.data/scripts/{executable}", b"uv binary")
                    self.assertIn(f"uv=={self.policy.uv_version}", command)
                else:
                    return f"uv {self.policy.uv_version}"
                return ""

            with patch.object(runtime.shutil, "which", return_value=None):
                with patch.object(runtime.venv, "EnvBuilder"):
                    with patch.object(runtime, "_run", side_effect=run):
                        with runtime._uv(self.policy, root) as tool:
                            self.assertEqual(tool.read_bytes(), b"uv binary")
                            temporary_tool = tool
            self.assertFalse(temporary_tool.exists())
            self.assertEqual(list(root.iterdir()), [])

    def test_environment_creation_uses_explicit_interpreter_and_copies(self) -> None:
        with patch.object(runtime, "_run") as run:
            runtime.create_venv(pathlib.Path("owned-python"), pathlib.Path("target"))
        self.assertEqual(run.call_args.args[0], ["owned-python", "-I", "-m", "venv", "--copies", "target"])
