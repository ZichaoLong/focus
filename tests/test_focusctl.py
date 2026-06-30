import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from bot import focusctl
from bot.version import __version__


class FocusctlEntrypointTests(unittest.TestCase):
    def test_version_prints_project_version(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exc:
                focusctl.main(["--version"])

        self.assertEqual(exc.exception.code, 0)
        self.assertEqual(stdout.getvalue().strip(), f"focusctl {__version__}")

    def test_service_lifecycle_routes_to_manage_cli(self) -> None:
        with patch("bot.focusctl._run_manage") as mock_manage:
            focusctl.main(["--instance", "corp-a", "service", "restart"])

        mock_manage.assert_called_once_with(["--instance", "corp-a", "restart"])

    def test_service_runtime_status_routes_to_runtime_cli(self) -> None:
        with patch("bot.focusctl._run_runtime") as mock_runtime:
            focusctl.main(["--instance", "corp-a", "service", "status"])

        mock_runtime.assert_called_once_with(["--instance", "corp-a", "service", "status"])

    def test_service_list_routes_to_running_instance_view(self) -> None:
        with patch("bot.focusctl._run_runtime") as mock_runtime:
            focusctl.main(["service", "list"])

        mock_runtime.assert_called_once_with(["instance", "list"])

    def test_config_routes_to_manage_cli(self) -> None:
        with patch("bot.focusctl._run_manage") as mock_manage:
            focusctl.main(["config", "system", "--open"])

        mock_manage.assert_called_once_with(["config", "system", "--open"])

    def test_migrate_routes_to_manage_cli(self) -> None:
        with patch("bot.focusctl._run_manage") as mock_manage:
            focusctl.main(["migrate", "from-feishu-codex"])

        mock_manage.assert_called_once_with(["migrate", "from-feishu-codex"])

    def test_runtime_resource_routes_to_runtime_cli(self) -> None:
        with patch("bot.focusctl._run_runtime") as mock_runtime:
            focusctl.main(["thread", "list", "--scope", "cwd"])

        mock_runtime.assert_called_once_with(["thread", "list", "--scope", "cwd"])


if __name__ == "__main__":
    unittest.main()
