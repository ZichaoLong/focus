import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from bot.shell_completion import (
    complete_words,
    render_bash_completion_script,
    render_powershell_completion_script,
    render_zsh_completion_script,
)


class ShellCompletionTests(unittest.TestCase):
    def test_rendered_script_embeds_python_path_and_registrations(self) -> None:
        rendered = render_bash_completion_script(venv_python=pathlib.Path("/tmp/venv/bin/python"))

        self.assertIn("/tmp/venv/bin/python", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_feishu_codex feishu-codex", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_feishu_codexctl feishu-codexctl", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_feishu_codexd feishu-codexd", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_fcodex fcodex", rendered)

    def test_rendered_zsh_script_embeds_python_path_and_compdef(self) -> None:
        rendered = render_zsh_completion_script(venv_python=pathlib.Path("/tmp/venv/bin/python"))

        self.assertIn("/tmp/venv/bin/python", rendered)
        self.assertIn("autoload -Uz compinit", rendered)
        self.assertIn("compdef _fc_complete_feishu_codex feishu-codex", rendered)
        self.assertIn("compdef _fc_complete_fcodex fcodex", rendered)

    def test_rendered_powershell_script_embeds_python_path_and_registrations(self) -> None:
        rendered = render_powershell_completion_script(venv_python=pathlib.Path("/tmp/venv/Scripts/python.exe"))

        self.assertIn("/tmp/venv/Scripts/python.exe", rendered)
        self.assertIn("Register-ArgumentCompleter -Native -CommandName $commandName", rendered)
        self.assertIn("bot.shell_completion complete", rendered)
        self.assertIn("feishu-codexctl", rendered)

    def test_feishu_codex_completes_instance_option_and_remove_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            config_root = root / "config"
            data_root = root / "data"
            (config_root / "instances" / "corp-a").mkdir(parents=True, exist_ok=True)
            (data_root / "instances" / "corp-b").mkdir(parents=True, exist_ok=True)
            with patch.dict(
                os.environ,
                {
                    "FC_CONFIG_ROOT": str(config_root),
                    "FC_DATA_ROOT": str(data_root),
                },
                clear=False,
            ):
                instance_matches = complete_words("feishu-codex", ["feishu-codex", "--instance", ""], 2)
                remove_matches = complete_words("feishu-codex", ["feishu-codex", "instance", "remove", ""], 3)

        self.assertEqual(instance_matches, ["corp-a", "corp-b", "default"])
        self.assertEqual(remove_matches, ["corp-a", "corp-b"])

    def test_feishu_codexctl_completes_thread_goal_subcommands(self) -> None:
        matches = complete_words(
            "feishu-codexctl",
            ["feishu-codexctl", "thread", "goal", ""],
            3,
        )

        self.assertEqual(matches, ["show", "set", "pause", "resume", "clear"])

    def test_feishu_codexctl_completes_thread_goal_set_options_and_status(self) -> None:
        option_matches = complete_words(
            "feishu-codexctl",
            ["feishu-codexctl", "thread", "goal", "set", "--"],
            4,
        )
        status_matches = complete_words(
            "feishu-codexctl",
            ["feishu-codexctl", "thread", "goal", "set", "--status", "p"],
            5,
        )

        self.assertEqual(
            option_matches,
            ["--thread-id", "--thread-name", "--objective", "--status", "--help"],
        )
        self.assertEqual(status_matches, ["paused"])

    def test_fcodex_skips_known_upstream_option_values_when_completing_resume(self) -> None:
        matches = complete_words(
            "fcodex",
            ["fcodex", "-p", "demo", ""],
            3,
        )

        self.assertEqual(matches, ["resume"])


if __name__ == "__main__":
    unittest.main()
