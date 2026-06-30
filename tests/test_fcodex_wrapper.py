import os
import unittest
from unittest.mock import patch

from bot.fcodex import _program_name


class FcodexWrapperTests(unittest.TestCase):
    def test_program_name_prefers_installed_wrapper_command_env(self) -> None:
        with patch.dict(os.environ, {"FOCUS_WRAPPER_COMMAND": "fcodex"}, clear=False):
            with patch("sys.argv", ["-c", "--version"]):
                self.assertEqual(_program_name(), "fcodex")

    def test_program_name_ignores_unknown_wrapper_command_env(self) -> None:
        with patch.dict(os.environ, {"FOCUS_WRAPPER_COMMAND": "unexpected"}, clear=False):
            with patch("sys.argv", ["/tmp/focus", "--version"]):
                self.assertEqual(_program_name(), "focus")


if __name__ == "__main__":
    unittest.main()
