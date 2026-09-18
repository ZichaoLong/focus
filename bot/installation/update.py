"""Machine-wide browser-update journal, source and single-flight admission.

See docs/contracts/focus-web-update.zh-CN.md. Workers run outside the service
cgroup and the managed venv; only exact operation settlement can write results.
"""

from __future__ import annotations

import contextlib
import json
import math
import pathlib
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit

from bot.atomic_file import atomic_write_text
from bot.file_lock import acquire_file_lock, open_lock_file, release_file_lock
from bot.installation.update_process import UpdateError, UpdateLaunchOutcomeUnknown
from bot.platform_paths import default_data_root


DEFAULT_SOURCE = "https://github.com/ZichaoLong/focus.git"
STATES = {"idle", "checking", "ready", "applying", "succeeded", "failed", "unknown"}
PUBLIC_FIELDS = ("operation_id", "state", "requested_commit", "resolved_commit", "message",
                 "error", "preflight", "updated_at", "installation_started", "operation_source")
_PRIVATE_FIELDS = ("unit", "bundle_sha256", "staging_dir", "bundle_path", "wheelhouse_path", "offline_requirements")


def validate_source(value: str) -> str:
    try:
        url = urlsplit(value)
        valid = (value == value.strip() and 0 < len(value) <= 2048
                 and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)
                 and url.scheme in {"https", "ssh"} and url.hostname and url.path
                 and not url.password and not url.query and not url.fragment
                 and (url.scheme == "ssh" or url.username is None))
        url.port
    except (ValueError, TypeError, AttributeError) as exc:
        raise UpdateError("Invalid HTTPS/SSH Git URL") from exc
    if not valid:
        raise UpdateError("Use an HTTPS/SSH Git URL without passwords, query or fragment")
    return value


def validate_commit(value: str) -> str:
    if not isinstance(value, str) or (value and re.fullmatch(r"[0-9a-fA-F]{7,40}", value) is None):
        raise UpdateError("Enter a 7–40 character commit SHA, or leave empty for main")
    return value.lower()


def read_json(path: pathlib.Path) -> dict | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    if len(raw) > 256 * 1024:
        raise UpdateError("Update journal is too large; inspect it on the host")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except (ValueError, UnicodeError) as exc:
        raise UpdateError("Invalid update journal; inspect it on the host") from exc


def write_json(path: pathlib.Path, value: dict) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n", mode=0o600)


class UpdateJournal:
    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root).resolve()
        self.path = self.root / "web-update-operation.json"

    @contextlib.contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with open_lock_file(self.root / "web-update.lock") as handle:
            acquire_file_lock(handle, blocking=True)
            try:
                yield
            finally:
                release_file_lock(handle)

    def read(self) -> dict:
        value = read_json(self.path)
        if value is None:
            return dict(operation_id="", state="idle", requested_commit="", resolved_commit="",
                        operation_source=None, message="", error="", preflight={},
                        updated_at=0.0, installation_started=False, unit="", bundle_sha256="",
                        staging_dir="", bundle_path="", wheelhouse_path="", offline_requirements="")
        if (set(value) != {*PUBLIC_FIELDS, *_PRIVATE_FIELDS, "schema"}
                or value["schema"] != "focus-web-update-1"
                or not isinstance(value["state"], str) or value["state"] not in STATES
                or not isinstance(value["operation_id"], str)
                or re.fullmatch(r"[0-9a-f]{32}", value["operation_id"]) is None
                or type(value["installation_started"]) is not bool
                or type(value["updated_at"]) not in {float, int} or not math.isfinite(value["updated_at"])
                or not isinstance(value["preflight"], dict)
                or any(not isinstance(value[k], str) for k in ("unit", "bundle_sha256", "requested_commit", "resolved_commit", "message", "error", "staging_dir", "bundle_path", "wheelhouse_path", "offline_requirements"))):
            raise UpdateError("Invalid update journal; no update may proceed")
        source = value["operation_source"]
        if source is None:
            if value["state"] != "idle" or value["operation_id"]:
                raise UpdateError("Invalid pinned update source")
        elif not isinstance(source, dict) or set(source) != {"url", "branch"} or source["branch"] != "main":
            raise UpdateError("Invalid pinned update source")
        else:
            validate_source(source["url"])
        return value

    def write(self, value: dict) -> None:
        write_json(self.path, {**value, "schema": "focus-web-update-1", "updated_at": time.time()})

    def directory(self, operation_id: str) -> pathlib.Path:
        if re.fullmatch(r"[0-9a-f]{32}", operation_id) is None:
            raise UpdateError("Invalid update operation id")
        return self.root / "web-updates" / operation_id

    def settle(self, operation_id: str, expected: str, **changes) -> None:
        with self.locked():
            value = self.read()
            if value["operation_id"] != operation_id or value["state"] != expected:
                raise UpdateError("Update operation changed; refusing stale worker settlement")
            self.write({**value, **changes})


def unit_active(unit: str) -> bool | None:
    try:
        result = subprocess.run(["systemctl", "--user", "show", unit, "--property=ActiveState", "--value"],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    state = result.stdout.strip()
    if state in {"active", "activating", "reloading", "deactivating"}:
        return True
    if state in {"inactive", "failed"}:
        return False
    return None


def unavailable_reason() -> str:
    if not sys.platform.startswith("linux") or not shutil.which("systemd-run") or not shutil.which("systemctl"):
        return "Browser updates currently require Linux systemd user services"
    if pathlib.Path(sys.prefix).resolve() != (default_data_root() / ".venv").resolve():
        return "Browser updates require the managed Focus installation (use install.sh first)"
    return ""


def launch_worker(journal: UpdateJournal, operation_id: str, mode: str) -> None:
    from bot.installation.update_launcher import launch_update_worker

    launch_update_worker(journal, operation_id, mode)


class FocusUpdateController:
    def __init__(self, *, global_data_root: pathlib.Path):
        self.journal = UpdateJournal(global_data_root)
        self.source_path = self.journal.root / "web-update-source.json"

    def _source(self) -> dict:
        source = read_json(self.source_path)
        if source is None:
            return {"url": DEFAULT_SOURCE, "branch": "main"}
        if set(source) != {"url", "branch"} or source["branch"] != "main":
            raise UpdateError("Invalid update source configuration")
        return {"url": validate_source(source["url"]), "branch": "main"}

    def _snapshot(self) -> dict:
        value = self.journal.read()
        if value["state"] in {"checking", "applying"} and time.time() - value["updated_at"] > 30:
            active = unit_active(value["unit"])
            if active is False:
                value.update(
                    state="failed" if value["state"] == "checking" else "unknown",
                    error="Updater exited without a final result. Inspect the host before retrying.",
                )
                self.journal.write(value)
            elif active is None:
                value.update(
                    state="unknown",
                    error="Could not determine updater unit state. Inspect the host before retrying.",
                )
                self.journal.write(value)
        return {**{k: value[k] for k in PUBLIC_FIELDS}, "source": self._source(),
                "restart_required": value["state"] in {"applying", "succeeded", "unknown"} or value["installation_started"],
                }

    def _remove_staging(self, value: dict) -> None:
        """Remove only the current operation's staging tree under the journal root."""

        operation_id = value["operation_id"]
        if not operation_id:
            return
        staging = self.journal.directory(operation_id)
        if staging.is_symlink():
            raise UpdateError("Unsafe staging directory")
        if staging.exists():
            shutil.rmtree(staging)

    def snapshot(self) -> dict:
        with self.journal.locked():
            return self._snapshot()

    def configure_source(self, url: str, confirmation: str) -> dict:
        validate_source(url)
        if confirmation != "change-source":
            raise UpdateError("Changing the source requires explicit confirmation")
        with self.journal.locked():
            current = self.journal.read()
            if current["state"] in {"checking", "applying", "unknown"}:
                raise UpdateError("An update is active or its outcome is unknown")
            if current["state"] == "ready":
                self._remove_staging(current)
                self.journal.write({**current, "state": "failed", "error": "Source changed; prepare again"})
            write_json(self.source_path, {"url": url, "branch": "main"})
            return self._snapshot()

    def start_check(self, commit: str) -> dict:
        requested = validate_commit(commit)
        if reason := unavailable_reason():
            raise UpdateError(reason)
        with self.journal.locked():
            current = self.journal.read()
            if current["state"] in {"checking", "applying", "unknown"}:
                raise UpdateError("An update is active or its outcome is unknown")
            if current["operation_id"]:
                self._remove_staging(current)
            operation_id = secrets.token_hex(16)
            value = dict(operation_id=operation_id, state="checking", requested_commit=requested,
                         resolved_commit="", operation_source=self._source(), message="Preparing source and dependencies",
                         error="", preflight={}, updated_at=time.time(), installation_started=False,
                         unit=f"focus-update-{operation_id}-check.service", bundle_sha256="",
                         staging_dir="", bundle_path="", wheelhouse_path="", offline_requirements="")
            self.journal.write(value)
            # Once launch is attempted its outcome may be ambiguous; never
            # repeat this POST. GET reconciles the exact unit and journal.
            try:
                launch_worker(self.journal, operation_id, "check")
            except UpdateLaunchOutcomeUnknown as exc:
                value.update(state="unknown", error=str(exc))
                self.journal.write(value)
            except Exception as exc:
                value.update(state="failed", error=str(exc) or "Updater could not be started")
                self.journal.write(value)
            return self._snapshot()

    def apply(self, operation_id: str, confirmation: str) -> dict:
        if reason := unavailable_reason():
            raise UpdateError(reason)
        with self.journal.locked():
            value = self.journal.read()
            if (not operation_id or operation_id != confirmation or operation_id != value["operation_id"]
                    or value["state"] != "ready"):
                raise UpdateError("Only the exact prepared operation can be confirmed and applied")
            value.update(state="applying", message="Rechecking before shutdown", error="",
                         unit=f"focus-update-{operation_id}-apply.service")
            self.journal.write(value)
            try:
                launch_worker(self.journal, operation_id, "apply")
            except UpdateLaunchOutcomeUnknown as exc:
                value.update(state="unknown", error=str(exc))
                self.journal.write(value)
            except Exception as exc:
                value.update(state="failed", error=str(exc) or "Updater could not be started")
                self.journal.write(value)
            return self._snapshot()
