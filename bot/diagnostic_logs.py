"""Bounded, process-coordinated diagnostic files; never conversation/state stores.

The public retention and cleanup contract lives in focusctl-command-matrix.
"""

from __future__ import annotations

import atexit
import logging
import pathlib
import stat
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

from bot.file_lock import (
    FileLockBusyError,
    acquire_file_lock,
    open_lock_file,
    release_file_lock,
)

RETENTION_DAYS = 30
MAINTENANCE_SECONDS = 30 * 60
_MAX_RECORD_BYTES = 64 * 1024


@dataclass(frozen=True)
class LogPolicy:
    name: str
    max_bytes: int
    backups: int


LOG_POLICIES = (
    LogPolicy("focus.log", 2 * 1024 * 1024, 3),
    LogPolicy("fcodex.log", 512 * 1024, 31),
    LogPolicy("service.stdout.log", 2 * 1024 * 1024, 3),
    LogPolicy("service.stderr.log", 2 * 1024 * 1024, 3),
)


@dataclass(frozen=True)
class LogFile:
    path: pathlib.Path
    size: int
    modified: float
    policy: LogPolicy
    current: bool


def _metadata(path: pathlib.Path):
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    return metadata if stat.S_ISREG(metadata.st_mode) else None


def log_inventory(data_dir: pathlib.Path) -> list[LogFile]:
    """Inspect only exact owned names, without creating directories or locks."""
    result = []
    for policy in LOG_POLICIES:
        for index in range(policy.backups + 1):
            path = data_dir / (f"{policy.name}.{index}" if index else policy.name)
            metadata = _metadata(path)
            if metadata is not None:
                result.append(
                    LogFile(
                        path, metadata.st_size, metadata.st_mtime, policy, index == 0
                    )
                )
    return result


@contextmanager
def _log_lock(data_dir: pathlib.Path):
    with open_lock_file(data_dir / "diagnostic-logs.lock") as handle:
        # Allow short concurrent writes to finish, but never wait indefinitely
        # for a stuck process. The same lock covers append, rotation and pruning.
        deadline = time.monotonic() + 0.05
        while True:
            try:
                acquire_file_lock(handle, blocking=False)
                break
            except FileLockBusyError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.002)
        try:
            yield
        finally:
            release_file_lock(handle)


def _prune_candidates(
    data_dir: pathlib.Path, keep_days: int, now: float
) -> list[LogFile]:
    files = log_inventory(data_dir)
    cutoff = now - keep_days * 86400
    selected = {
        entry.path: entry
        for entry in files
        if (keep_days == 0 or entry.modified < cutoff)
        and (not entry.current or entry.policy.name == "fcodex.log")
    }
    for policy in LOG_POLICIES:
        remaining = [
            entry
            for entry in files
            if entry.policy == policy and entry.path not in selected
        ]
        size = sum(entry.size for entry in remaining)
        for entry in sorted(remaining, key=lambda item: item.modified):
            if size <= policy.max_bytes * (policy.backups + 1):
                break
            if not entry.current:
                selected[entry.path] = entry
                size -= entry.size
    return sorted(selected.values(), key=lambda item: str(item.path))


def prune_logs(
    data_dir: pathlib.Path, *, keep_days: int = RETENTION_DAYS, dry_run: bool = False
) -> list[LogFile]:
    """Clean closed files, plus expired fcodex files (opened only under our lock)."""
    if keep_days < 0:
        raise ValueError("keep-days 必须大于或等于 0。")
    if dry_run or not data_dir.exists():
        return _prune_candidates(data_dir, keep_days, time.time())
    with _log_lock(data_dir):
        candidates = _prune_candidates(data_dir, keep_days, time.time())
        for entry in candidates:
            entry.path.unlink(missing_ok=True)
        return candidates


def _rotate(data_dir: pathlib.Path, policy: LogPolicy) -> None:
    for index in range(policy.backups, 0, -1):
        source = data_dir / (f"{policy.name}.{index - 1}" if index > 1 else policy.name)
        target = data_dir / f"{policy.name}.{index}"
        if _metadata(source) is None:
            continue
        if target.is_symlink() or (target.exists() and _metadata(target) is None):
            raise OSError(f"not a regular diagnostic log: {target}")
        source.replace(target)
    # Bound a pre-existing oversized capture when upgrading an old installation.
    previous = data_dir / f"{policy.name}.1"
    metadata = _metadata(previous)
    if metadata is not None and metadata.st_size > policy.max_bytes:
        with previous.open("r+b") as handle:
            handle.seek(-policy.max_bytes, 2)
            tail = handle.read(policy.max_bytes)
            handle.seek(0)
            handle.write(tail)
            handle.truncate()


def append_log(data_dir: pathlib.Path, name: str, text: str) -> bool:
    """Best effort append, with no persistent file descriptor across rotations."""
    try:
        policy = next(policy for policy in LOG_POLICIES if policy.name == name)
        encoded = text.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_RECORD_BYTES:
            encoded = (
                encoded[: _MAX_RECORD_BYTES - 48] + b"\n[diagnostic record truncated]\n"
            )
        rendered = encoded.decode("utf-8", errors="replace")
        data_dir.mkdir(parents=True, exist_ok=True)
        with _log_lock(data_dir):
            path = data_dir / name
            metadata = _metadata(path)
            if metadata is not None and (
                metadata.st_size + len(rendered.encode("utf-8")) > policy.max_bytes
                or (
                    name == "fcodex.log"
                    and int(metadata.st_mtime // 86400) != int(time.time() // 86400)
                )
            ):
                _rotate(data_dir, policy)
            with open_lock_file(path) as handle:
                handle.write(rendered)
        return True
    except Exception:
        # Do not recurse into logging, write tracebacks to the TUI, or change RPC outcomes.
        return False


class DiagnosticLogHandler(logging.Handler):
    def __init__(self, data_dir: pathlib.Path) -> None:
        super().__init__()
        self.data_dir = data_dir

    def emit(self, record: logging.LogRecord) -> None:
        try:
            append_log(self.data_dir, "focus.log", self.format(record) + "\n")
        except Exception:
            pass


def start_log_maintenance(data_dir: pathlib.Path) -> threading.Event:
    """Run inside the existing service; returning the stop event also aids teardown."""
    stopped = threading.Event()

    def sweep() -> None:
        try:
            prune_logs(data_dir)
        except Exception:
            pass

    def maintain() -> None:
        while not stopped.wait(MAINTENANCE_SECONDS):
            sweep()

    sweep()
    threading.Thread(target=maintain, name="focus-log-retention", daemon=True).start()
    atexit.register(stopped.set)
    return stopped
