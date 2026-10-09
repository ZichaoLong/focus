import os
import time
from unittest.mock import patch

import pytest

from bot.focusctl import focusctl_command_schema, main


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    root = tmp_path / "data"
    monkeypatch.setenv("FOCUS_DATA_ROOT", str(root))
    monkeypatch.setenv("FOCUS_CONFIG_ROOT", str(tmp_path / "config"))
    monkeypatch.setenv("FOCUS_GLOBAL_DATA_DIR", str(root / "_global"))
    monkeypatch.setenv("FOCUS_INSTANCE", "default")
    return root


def run(*args):
    with pytest.raises(SystemExit) as result:
        main(list(args))
    return result.value.code


def test_logs_status_and_preview_leave_logs_untouched(data_root, capsys):
    data_root.mkdir()
    old = data_root / "focus.log.1"
    old.write_text("previous error")
    age = time.time() - 40 * 86400
    os.utime(old, (age, age))
    assert run("--instance", "default", "logs", "status") == 0
    assert "fcodex.log" in capsys.readouterr().out
    assert run("--instance", "default", "logs", "prune", "--dry-run") == 0
    assert "would remove" in capsys.readouterr().out
    assert old.read_text(encoding="utf-8") == "previous error"
    assert not (data_root / "diagnostic-logs.lock").exists()
    assert run("--instance", "default", "logs", "prune") == 0
    assert not old.exists()


def test_explicit_instance_cleanup_does_not_touch_other_instances(data_root):
    other = data_root / "instances" / "other"
    other.mkdir(parents=True)
    for root in (data_root, other):
        (root / "fcodex.log").write_text("error")
        (root / "focus.log").write_text("current service")
        (root / "bindings.json").write_text("state")
    assert run("--instance", "other", "logs", "prune", "--keep-days", "0") == 0
    assert not (other / "fcodex.log").exists()
    assert (data_root / "fcodex.log").exists()
    assert (other / "focus.log").read_text(encoding="utf-8") == "current service"
    assert (other / "bindings.json").read_text(encoding="utf-8") == "state"


def test_negative_retention_and_unknown_instance_do_not_create_data(data_root):
    assert run("--instance", "default", "logs", "prune", "--keep-days", "-1") == 2
    assert run("--instance", "missing", "logs", "status") == 2
    assert not data_root.exists()


def test_default_selection_uses_normal_instance_resolution(data_root):
    (data_root / "_global").mkdir(parents=True)
    with patch("bot.manage_cli.log_commands.resolve_cli_instance_target") as resolve:
        resolve.return_value.instance_name = "chosen"
        resolve.return_value.data_dir = data_root
        assert run("logs", "status") == 0
    resolve.assert_called_once_with(preferred_running_instance="default")


def test_completion_schema_contains_logs_and_cleanup_flags():
    logs = focusctl_command_schema().subcommand("logs")
    assert logs.subcommand("status") is not None
    flags = {
        name for option in logs.subcommand("prune").options for name in option.names
    }
    assert {"--dry-run", "--keep-days"} <= flags
