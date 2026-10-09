import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

from bot.service_log_capture import capture_service


def test_captures_output_and_propagates_exit_status(tmp_path):
    result = capture_service(
        [
            sys.executable,
            "-c",
            "import os; os.write(1, b'hello\\n'); os.write(2, b'error\\n'); exit(7)",
        ],
        tmp_path,
    )
    assert result == 7
    assert (tmp_path / "service.stdout.log").read_text(encoding="utf-8") == "hello\n"
    assert (tmp_path / "service.stderr.log").read_text(encoding="utf-8") == "error\n"


@pytest.mark.parametrize("fd,name", [(1, "stdout"), (2, "stderr")])
def test_captures_partial_unicode_and_large_lines_with_bounded_memory(
    tmp_path, fd, name
):
    script = f"import os; os.write({fd}, b'x' * 100000); os.write({fd}, bytes([228,184])); os.write({fd}, bytes([173,10]))"
    assert capture_service([sys.executable, "-c", script], tmp_path) == 0
    content = (tmp_path / f"service.{name}.log").read_text(encoding="utf-8")
    assert content == "x" * 100000 + "中\n"


def test_failed_launch_is_recorded(tmp_path):
    assert capture_service([str(tmp_path / "missing-command")], tmp_path) == 1
    assert "service launch failed" in (tmp_path / "service.stderr.log").read_text(
        encoding="utf-8"
    )


@pytest.mark.skipif(os.name == "nt", reason="launchd signal supervision is POSIX-only")
def test_stop_reaches_child_and_allows_graceful_shutdown(tmp_path):
    ready = tmp_path / "ready"
    script = (
        "import pathlib, signal, sys, time; "
        "signal.signal(signal.SIGTERM, lambda *_: (print('stopped', flush=True), sys.exit(0))); "
        "pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(30)"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "bot.service_log_capture",
            "--data-dir",
            str(tmp_path),
            "--",
            sys.executable,
            "-c",
            script,
            str(ready),
        ],
        cwd=pathlib.Path(__file__).resolve().parents[1],
    )
    try:
        deadline = time.monotonic() + 8
        while (
            not ready.exists()
            and process.poll() is None
            and time.monotonic() < deadline
        ):
            time.sleep(0.02)
        assert ready.exists()
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=12) == 0
        assert "stopped" in (tmp_path / "service.stdout.log").read_text(
            encoding="utf-8"
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
