"""Machine-wide browser-update journal, source and single-flight admission.

See docs/contracts/focus-web-update.zh-CN.md. Workers run outside the service
cgroup and the managed venv; only exact operation progress/settlement can write results.
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
from bot.installation.update_discovery import installed_build, installation_id, resolve_candidate
from bot.installation.update_process import UpdateError, UpdateLaunchOutcomeUnknown
from bot.platform_paths import default_data_root


DEFAULT_SOURCE = "https://github.com/ZichaoLong/focus.git"
UPDATE_TARGETS = frozenset({"stable", "main"})
STATES = {"idle", "checking", "cancelling", "cancelled", "ready", "applying", "succeeded", "failed", "unknown"}
UPDATE_SCHEMA = "focus-web-update-3"
UPDATE_PHASES = frozenset(
    {
        "idle",
        "starting",
        "cancelling",
        "cancelled",
        "disk_preflight",
        "release_metadata",
        "release_download",
        "release_verify",
        "source_clone",
        "source_revision",
        "node_preflight",
        "npm_install",
        "web_build",
        "bundle_build",
        "bundle_validate",
        "python_preflight",
        "dependency_download",
        "wheelhouse_verify",
        "final_disk_check",
        "apply_validate",
        "apply_prepare",
        "apply_install",
        "apply_restart",
        "ready",
        "succeeded",
        "failed",
        "unknown",
    }
)
UPDATE_PROGRESS_UNITS = frozenset({"bytes"})
PUBLIC_FIELDS = ("operation_id", "target", "state", "requested_commit", "resolved_commit", "message",
                 "error", "preflight", "updated_at", "installation_started", "operation_source",
                 "phase", "phase_started_at", "last_progress_at", "progress")
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


def validate_target(value: str) -> str:
    if value not in UPDATE_TARGETS:
        raise UpdateError("Update target must be stable or main")
    return value


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


def _phase_for_state(state: object) -> str:
    if isinstance(state, str) and state in STATES:
        return {
            "idle": "idle",
            "checking": "starting",
            "cancelling": "cancelling",
            "cancelled": "cancelled",
            "ready": "ready",
            "applying": "apply_validate",
            "succeeded": "succeeded",
            "failed": "failed",
            "unknown": "unknown",
        }[state]
    return "idle"


def _valid_progress(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or set(value) != {"current", "total", "unit"}:
        return False
    current = value["current"]
    total = value["total"]
    return (
        type(current) is int
        and current >= 0
        and (total is None or (type(total) is int and total > 0 and current <= total))
        and isinstance(value["unit"], str)
        and value["unit"] in UPDATE_PROGRESS_UNITS
    )


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
            return dict(operation_id="", target="", state="idle", requested_commit="", resolved_commit="",
                        operation_source=None, message="", error="", preflight={},
                        updated_at=0.0, installation_started=False, unit="", bundle_sha256="",
                        staging_dir="", bundle_path="", wheelhouse_path="", offline_requirements="",
                        phase="idle", phase_started_at=0.0, last_progress_at=0.0, progress=None)
        if value.get("schema") in {"focus-web-update-1", "focus-web-update-2"}:
            # The original browser updater only built from the configured main
            # source. Preserve an existing idle/ready journal when the target
            # field is introduced; a new write upgrades it to schema 3.
            if value.get("schema") == "focus-web-update-1" and "target" not in value:
                value = {
                    **value,
                    "target": "main" if value.get("operation_id") else "",
                }
            value = {
                **value,
                "schema": UPDATE_SCHEMA,
                "phase": _phase_for_state(value.get("state")),
                "phase_started_at": value.get("updated_at", 0.0),
                "last_progress_at": value.get("updated_at", 0.0),
                "progress": None,
            }
        if (set(value) != {*PUBLIC_FIELDS, *_PRIVATE_FIELDS, "schema"}
                or value["schema"] != UPDATE_SCHEMA
                or not isinstance(value["state"], str) or value["state"] not in STATES
                or not isinstance(value["operation_id"], str)
                or not isinstance(value["target"], str)
                or (value["target"] and value["target"] not in UPDATE_TARGETS)
                or re.fullmatch(r"[0-9a-f]{32}", value["operation_id"]) is None
                or type(value["installation_started"]) is not bool
                or type(value["updated_at"]) not in {float, int} or not math.isfinite(value["updated_at"])
                or not isinstance(value["phase"], str) or value["phase"] not in UPDATE_PHASES
                or type(value["phase_started_at"]) not in {float, int} or not math.isfinite(value["phase_started_at"])
                or value["phase_started_at"] < 0
                or type(value["last_progress_at"]) not in {float, int} or not math.isfinite(value["last_progress_at"])
                or value["last_progress_at"] < 0
                or not _valid_progress(value["progress"])
                or not isinstance(value["preflight"], dict)
                or any(not isinstance(value[k], str) for k in ("unit", "bundle_sha256", "requested_commit", "resolved_commit", "message", "error", "staging_dir", "bundle_path", "wheelhouse_path", "offline_requirements"))):
            raise UpdateError("Invalid update journal; no update may proceed")
        source = value["operation_source"]
        if source is None:
            if value["target"] == "main" or (value["target"] == "" and value["operation_id"]):
                raise UpdateError("Invalid pinned update source")
        elif value["target"] != "main" or not isinstance(source, dict) or set(source) != {"url", "branch"} or source["branch"] != "main":
            raise UpdateError("Invalid pinned update source")
        else:
            validate_source(source["url"])
        return value

    def write(self, value: dict) -> None:
        write_json(self.path, {**value, "schema": UPDATE_SCHEMA, "updated_at": time.time()})

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

    def progress(
        self,
        operation_id: str,
        expected: str,
        *,
        phase: str,
        message: str,
        progress: dict | None = None,
    ) -> None:
        if phase not in UPDATE_PHASES:
            raise UpdateError("Invalid update progress phase")
        if not _valid_progress(progress):
            raise UpdateError("Invalid update progress payload")
        with self.locked():
            value = self.read()
            if value["operation_id"] != operation_id or value["state"] != expected:
                raise UpdateError("Update operation changed; refusing stale worker progress")
            now = time.time()
            phase_started_at = now if value["phase"] != phase else value["phase_started_at"]
            self.write({
                **value,
                "phase": phase,
                "phase_started_at": phase_started_at,
                "last_progress_at": now,
                "progress": progress,
                "message": message,
            })


def unit_active(unit: str) -> bool | None:
    try:
        result = subprocess.run(["systemctl", "--user", "show", unit, "--property=ActiveState", "--property=Job"],
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    observed = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if result.returncode or "Job" not in observed:
        return None
    # An inactive unit with a queued start/stop job is not proof that its work
    # has ended. Do not release single-flight admission until that job settles.
    if observed["Job"]:
        return True
    state = observed.get("ActiveState", "")
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


def stop_check_worker(unit: str) -> None:
    """Queue a stop of the check's complete cgroup; observation confirms completion."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "stop", "--no-block", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpdateError("Could not confirm the cancellation request; refresh status or retry cancellation") from exc
    if result.returncode:
        raise UpdateError("Could not stop the update check; refresh status or retry cancellation")


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
        if value["state"] == "cancelling":
            active = unit_active(value["unit"])
            if active is False:
                try:
                    self._remove_staging(value)
                except (OSError, UpdateError):
                    value["error"] = "Check stopped, but staging cleanup failed; refresh status or retry cancellation"
                else:
                    now = time.time()
                    value.update(
                        state="cancelled", phase="cancelled", phase_started_at=now,
                        last_progress_at=now, progress=None, error="", preflight={},
                        message="Update preparation cancelled; the installed Focus is unchanged",
                        bundle_sha256="", staging_dir="", bundle_path="", wheelhouse_path="",
                        offline_requirements="",
                    )
                self.journal.write(value)
            elif active is None and not value["error"]:
                value["error"] = "Cannot confirm that the check has stopped; preparation remains blocked"
                self.journal.write(value)
        if value["state"] in {"checking", "applying"} and time.time() - value["updated_at"] > 30:
            active = unit_active(value["unit"])
            if active is False:
                now = time.time()
                value.update(
                    state="failed" if value["state"] == "checking" else "unknown",
                    error="Updater exited without a final result. Inspect the host before retrying.",
                    phase="failed" if value["state"] == "checking" else "unknown",
                    phase_started_at=now,
                    last_progress_at=now,
                    progress=None,
                )
                self.journal.write(value)
            elif active is None:
                now = time.time()
                value.update(
                    state="unknown",
                    error="Could not determine updater unit state. Inspect the host before retrying.",
                    phase="unknown",
                    phase_started_at=now,
                    last_progress_at=now,
                    progress=None,
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

    @staticmethod
    def _recoverable_unknown_check(value: dict) -> bool:
        """Allow an explicit retry after a check-only launcher outcome is settled."""

        return (
            value["state"] == "unknown"
            and value["unit"].endswith("-check.service")
            and not value["installation_started"]
            and unit_active(value["unit"]) is False
        )

    def snapshot(self) -> dict:
        with self.journal.locked():
            return self._snapshot()

    def configure_source(self, url: str, confirmation: str) -> dict:
        validate_source(url)
        if confirmation != "change-source":
            raise UpdateError("Changing the source requires explicit confirmation")
        with self.journal.locked():
            current = self.journal.read()
            if current["state"] in {"checking", "cancelling", "applying"} or (
                current["state"] == "unknown"
                and not self._recoverable_unknown_check(current)
            ):
                raise UpdateError("An update is active or its outcome is unknown")
            if current["state"] == "ready":
                self._remove_staging(current)
                now = time.time()
                self.journal.write({
                    **current,
                    "state": "failed",
                    "error": "Source changed; prepare again",
                    "phase": "failed",
                    "phase_started_at": now,
                    "last_progress_at": now,
                    "progress": None,
                })
            write_json(self.source_path, {"url": url, "branch": "main"})
            return self._snapshot()

    def start_check(self, target: str, commit: str | None = None) -> dict:
        if commit is None:
            # Keep direct callers from the pre-target API on the safe main
            # path; browser requests always provide an explicit target.
            commit = target
            target = "main"
        target = validate_target(target)
        requested = validate_commit(commit)
        if target == "stable" and requested:
            raise UpdateError("Stable updates do not accept a commit; choose main for a commit")
        if reason := unavailable_reason():
            raise UpdateError(reason)
        with self.journal.locked():
            current = self.journal.read()
            if current["state"] in {"checking", "cancelling", "applying"} or (
                current["state"] == "unknown"
                and not self._recoverable_unknown_check(current)
            ):
                raise UpdateError("An update is active or its outcome is unknown")
            return self._start_locked(current, target, requested)

    def _start_locked(self, current: dict, target: str, requested: str, *, preflight: dict | None = None) -> dict:
        operation_id = secrets.token_hex(16)
        if current["operation_id"]:
            self._remove_staging(current)
        now = time.time()
        value = dict(operation_id=operation_id, target=target, state="checking", requested_commit=requested,
                     resolved_commit="", operation_source=self._source() if target == "main" else None,
                     message="Preparing the update check",
                     error="", preflight=preflight or {}, updated_at=time.time(), installation_started=False,
                     unit=f"focus-update-{operation_id}-check.service", bundle_sha256="",
                     staging_dir="", bundle_path="", wheelhouse_path="", offline_requirements="",
                     phase="starting", phase_started_at=now, last_progress_at=now, progress=None)
        self.journal.write(value)
        # Once launch is attempted its outcome may be ambiguous; never
        # repeat this POST. GET reconciles the exact unit and journal.
        try:
            launch_worker(self.journal, operation_id, "check")
        except UpdateLaunchOutcomeUnknown as exc:
            now = time.time()
            value.update(state="unknown", error=str(exc), phase="unknown",
                         phase_started_at=now, last_progress_at=now, progress=None)
            self.journal.write(value)
        except Exception as exc:
            now = time.time()
            value.update(state="failed", error=str(exc) or "Updater could not be started",
                         phase="failed", phase_started_at=now, last_progress_at=now, progress=None)
            self.journal.write(value)
        return self._snapshot()

    def installation_status(self) -> dict:
        with self.journal.locked():
            return self._installation_status_locked()

    def _installation_status_locked(self) -> dict:
        status = self._snapshot()
        installed = installed_build(self.journal.root)
        fields = ("operation_id", "target", "state", "requested_commit", "resolved_commit",
                  "phase", "progress", "message", "error")
        return {"installation_id": installation_id(self.journal.root), "installed": installed,
                "request_id": status["preflight"].get("batch_request_id", ""),
                "operation": {key: status[key] for key in fields}}

    def prepare_latest(self, install_id: str, channel: str, previous: str, request_id: str) -> dict:
        if (channel not in {"installed", "main", "stable"} or not re.fullmatch("[a-f0-9]{32}", request_id)):
            raise UpdateError("Invalid batch preparation")
        if reason := unavailable_reason():
            raise UpdateError(reason)
        with self.journal.locked():
            before = self._installation_status_locked()
            op = before["operation"]
            if before["installation_id"] != install_id or op["operation_id"] != previous:
                raise UpdateError("安装或更新记录已更换，请重新检查")
            if op["state"] in {"checking", "applying", "cancelling", "unknown"}:
                raise UpdateError("已有操作进行中或结果待核实，请查看实例的服务端更新")
            installed = before["installed"]
            if channel == "installed" and not installed:
                raise UpdateError("没有已安装渠道记录，请选择 main 或 stable")
            target = ("stable" if installed["channel"] == "stable" else "main") if channel == "installed" else channel
            source = self._source() if target == "main" else None

        # Remote I/O never holds the shared journal lock. Compare the full observed
        # operation and source again before allowing the single-flight transition.
        candidate = resolve_candidate(target, source, self.journal.root)
        with self.journal.locked():
            now = self._installation_status_locked()
            if before != now or (source and self._source() != source):
                raise UpdateError("检查期间安装、更新源或操作已变化，请重新检查")
            current = self.journal.read()
            revision = candidate["revision"]
            same = (installed and installed["source_revision"] == revision and
                    installed["channel"] == ("stable" if target == "stable" else "local") and
                    (target == "main" or (installed["build_id"], installed["version"]) ==
                     (candidate["build_id"], candidate["version"])))
            if same:
                outcome = "current"
            elif (op["state"] == "ready" and op["target"] == target and op["resolved_commit"] == revision
                  and current["operation_source"] == source and current["preflight"].get("python_runtime") and
                  (target == "main" or current["bundle_sha256"] == candidate["digest"])):
                outcome = "prepared"
            else:
                pins = {"batch_request_id": request_id}
                if candidate["digest"]:
                    pins["stable_sha256"] = candidate["digest"]
                self._start_locked(current, target, revision, preflight=pins)
                now = self._installation_status_locked()
                outcome = "prepared"
            return {**now, "outcome": outcome, "target": target, "revision": revision, "version": candidate["version"]}

    def cancel_check(self, operation_id: str) -> dict:
        if reason := unavailable_reason():
            raise UpdateError(reason)
        with self.journal.locked():
            value = self.journal.read()
            if (not operation_id or operation_id != value["operation_id"]
                    or value["state"] not in {"checking", "ready", "cancelling", "cancelled"}
                    or value["installation_started"]
                    or value["unit"] != f"focus-update-{operation_id}-check.service"):
                raise UpdateError("Only the exact update preparation can be cancelled; installation cannot be cancelled")
            if value["state"] == "cancelled" or (value["state"] == "cancelling" and not value["error"]):
                return self._snapshot()
            now = time.time()
            value.update(state="cancelling", phase="cancelling", phase_started_at=now,
                         last_progress_at=now, progress=None, error="",
                         message="Stopping update preparation; waiting for the check and its child processes to exit")
            # This exact-state transition fences ready publication and apply,
            # including a check which finishes just as the user cancels it.
            self.journal.write(value)
            try:
                stop_check_worker(value["unit"])
            except UpdateError as exc:
                value["error"] = str(exc)
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
            now = time.time()
            value.update(state="applying", message="Rechecking before shutdown", error="",
                         unit=f"focus-update-{operation_id}-apply.service", phase="apply_validate",
                         phase_started_at=now, last_progress_at=now, progress=None)
            self.journal.write(value)
            try:
                launch_worker(self.journal, operation_id, "apply")
            except UpdateLaunchOutcomeUnknown as exc:
                now = time.time()
                value.update(state="unknown", error=str(exc), phase="unknown",
                             phase_started_at=now, last_progress_at=now, progress=None)
                self.journal.write(value)
            except Exception as exc:
                now = time.time()
                value.update(state="failed", error=str(exc) or "Updater could not be started",
                             phase="failed", phase_started_at=now, last_progress_at=now, progress=None)
                self.journal.write(value)
            return self._snapshot()
