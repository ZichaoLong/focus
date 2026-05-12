import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from bot.bash_completion import complete_words, render_bash_completion_script


class BashCompletionTests(unittest.TestCase):
    def test_rendered_script_embeds_python_path_and_registrations(self) -> None:
        rendered = render_bash_completion_script(venv_python=pathlib.Path("/tmp/venv/bin/python"))

        self.assertIn("/tmp/venv/bin/python", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_feishu_codex feishu-codex", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_feishu_codexctl feishu-codexctl", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_feishu_codexd feishu-codexd", rendered)
        self.assertIn("complete -o bashdefault -o default -F _fc_complete_fcodex fcodex", rendered)

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

    def test_feishu_codexctl_completes_choice_options(self) -> None:
        matches = complete_words(
            "feishu-codexctl",
            ["feishu-codexctl", "thread", "memory", "--mode", "r"],
            4,
        )

        self.assertEqual(matches, ["read", "read_write"])

    def test_fcodex_skips_known_upstream_option_values_when_completing_resume(self) -> None:
        matches = complete_words(
            "fcodex",
            ["fcodex", "-p", "demo", ""],
            3,
        )

        self.assertEqual(matches, ["resume"])


if __name__ == "__main__":
    unittest.main()
