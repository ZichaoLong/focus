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

            with patch.dict("os.environ", {"HOME": str(root)}, clear=False):
                with patch("bot.codex_command_resolver.shutil.which", return_value=None):
                    command = detect_stable_codex_command()

        self.assertEqual(command, shlex.join([str(stable_node), str(stable_codex_js)]))

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

    def test_render_initial_codex_yaml_embeds_detected_stable_command(self) -> None:
        with patch("bot.install_templates.detect_stable_codex_command", return_value="/stable/node /stable/codex"):
            rendered = render_initial_codex_yaml()

        self.assertIn("已自动探测到稳定的 Node 管理器 Codex 启动命令", rendered)
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


if __name__ == "__main__":
    unittest.main()
