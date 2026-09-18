"""Bounded child processes for the independent browser updater."""

from __future__ import annotations

import os
import pathlib
import signal
import subprocess
import threading


class UpdateError(RuntimeError):
    """Safe operator-facing failure, without child output or credentials."""


class UpdateLaunchOutcomeUnknown(UpdateError):
    """The launcher timed out after submission may already have succeeded."""


def run(command: list[str], *, cwd: pathlib.Path, label: str, timeout: float = 1200,
        env: dict[str, str] | None = None) -> str:
    environment = dict(os.environ if env is None else env)
    environment = {k: v for k, v in environment.items() if not k.upper().startswith("PYTHON")}
    environment.update(GIT_TERMINAL_PROMPT="0", PIP_NO_INPUT="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    # Browser operations cannot open credential/host-key prompts. Use the host's
    # normal SSH keys/config/known_hosts, but never an interactive fallback.
    environment.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes -oStrictHostKeyChecking=yes")
    environment["GIT_ALLOW_PROTOCOL"] = "https:ssh"
    try:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    except OSError as exc:
        raise UpdateError(f"{label}: cannot start required tool") from exc
    tail = bytearray()

    def drain() -> None:
        assert process.stdout is not None
        while chunk := process.stdout.read(8192):
            tail.extend(chunk)
            del tail[:-65536]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise UpdateError(f"{label}: timed out") from exc
    finally:
        reader.join(timeout=5)
    if reader.is_alive():
        os.killpg(process.pid, signal.SIGKILL)
        reader.join(timeout=5)
        raise UpdateError(f"{label}: child processes did not exit")
    if process.returncode:
        # Raw pip/Git output may contain credential-bearing URLs. It is never
        # projected into the browser or a world-readable system journal.
        raise UpdateError(f"{label}: command failed (exit {process.returncode}); check host network, credentials and toolchain")
    return tail.decode("utf-8", "replace").strip()
