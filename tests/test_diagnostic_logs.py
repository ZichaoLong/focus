import json
import logging
import os
import pathlib
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from bot.diagnostic_logs import (
    DiagnosticLogHandler,
    LogPolicy,
    append_log,
    log_inventory,
    prune_logs,
    start_log_maintenance,
)
from bot.fcodex.diagnostics import FcodexDiagnostics
from bot.file_lock import acquire_file_lock, open_lock_file, release_file_lock


def test_rotation_bounds_files_and_keeps_newest_records(tmp_path):
    policy = LogPolicy("fcodex.log", 64, 2)
    with patch("bot.diagnostic_logs.LOG_POLICIES", (policy,)):
        for index in range(15):
            assert append_log(tmp_path, "fcodex.log", f"{index:02d} {'x' * 25}\n")
        files = log_inventory(tmp_path)
    assert len(files) == 3
    assert sum(entry.size for entry in files) <= 192
    assert "14 " in (tmp_path / "fcodex.log").read_text(encoding="utf-8")
    assert "00 " not in "".join(
        entry.path.read_text(encoding="utf-8") for entry in files
    )


def test_prune_preview_scope_age_and_active_file_rules(tmp_path):
    old = time.time() - 40 * 86400
    for name in (
        "fcodex.log",
        "focus.log.1",
        "service.stderr.log.1",
        "focus.log",
        "service.stderr.log",
        "sessions.jsonl",
        "state.sqlite",
        "focus.log.99",
    ):
        path = tmp_path / name
        path.write_text("keep evidence")
        os.utime(path, (old, old))
    (tmp_path / "fcodex.log.1").write_text("recent")
    before = {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()}
    preview = prune_logs(tmp_path, dry_run=True)
    assert {entry.path.name for entry in preview} == {
        "fcodex.log",
        "focus.log.1",
        "service.stderr.log.1",
    }
    assert {entry.name: entry.read_bytes() for entry in tmp_path.iterdir()} == before
    removed = prune_logs(tmp_path)
    assert removed == preview
    for name in (
        "focus.log",
        "service.stderr.log",
        "sessions.jsonl",
        "state.sqlite",
        "focus.log.99",
        "fcodex.log.1",
    ):
        assert (tmp_path / name).exists()


def test_inspection_does_not_create_missing_directory(tmp_path):
    missing = tmp_path / "not-installed"
    assert log_inventory(missing) == []
    assert prune_logs(missing, dry_run=True) == []
    assert prune_logs(missing) == []
    assert not missing.exists()


def test_automatic_maintenance_cleans_at_startup_and_while_running(tmp_path):
    def expired(name):
        path = tmp_path / name
        path.write_text("old error")
        old = time.time() - 40 * 86400
        os.utime(path, (old, old))
        return path

    first = expired("focus.log.1")
    with patch("bot.diagnostic_logs.MAINTENANCE_SECONDS", 0.01):
        stopped = start_log_maintenance(tmp_path)
        try:
            assert not first.exists()
            later = expired("fcodex.log")
            deadline = time.monotonic() + 2
            while later.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert not later.exists()
        finally:
            stopped.set()


def test_daily_fcodex_rotation_and_explicit_clear_with_future_mtime(tmp_path):
    current = tmp_path / "fcodex.log"
    assert append_log(tmp_path, "fcodex.log", "yesterday\n")
    yesterday = time.time() - 86400
    os.utime(current, (yesterday, yesterday))
    assert append_log(tmp_path, "fcodex.log", "today\n")
    assert current.read_text(encoding="utf-8") == "today\n"
    assert (tmp_path / "fcodex.log.1").read_text(encoding="utf-8") == "yesterday\n"
    future = time.time() + 86400
    os.utime(current, (future, future))
    prune_logs(tmp_path, keep_days=0)
    assert not current.exists()


def test_cleanup_and_rotation_do_not_follow_symlinks(tmp_path):
    target = tmp_path / "conversation.txt"
    target.write_text("conversation data")
    link = tmp_path / "fcodex.log.1"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert prune_logs(tmp_path, keep_days=0) == []
    assert link.is_symlink()
    current = tmp_path / "fcodex.log"
    current.write_text("too large")
    with patch("bot.diagnostic_logs.LOG_POLICIES", (LogPolicy("fcodex.log", 8, 1),)):
        assert not append_log(tmp_path, "fcodex.log", "next")
    assert target.read_text(encoding="utf-8") == "conversation data"


def test_busy_or_broken_log_sink_never_breaks_logging(tmp_path):
    handler = DiagnosticLogHandler(tmp_path)
    record = logging.LogRecord("test", logging.ERROR, "", 0, "a failure", (), None)
    with open_lock_file(tmp_path / "diagnostic-logs.lock") as lock:
        acquire_file_lock(lock, blocking=False)
        try:
            assert not append_log(tmp_path, "fcodex.log", "busy\n")
            handler.emit(record)
        finally:
            release_file_lock(lock)
    (tmp_path / "focus.log").mkdir()
    handler.emit(record)
    assert not (tmp_path / "fcodex.log").exists()


def test_diagnostics_redaction_throttling_and_no_rpc_payloads(tmp_path):
    diagnostics = FcodexDiagnostics(tmp_path, instance_name="test")
    error = (
        'Authorization: Bearer token-one api_key="token-two" access_token=token-three'
    )
    with patch("bot.fcodex.diagnostics.time.monotonic", return_value=10):
        for index in range(5):
            diagnostics.record(
                "upstream_error",
                method="config/batchWrite",
                request_id=index,
                code=-1,
                message=error,
            )
    first = json.loads((tmp_path / "fcodex.log").read_text(encoding="utf-8"))
    assert first["method"] == "config/batchWrite"
    assert first["code"] == "-1"
    assert first["suppressed"] == 0
    assert "token-" not in first["message"]
    diagnostics.close()
    records = [
        json.loads(line)
        for line in (tmp_path / "fcodex.log").read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 2
    assert records[-1]["suppressed"] == 4


def test_rate_limit_window_and_memory_are_bounded(tmp_path):
    diagnostics = FcodexDiagnostics(tmp_path)
    with patch("bot.fcodex.diagnostics.time.monotonic", return_value=10):
        diagnostics.record("failure", method="config/batchWrite")
        diagnostics.record("failure", method="config/batchWrite")
    with patch("bot.fcodex.diagnostics.time.monotonic", return_value=71):
        diagnostics.record("failure", method="config/batchWrite")
    assert (
        json.loads(
            (tmp_path / "fcodex.log").read_text(encoding="utf-8").splitlines()[-1]
        )["suppressed"]
        == 1
    )
    for index in range(200):
        diagnostics.record("failure", method=f"method/{index}")
    assert len(diagnostics._recent) == 128


def test_transient_sink_failure_does_not_suppress_next_failure(tmp_path):
    diagnostics = FcodexDiagnostics(tmp_path)
    with patch("bot.fcodex.diagnostics.append_log", return_value=False):
        diagnostics.record("failure", method="config/batchWrite")
    diagnostics.record("failure", method="config/batchWrite")
    record = json.loads((tmp_path / "fcodex.log").read_text(encoding="utf-8"))
    assert record["method"] == "config/batchWrite"


def test_large_record_and_legacy_capture_are_bounded(tmp_path):
    (tmp_path / "service.stderr.log").write_bytes(b"x" * (3 * 1024 * 1024))
    assert append_log(tmp_path, "service.stderr.log", "new error\n")
    assert (tmp_path / "service.stderr.log.1").stat().st_size == 2 * 1024 * 1024
    assert append_log(tmp_path, "focus.log", "x" * (3 * 1024 * 1024))
    assert (tmp_path / "focus.log").stat().st_size <= 64 * 1024


def test_concurrent_process_writes_and_pruning_preserve_json_records(tmp_path):
    script = """
import json, pathlib, sys
from bot.diagnostic_logs import append_log, prune_logs
directory = pathlib.Path(sys.argv[1])
written = []
for i in range(250):
    record = {"id": sys.argv[2] + ":" + str(i), "message": "x" * 4096}
    if append_log(directory, "fcodex.log", json.dumps(record) + "\\n"):
        written.append(record["id"])
    if i % 20 == 0:
        try:
            prune_logs(directory)
        except OSError:
            pass
print(json.dumps(written))
"""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), str(i)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=pathlib.Path(__file__).resolve().parents[1],
        )
        for i in range(3)
    ]
    expected = set()
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        expected.update(json.loads(stdout))
    actual = []
    for entry in log_inventory(tmp_path):
        actual.extend(
            json.loads(line)["id"]
            for line in entry.path.read_text(encoding="utf-8").splitlines()
        )
    assert expected
    assert len(actual) == len(set(actual))
    assert set(actual) == expected
