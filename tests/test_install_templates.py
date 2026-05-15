import pathlib
import shlex
import tempfile
import unittest
from unittest.mock import patch

import yaml

from bot.codex_command_resolver import resolve_managed_codex_command
from bot.install_templates import CODEX_YAML_TEMPLATE, detect_stable_codex_command, render_initial_codex_yaml


class InstallTemplateTests(unittest.TestCase):
    def test_detect_stable_codex_command_prefers_fnm_default_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            fnm_root = root / "fnm"
            default_installation = fnm_root / "aliases" / "default"
            (default_installation / "bin").mkdir(parents=True)
            (default_installation / "lib" / "node_modules" / "@openai" / "codex" / "bin").mkdir(parents=True)
            stable_node = default_installation / "bin" / "node"
            stable_node.write_text("", encoding="utf-8")
            stable_codex_js = default_installation / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            stable_codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            stable_codex = default_installation / "bin" / "codex"
            stable_codex.symlink_to(stable_codex_js)
            fnm_executable = fnm_root / "fnm"
            fnm_executable.write_text("", encoding="utf-8")

            session_bin = root / "run" / "fnm_multishells" / "123" / "bin"
            session_bin.mkdir(parents=True)
            (session_bin / "node").symlink_to(stable_node)
            (session_bin / "codex").symlink_to(stable_codex)

            def _which(name: str) -> str | None:
                mapping = {
                    "fnm": str(fnm_executable),
                    "node": str(session_bin / "node"),
                    "codex": str(session_bin / "codex"),
                }
                return mapping.get(name)

            with patch("bot.codex_command_resolver.shutil.which", side_effect=_which):
                command = detect_stable_codex_command()

        self.assertEqual(command, shlex.join([str(stable_node), str(stable_codex)]))

    def test_detect_stable_codex_command_supports_nvm_default_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            nvm_root = root / ".nvm"
            version_root = nvm_root / "versions" / "node" / "v24.15.0" / "bin"
            version_root.mkdir(parents=True)
            (nvm_root / "alias").mkdir(parents=True)
            stable_node = version_root / "node"
            stable_node.write_text("", encoding="utf-8")
            stable_codex_js = (
                nvm_root
                / "versions"
                / "node"
                / "v24.15.0"
                / "lib"
                / "node_modules"
                / "@openai"
                / "codex"
                / "bin"
                / "codex.js"
            )
            stable_codex_js.parent.mkdir(parents=True)
            stable_codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            stable_codex = version_root / "codex"
            stable_codex.symlink_to(stable_codex_js)
            (nvm_root / "alias" / "default").write_text("v24.15.0\n", encoding="utf-8")

            with patch.dict("os.environ", {"HOME": str(root), "FNM_DIR": "", "NVM_DIR": ""}, clear=False):
                with patch("bot.codex_command_resolver.shutil.which", return_value=None):
                    command = detect_stable_codex_command()

        self.assertEqual(command, shlex.join([str(stable_node), str(stable_codex_js)]))

    def test_detect_stable_codex_command_on_windows_supports_global_npm_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            appdata = root / "AppData" / "Roaming"
            npm_dir = appdata / "npm"
            wrapper = npm_dir / "codex.cmd"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("@echo off\r\n", encoding="utf-8")
            codex_js = npm_dir / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            codex_js.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            node = root / "Program Files" / "nodejs" / "node.exe"
            node.parent.mkdir(parents=True)
            node.write_text("", encoding="utf-8")

            def _which(name: str) -> str | None:
                if name == "codex":
                    return str(wrapper)
                if name == "node":
                    return str(node)
                return None

            with patch("bot.codex_command_resolver._is_windows", return_value=True):
                with patch.dict(
                    "os.environ",
                    {
                        "APPDATA": str(appdata),
                        "ProgramFiles": str(root / "Program Files"),
                        "ProgramFiles(x86)": "",
                        "HOME": str(root),
                    },
                    clear=False,
                ):
                    with patch("bot.codex_command_resolver.shutil.which", side_effect=_which):
                        command = detect_stable_codex_command()

        self.assertEqual(
            command,
            shlex.join(
                [
                    str(node).replace("\\", "/"),
                    str(codex_js).replace("\\", "/"),
                ]
            ),
        )

    def test_resolve_managed_codex_command_normalizes_explicit_nvm_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            installation_root = root / ".nvm" / "versions" / "node" / "v24.15.0"
            wrapper = installation_root / "bin" / "codex"
            wrapper.parent.mkdir(parents=True)
            node = installation_root / "bin" / "node"
            node.write_text("", encoding="utf-8")
            codex_js = installation_root / "lib" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            codex_js.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            wrapper.symlink_to(codex_js)

            command = resolve_managed_codex_command(str(wrapper))

        self.assertEqual(command, shlex.join([str(node), str(codex_js)]))

    def test_resolve_managed_codex_command_on_windows_prefers_current_npm_wrapper_with_explicit_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            appdata = root / "AppData" / "Roaming"
            npm_dir = appdata / "npm"
            wrapper = npm_dir / "codex.cmd"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("@echo off\r\n", encoding="utf-8")
            codex_js = npm_dir / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            codex_js.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            node = root / "Program Files" / "nodejs" / "node.exe"
            node.parent.mkdir(parents=True)
            node.write_text("", encoding="utf-8")

            def _which(name: str) -> str | None:
                if name == "codex":
                    return str(wrapper)
                if name == "node":
                    return str(node)
                return None

            with patch("bot.codex_command_resolver._is_windows", return_value=True):
                with patch.dict(
                    "os.environ",
                    {
                        "APPDATA": str(appdata),
                        "ProgramFiles": str(root / "Program Files"),
                        "ProgramFiles(x86)": "",
                        "HOME": str(root),
                    },
                    clear=False,
                ):
                    with patch("bot.codex_command_resolver.shutil.which", side_effect=_which):
                        command = resolve_managed_codex_command("codex")

        self.assertEqual(
            command,
            shlex.join(
                [
                    str(node).replace("\\", "/"),
                    str(codex_js).replace("\\", "/"),
                ]
            ),
        )

    def test_resolve_managed_codex_command_on_windows_falls_back_to_appdata_npm_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            appdata = root / "AppData" / "Roaming"
            npm_dir = appdata / "npm"
            wrapper = npm_dir / "codex.cmd"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("@echo off\r\n", encoding="utf-8")
            codex_js = npm_dir / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
            codex_js.parent.mkdir(parents=True)
            codex_js.write_text("#!/usr/bin/env node\n", encoding="utf-8")
            node = root / "Program Files" / "nodejs" / "node.exe"
            node.parent.mkdir(parents=True)
            node.write_text("", encoding="utf-8")

            def _which(name: str) -> str | None:
                if name == "node":
                    return str(node)
                return None

            with patch("bot.codex_command_resolver._is_windows", return_value=True):
                with patch.dict(
                    "os.environ",
                    {
                        "APPDATA": str(appdata),
                        "ProgramFiles": str(root / "Program Files"),
                        "ProgramFiles(x86)": "",
                        "HOME": str(root),
                    },
                    clear=False,
                ):
                    with patch("bot.codex_command_resolver.shutil.which", side_effect=_which):
                        command = resolve_managed_codex_command("codex")

        self.assertEqual(
            command,
            shlex.join(
                [
                    str(node).replace("\\", "/"),
                    str(codex_js).replace("\\", "/"),
                ]
            ),
        )

    def test_render_initial_codex_yaml_embeds_detected_stable_command(self) -> None:
        with patch("bot.install_templates.detect_stable_codex_command", return_value="/stable/node /stable/codex"):
            rendered = render_initial_codex_yaml()

        self.assertIn("已自动探测到稳定的 Codex 启动命令", rendered)
        self.assertIn("codex_command: /stable/node /stable/codex", rendered)
        active_lines = [
            line
            for line in rendered.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(
            yaml.safe_load("\n".join(active_lines)),
            {"codex_command": "/stable/node /stable/codex"},
        )

    def test_render_initial_codex_yaml_keeps_generic_template_without_stable_command(self) -> None:
        with patch("bot.install_templates.detect_stable_codex_command", return_value=None):
            rendered = render_initial_codex_yaml()

        self.assertEqual(rendered, CODEX_YAML_TEMPLATE)

    def test_codex_yaml_template_documents_new_thread_memory_mode_seed(self) -> None:
        self.assertIn("new_thread_memory_mode_seed", CODEX_YAML_TEMPLATE)
        self.assertIn("read_write", CODEX_YAML_TEMPLATE)


if __name__ == "__main__":
    unittest.main()
