"""One-shot transfer from the old feishu-codex local install to FOCUS."""

from __future__ import annotations

import filecmp
import json
import ntpath
import os
import pathlib
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable

from bot.instance_layout import DEFAULT_INSTANCE_NAME, validate_instance_name
from bot.platform_paths import (
    default_config_root,
    default_data_root,
    default_env_file,
    default_launch_agent_dir,
    default_systemd_user_dir,
    default_user_bash_completion_dir,
    default_user_bin_dir,
    default_user_powershell_completion_path,
    default_user_powershell_profile_path,
    default_user_zsh_completion_path,
    default_user_zsh_rc_path,
    is_linux,
    is_macos,
    is_windows,
)

_LEGACY_APP_NAME = "feishu-codex"
_LEGACY_ENV_FILE_NAME = "feishu-codex.env"
_FOCUS_ENV_FILE_NAME = "focus.env"
_LEGACY_WRAPPER_NAMES = ("feishu-codex", "feishu-codexctl", "feishu-codexd")
_LEGACY_COMPLETION_COMMAND_NAMES = _LEGACY_WRAPPER_NAMES
_LEGACY_ZSH_PROFILE_BLOCK_START = "# >>> feishu-codex zsh completion >>>"
_LEGACY_ZSH_PROFILE_BLOCK_END = "# <<< feishu-codex zsh completion <<<"
_LEGACY_POWERSHELL_PROFILE_BLOCK_START = "# >>> feishu-codex PowerShell completion >>>"
_LEGACY_POWERSHELL_PROFILE_BLOCK_END = "# <<< feishu-codex PowerShell completion <<<"
_LEGACY_SCHEDULED_UNIT_PREFIX = "feishu-codex-scheduled"
_FOCUS_SCHEDULED_UNIT_PREFIX = "focus-scheduled"
_MIGRATION_BACKUP_ROOT_NAME = "migration-backups"
_WINDOWS_USER_PATH_METADATA_FILE = "windows-user-path.json"

_CONFIG_SKIP_DIR_NAMES = {"shell-completion", "install-state", "__pycache__"}
_CONFIG_SKIP_FILE_NAMES = {"system.yaml.example", "codex.yaml.example"}
_DATA_SKIP_DIR_NAMES = {".venv", "scheduled-tasks", "__pycache__"}
_DATA_SKIP_FILE_NAMES = {
    "app_server_runtime.json",
    "app_server_websocket.token",
    "codex-app-server-start.lock",
    "instance_registry.json",
    "instance_registry.lock",
    "interaction_leases.json",
    "interaction_leases.lock",
    "service-instance.json",
    "service-instance.lock",
    "service-launch.cmd",
    "service-task.xml",
    "service.plist",
    "thread_runtime_leases.json",
    "thread_runtime_leases.lock",
}
_ALLOWED_EXISTING_CONFIG_ROOT_NAMES = {
    "codex.yaml",
    "codex.yaml.example",
    "focus.env",
    "init.token",
    "install-state",
    "shell-completion",
    "system.yaml",
    "system.yaml.example",
}
_ALLOWED_EXISTING_DATA_ROOT_NAMES = {
    ".venv",
    _MIGRATION_BACKUP_ROOT_NAME,
    "service.stdout.log",
    "service.stderr.log",
}


class LegacyMigrationError(RuntimeError):
    """Raised when a migration stage cannot safely continue."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


@dataclass(slots=True)
class LegacyMigrationSummary:
    instances: list[str] = field(default_factory=list)
    config_files: int = 0
    data_files: int = 0
    scheduled_tasks: int = 0
    removed_wrappers: int = 0
    warnings: list[str] = field(default_factory=list)
    backup_dir: pathlib.Path | None = None


def migrate_from_feishu_codex(
    *,
    install_new_surface: Callable[[], int] | None = None,
) -> LegacyMigrationSummary:
    migrator = _LegacyFeishuCodexMigrator(install_new_surface=install_new_surface)
    return migrator.run()


class _LegacyFeishuCodexMigrator:
    def __init__(self, *, install_new_surface: Callable[[], int] | None = None) -> None:
        self._install_new_surface = install_new_surface
        self._legacy_config_root = _legacy_config_root()
        self._legacy_data_root = _legacy_data_root()
        self._legacy_env_file = _legacy_env_file(self._legacy_config_root)
        self._legacy_scheduled_task_root = _legacy_scheduled_task_root()
        self._target_config_root = default_config_root()
        self._target_data_root = default_data_root()
        self._target_env_file = default_env_file()
        self._backup_dir: pathlib.Path | None = None
        self._summary = LegacyMigrationSummary()

    def run(self) -> LegacyMigrationSummary:
        self._summary.instances = self._discover_legacy_instances()
        self._run_stage("preflight", self._preflight)
        self._run_stage("stop-legacy-service", self._stop_legacy_services)
        self._run_stage("transfer-local-state", self._transfer_local_state)
        self._run_stage("install-focus-surface", self._install_focus_surface)
        self._run_stage("transfer-scheduled-timers", self._transfer_scheduled_timers)
        self._run_stage("cleanup-legacy-install-surface", self._cleanup_legacy_install_surface)
        self._run_stage("archive-legacy-roots", self._archive_legacy_roots)
        self._summary.backup_dir = self._backup_dir
        return self._summary

    def _run_stage(self, stage: str, operation: Callable[[], None]) -> None:
        try:
            operation()
        except LegacyMigrationError:
            raise
        except Exception as exc:  # pragma: no cover - exercised through callers.
            message = str(exc).strip() or exc.__class__.__name__
            raise LegacyMigrationError(stage, message) from exc

    def _preflight(self) -> None:
        if _same_path(self._legacy_env_file, self._target_env_file):
            raise LegacyMigrationError("preflight", "旧 env 文件与目标 FOCUS env 文件不能是同一个路径。")
        self._ensure_target_output_paths_outside_legacy_roots()
        if not self._has_legacy_source():
            raise LegacyMigrationError(
                "preflight",
                "未找到旧 feishu-codex 配置、数据、scheduled tasks、wrapper 或 env 文件；迁移已停止。",
            )
        self._ensure_target_surface_is_safe()
        self._backup_dir = _unique_backup_dir(self._target_data_root)
        self._backup_dir.mkdir(parents=True, exist_ok=False)

    def _has_legacy_source(self) -> bool:
        if self._legacy_config_root.exists() or self._legacy_data_root.exists():
            return True
        if self._legacy_env_file.exists() or self._legacy_scheduled_task_root.exists():
            return True
        for bin_dir in _dedupe_paths(default_user_bin_dir(), _legacy_user_bin_dir()):
            for name in _LEGACY_WRAPPER_NAMES:
                path = bin_dir / (f"{name}.cmd" if is_windows() else name)
                if path.exists():
                    return True
        return False

    def _ensure_target_surface_is_safe(self) -> None:
        conflicts: list[pathlib.Path] = []
        if self._target_config_root.exists():
            for child in self._target_config_root.iterdir():
                if child.name == "instances":
                    if any(child.iterdir()):
                        conflicts.append(child)
                    continue
                if child.name not in _ALLOWED_EXISTING_CONFIG_ROOT_NAMES:
                    conflicts.append(child)
        if self._target_data_root.exists():
            for child in self._target_data_root.iterdir():
                if child.name in _ALLOWED_EXISTING_DATA_ROOT_NAMES:
                    continue
                if child.name == "_global" and _dir_contains_only_runtime_files(child):
                    continue
                if child.suffix == ".log":
                    continue
                conflicts.append(child)
        if conflicts:
            rendered = "\n".join(f"- {path}" for path in conflicts[:10])
            raise LegacyMigrationError(
                "preflight",
                "目标 focus 目录已包含非安装生成的数据；为避免覆盖真实新数据，迁移已停止：\n"
                f"{rendered}",
            )

    def _ensure_target_output_paths_outside_legacy_roots(self) -> None:
        legacy_roots = (
            ("旧 config root", self._legacy_config_root),
            ("旧 data root", self._legacy_data_root),
            ("旧 scheduled task root", self._legacy_scheduled_task_root),
        )
        conflicts: list[tuple[str, pathlib.Path, str, pathlib.Path]] = []
        for target_label, target_path in _target_output_paths(
            target_config_root=self._target_config_root,
            target_data_root=self._target_data_root,
            target_env_file=self._target_env_file,
        ):
            for root_label, legacy_root in legacy_roots:
                if _paths_overlap(target_path, legacy_root):
                    conflicts.append((target_label, target_path, root_label, legacy_root))
                    break
        if not conflicts:
            return
        rendered = "\n".join(
            f"- {target_label}: {target_path} overlaps {root_label}: {legacy_root}"
            for target_label, target_path, root_label, legacy_root in conflicts[:10]
        )
        raise LegacyMigrationError(
            "preflight",
            "FOCUS 目标输出路径不能与旧 feishu-codex root 重叠；迁移已停止：\n"
            f"{rendered}",
        )

    def _discover_legacy_instances(self) -> list[str]:
        names = {DEFAULT_INSTANCE_NAME}
        for root in (self._legacy_config_root / "instances", self._legacy_data_root / "instances"):
            if not root.exists():
                continue
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                try:
                    names.add(validate_instance_name(child.name))
                except ValueError:
                    continue
        return sorted(names)

    def _stop_legacy_services(self) -> None:
        if is_linux():
            _stop_disable_legacy_systemd_units(self._summary.instances, remove_files=False)
            return
        if is_macos():
            _stop_disable_legacy_launchd_units(self._summary.instances, remove_files=False)
            return
        if is_windows():
            _stop_disable_legacy_windows_tasks(self._summary.instances, remove_files=False)

    def _transfer_local_state(self) -> None:
        backup_dir = self._require_backup_dir()
        self._summary.config_files = self._transfer_tree(
            source_root=self._legacy_config_root,
            target_root=self._target_config_root,
            backup_existing_root=backup_dir / "preexisting-focus-config",
            kind="config",
        )
        self._summary.config_files += self._transfer_explicit_legacy_env_file()
        self._summary.data_files = self._transfer_tree(
            source_root=self._legacy_data_root,
            target_root=self._target_data_root,
            backup_existing_root=backup_dir / "preexisting-focus-data",
            kind="data",
        )

    def _transfer_explicit_legacy_env_file(self) -> int:
        source_path = self._legacy_env_file
        if not source_path.exists():
            return 0
        default_legacy_env = self._legacy_config_root / _LEGACY_ENV_FILE_NAME
        default_target_env = self._target_config_root / _FOCUS_ENV_FILE_NAME
        if source_path == default_legacy_env and self._target_env_file == default_target_env:
            return 0
        self._copy_transfer_file(
            source_path,
            self._target_env_file,
            backup_existing_path=self._require_backup_dir() / "preexisting-focus-config" / _FOCUS_ENV_FILE_NAME,
            allow_replace_existing=True,
        )
        return 1

    def _transfer_tree(
        self,
        *,
        source_root: pathlib.Path,
        target_root: pathlib.Path,
        backup_existing_root: pathlib.Path,
        kind: str,
    ) -> int:
        if not source_root.exists():
            return 0
        transferred = 0
        for source_path, relative_path in _iter_transfer_files(source_root, kind=kind):
            if (
                kind == "config"
                and relative_path.name != _LEGACY_ENV_FILE_NAME
                and _same_path(source_path, self._legacy_env_file)
            ):
                continue
            target_relative_path = _target_relative_path(relative_path, kind=kind)
            if target_relative_path is None:
                continue
            target_path = target_root / target_relative_path
            self._copy_transfer_file(
                source_path,
                target_path,
                backup_existing_path=backup_existing_root / target_relative_path,
                allow_replace_existing=(kind == "config"),
            )
            transferred += 1
        return transferred

    @staticmethod
    def _copy_transfer_file(
        source_path: pathlib.Path,
        target_path: pathlib.Path,
        *,
        backup_existing_path: pathlib.Path,
        allow_replace_existing: bool,
    ) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            if target_path.is_file() and filecmp.cmp(source_path, target_path, shallow=False):
                return
            if not allow_replace_existing:
                raise LegacyMigrationError(
                    "transfer-local-state",
                    f"目标文件已存在且不是可覆盖安装面：{target_path}",
                )
            backup_existing_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target_path), str(backup_existing_path))
        shutil.copy2(source_path, target_path)

    def _install_focus_surface(self) -> None:
        if self._install_new_surface is None:
            return
        result = int(self._install_new_surface())
        if result != 0:
            raise LegacyMigrationError("install-focus-surface", f"新 FOCUS 安装面刷新失败：exit {result}")

    def _transfer_scheduled_timers(self) -> None:
        if not is_linux():
            return
        old_root = self._legacy_scheduled_task_root
        if not old_root.exists():
            return
        try:
            scheduled = _scheduled_prompt_module()
        except Exception as exc:
            raise LegacyMigrationError("transfer-scheduled-timers", f"无法加载 scheduled prompt helper：{exc}") from exc
        focusctl_path = default_user_bin_dir() / ("focusctl.cmd" if is_windows() else "focusctl")
        for task_dir in sorted(old_root.iterdir()):
            if not task_dir.is_dir():
                continue
            raw = _read_json_file(task_dir / "task.json")
            task_id = str(raw.get("task_id") or task_dir.name).strip()
            if not task_id:
                continue
            prompt_file = pathlib.Path(str(raw.get("prompt_file") or task_dir / "prompt.txt")).expanduser()
            if not prompt_file.exists():
                prompt_file = task_dir / "prompt.txt"
            prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
            prompt_text, prompt_warnings = _migrate_scheduled_prompt_text(prompt_text, task_id=task_id)
            self._summary.warnings.extend(prompt_warnings)
            spec = scheduled.ScheduledTaskSpec(
                task_id=task_id,
                instance=str(raw.get("instance") or DEFAULT_INSTANCE_NAME).strip() or DEFAULT_INSTANCE_NAME,
                binding_id=str(raw.get("binding_id") or "").strip(),
                on_calendar=str(raw.get("on_calendar") or "").strip(),
                description=str(raw.get("description") or "").strip(),
                prompt_file="",
                ctl_path=str(focusctl_path),
                synthetic_source=str(raw.get("synthetic_source") or "schedule").strip() or "schedule",
                display_mode=str(raw.get("display_mode") or "silent").strip() or "silent",
                created_at=str(raw.get("created_at") or "").strip(),
            )
            existed = scheduled.timer_unit_path(task_id).exists()
            scheduled.save_spec(spec, prompt_text=prompt_text)
            _run_systemctl("daemon-reload")
            _run_systemctl("enable", f"{_FOCUS_SCHEDULED_UNIT_PREFIX}-{task_id}.timer")
            _run_systemctl("restart" if existed else "start", f"{_FOCUS_SCHEDULED_UNIT_PREFIX}-{task_id}.timer")
            _remove_legacy_scheduled_timer(task_id)
            self._summary.scheduled_tasks += 1

    def _cleanup_legacy_install_surface(self) -> None:
        self._summary.removed_wrappers = _remove_legacy_wrappers()
        _remove_legacy_completion_files()
        _remove_legacy_windows_user_path()
        if is_linux():
            _stop_disable_legacy_systemd_units(self._summary.instances, remove_files=True)
            return
        if is_macos():
            _stop_disable_legacy_launchd_units(self._summary.instances, remove_files=True)
            return
        if is_windows():
            _stop_disable_legacy_windows_tasks(self._summary.instances, remove_files=True)

    def _archive_legacy_roots(self) -> None:
        backup_dir = self._require_backup_dir()
        legacy_backup_dir = backup_dir / "legacy"
        for label, root in (("config", self._legacy_config_root), ("data", self._legacy_data_root)):
            if not root.exists():
                continue
            destination = legacy_backup_dir / label
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root), str(destination))
            _remove_empty_parent(root.parent, stop_at=_legacy_cleanup_stop(root))
        if self._legacy_env_file.exists() and not _is_relative_to(self._legacy_env_file, self._legacy_config_root):
            destination = legacy_backup_dir / "env" / self._legacy_env_file.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self._legacy_env_file), str(destination))
            _remove_empty_parent(self._legacy_env_file.parent, stop_at=self._legacy_env_file.parent.parent)
        if self._legacy_scheduled_task_root.exists() and not _is_relative_to(
            self._legacy_scheduled_task_root,
            self._legacy_data_root,
        ):
            destination = legacy_backup_dir / "scheduled-tasks"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(self._legacy_scheduled_task_root), str(destination))
            _remove_empty_parent(
                self._legacy_scheduled_task_root.parent,
                stop_at=self._legacy_scheduled_task_root.parent.parent,
            )

    def _require_backup_dir(self) -> pathlib.Path:
        if self._backup_dir is None:
            raise LegacyMigrationError("preflight", "迁移备份目录尚未初始化。")
        return self._backup_dir


def _legacy_config_root() -> pathlib.Path:
    raw = os.environ.get("FC_CONFIG_ROOT", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    home = pathlib.Path.home()
    if is_windows():
        appdata = pathlib.Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        return appdata / _LEGACY_APP_NAME / "config"
    if is_macos():
        return home / "Library" / "Application Support" / _LEGACY_APP_NAME / "config"
    return home / ".config" / _LEGACY_APP_NAME


def _legacy_data_root() -> pathlib.Path:
    raw = os.environ.get("FC_DATA_ROOT", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    home = pathlib.Path.home()
    if is_windows():
        local_appdata = pathlib.Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return local_appdata / _LEGACY_APP_NAME / "data"
    if is_macos():
        return home / "Library" / "Application Support" / _LEGACY_APP_NAME / "data"
    return home / ".local" / "share" / _LEGACY_APP_NAME


def _legacy_user_bin_dir() -> pathlib.Path:
    raw = os.environ.get("FC_BIN_DIR", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    home = pathlib.Path.home()
    if is_windows():
        local_appdata = pathlib.Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return local_appdata / _LEGACY_APP_NAME / "bin"
    return home / ".local" / "bin"


def _legacy_env_file(config_root: pathlib.Path | None = None) -> pathlib.Path:
    raw = os.environ.get("FC_ENV_FILE", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    return (config_root or _legacy_config_root()) / _LEGACY_ENV_FILE_NAME


def _legacy_user_bash_completion_dir() -> pathlib.Path | None:
    raw = os.environ.get("FC_BASH_COMPLETION_DIR", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    if is_windows():
        return None
    raw_user_dir = os.environ.get("BASH_COMPLETION_USER_DIR", "").strip()
    if raw_user_dir:
        return pathlib.Path(raw_user_dir).expanduser() / "completions"
    return pathlib.Path.home() / ".local" / "share" / "bash-completion" / "completions"


def _legacy_user_zsh_completion_path(config_root: pathlib.Path | None = None) -> pathlib.Path | None:
    raw = os.environ.get("FC_ZSH_COMPLETION_PATH", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    if is_windows():
        return None
    return (config_root or _legacy_config_root()) / "shell-completion" / "feishu-codex.zsh"


def _legacy_user_zsh_rc_path() -> pathlib.Path | None:
    raw = os.environ.get("FC_ZSH_RC_PATH", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    if is_windows():
        return None
    return pathlib.Path.home() / ".zshrc"


def _legacy_user_powershell_profile_path() -> pathlib.Path | None:
    raw = os.environ.get("FC_POWERSHELL_PROFILE_PATH", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    if not is_windows():
        return None
    return pathlib.Path.home() / "Documents" / "PowerShell" / "profile.ps1"


def _legacy_user_powershell_completion_path(config_root: pathlib.Path | None = None) -> pathlib.Path | None:
    raw = os.environ.get("FC_POWERSHELL_COMPLETION_PATH", "").strip()
    if raw:
        return pathlib.Path(raw).expanduser()
    if _legacy_user_powershell_profile_path() is None:
        return None
    return (config_root or _legacy_config_root()) / "shell-completion" / "feishu-codex.ps1"


def _legacy_scheduled_task_root() -> pathlib.Path:
    raw_xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip()
    if raw_xdg_data_home:
        xdg_data_home = pathlib.Path(raw_xdg_data_home).expanduser()
    else:
        xdg_data_home = pathlib.Path.home() / ".local" / "share"
    return xdg_data_home / _LEGACY_APP_NAME / "scheduled-tasks"


def _target_output_paths(
    *,
    target_config_root: pathlib.Path,
    target_data_root: pathlib.Path,
    target_env_file: pathlib.Path,
) -> tuple[tuple[str, pathlib.Path], ...]:
    return tuple(
        (label, path)
        for label, path in (
            ("FOCUS config root", target_config_root),
            ("FOCUS data root", target_data_root),
            ("FOCUS env file", target_env_file),
            ("FOCUS bin dir", default_user_bin_dir()),
            ("FOCUS bash completion dir", default_user_bash_completion_dir()),
            ("FOCUS zsh completion path", default_user_zsh_completion_path()),
            ("FOCUS zsh rc path", default_user_zsh_rc_path()),
            ("FOCUS PowerShell completion path", default_user_powershell_completion_path()),
            ("FOCUS PowerShell profile path", default_user_powershell_profile_path()),
            ("FOCUS systemd user dir", default_systemd_user_dir() if is_linux() else None),
            ("FOCUS LaunchAgent dir", default_launch_agent_dir() if is_macos() else None),
        )
        if path is not None
    )


def _legacy_windows_user_path_metadata_path() -> pathlib.Path:
    return _legacy_config_root() / "install-state" / _WINDOWS_USER_PATH_METADATA_FILE


def _unique_backup_dir(data_root: pathlib.Path) -> pathlib.Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = data_root / _MIGRATION_BACKUP_ROOT_NAME / f"feishu-codex-{timestamp}"
    candidate = base
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = pathlib.Path(f"{base}-{counter}")
    return candidate


def _paths_overlap(left: pathlib.Path, right: pathlib.Path) -> bool:
    normalized_left = pathlib.Path(left).resolve()
    normalized_right = pathlib.Path(right).resolve()
    return (
        normalized_left == normalized_right
        or normalized_left in normalized_right.parents
        or normalized_right in normalized_left.parents
    )


def _same_path(left: pathlib.Path, right: pathlib.Path) -> bool:
    return pathlib.Path(left).resolve() == pathlib.Path(right).resolve()


def _is_relative_to(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        pathlib.Path(path).relative_to(root)
    except ValueError:
        return False
    return True


def _legacy_cleanup_stop(root: pathlib.Path) -> pathlib.Path:
    parent = pathlib.Path(root).parent
    if parent.name == _LEGACY_APP_NAME:
        return parent.parent
    return parent


def _dir_contains_only_runtime_files(path: pathlib.Path) -> bool:
    for child in path.rglob("*"):
        if child.is_dir():
            continue
        if child.name not in _DATA_SKIP_FILE_NAMES and child.suffix != ".log":
            return False
    return True


def _iter_transfer_files(source_root: pathlib.Path, *, kind: str) -> Iterable[tuple[pathlib.Path, pathlib.Path]]:
    skip_dir_names = _CONFIG_SKIP_DIR_NAMES if kind == "config" else _DATA_SKIP_DIR_NAMES
    for current_dir, dirnames, filenames in os.walk(source_root):
        current_path = pathlib.Path(current_dir)
        relative_dir = current_path.relative_to(source_root)
        dirnames[:] = [name for name in dirnames if name not in skip_dir_names]
        for filename in filenames:
            relative_path = relative_dir / filename
            if _skip_transfer_file(relative_path, kind=kind):
                continue
            yield current_path / filename, relative_path


def _skip_transfer_file(relative_path: pathlib.Path, *, kind: str) -> bool:
    name = relative_path.name
    if kind == "config":
        return name in _CONFIG_SKIP_FILE_NAMES
    if name in _DATA_SKIP_FILE_NAMES:
        return True
    if name.endswith(".tmp") or name.endswith(".lock") or pathlib.Path(name).suffix == ".log":
        return True
    return False


def _target_relative_path(relative_path: pathlib.Path, *, kind: str) -> pathlib.Path | None:
    if kind == "config" and relative_path.name == _LEGACY_ENV_FILE_NAME:
        return relative_path.with_name(_FOCUS_ENV_FILE_NAME)
    return relative_path


def _read_json_file(path: pathlib.Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _migrate_scheduled_prompt_text(prompt_text: str, *, task_id: str) -> tuple[str, list[str]]:
    migrated = str(prompt_text or "")
    replacements = (
        ("feishu-codexctl", "focusctl"),
        ("feishu-codex-scheduled-", "focus-scheduled-"),
        ("~/.local/share/feishu-codex", "~/.local/share/focus"),
        ("~/.config/feishu-codex", "~/.config/focus"),
        ("feishu-codex.env", "focus.env"),
    )
    for old, new in replacements:
        migrated = migrated.replace(old, new)

    warnings: list[str] = []
    if "manage_scheduled_prompt.py" in migrated:
        warnings.append(
            f"scheduled task {task_id}: prompt contains a concrete manage_scheduled_prompt.py helper path; "
            "please verify the self-removal command after migration."
        )
    old_markers = (
        "/feishu-codex/",
        "\\feishu-codex\\",
        "FC_CONFIG_ROOT",
        "FC_DATA_ROOT",
        "FC_BIN_DIR",
        "FC_ENV_FILE",
    )
    if any(marker in migrated for marker in old_markers):
        warnings.append(
            f"scheduled task {task_id}: prompt still contains old feishu-codex path/env markers after safe rewrites."
        )
    return migrated, warnings


def _scheduled_prompt_module():
    from bot.managed_skills.feishu_scheduled_prompts.skill.scripts import manage_scheduled_prompt

    return manage_scheduled_prompt


def _run_systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if shutil.which("systemctl") is None:
        if check:
            raise LegacyMigrationError("systemd", "systemctl 不可用。")
        return subprocess.CompletedProcess(["systemctl", "--user", *args], 127, "", "systemctl unavailable")
    return subprocess.run(["systemctl", "--user", *args], check=check, text=True, capture_output=True)


def _stop_disable_legacy_systemd_units(instance_names: list[str], *, remove_files: bool) -> None:
    if shutil.which("systemctl") is None:
        return
    unit_names = {"feishu-codex"}
    for instance_name in instance_names:
        if instance_name == DEFAULT_INSTANCE_NAME:
            continue
        unit_names.add(f"feishu-codex@{instance_name}")
        unit_names.add(f"feishu-codex-{instance_name}")
    for unit_name in sorted(unit_names):
        _run_systemctl("disable", unit_name, check=False)
        _run_systemctl("stop", unit_name, check=False)
    if remove_files:
        systemd_dir = default_systemd_user_dir()
        paths = [systemd_dir / "feishu-codex.service", systemd_dir / "feishu-codex@.service"]
        for instance_name in instance_names:
            if instance_name == DEFAULT_INSTANCE_NAME:
                continue
            paths.append(systemd_dir / f"feishu-codex@{instance_name}.service")
            paths.append(systemd_dir / f"feishu-codex-{instance_name}.service")
        paths.extend(systemd_dir.glob("feishu-codex*.service"))
        for path in paths:
            _unlink_if_exists(path)
        _run_systemctl("daemon-reload", check=False)


def _stop_disable_legacy_launchd_units(instance_names: list[str], *, remove_files: bool) -> None:
    if shutil.which("launchctl") is None:
        return
    domain = f"gui/{os.getuid()}"
    launch_agent_dir = default_launch_agent_dir()
    for instance_name in instance_names:
        label = f"io.feishu-codex.{instance_name}"
        subprocess.run(["launchctl", "bootout", domain, label], check=False, text=True, capture_output=True)
        if remove_files:
            _unlink_if_exists(launch_agent_dir / f"{label}.plist")


def _stop_disable_legacy_windows_tasks(instance_names: list[str], *, remove_files: bool) -> None:
    if shutil.which("schtasks") is None:
        return
    task_names = ["feishu-codex" if name == DEFAULT_INSTANCE_NAME else f"feishu-codex-{name}" for name in instance_names]
    for task_name in task_names:
        subprocess.run(["schtasks", "/End", "/TN", task_name], check=False, text=True, capture_output=True)
        if remove_files:
            subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"], check=False, text=True, capture_output=True)


def _remove_legacy_scheduled_timer(task_id: str) -> None:
    unit_name = f"{_LEGACY_SCHEDULED_UNIT_PREFIX}-{task_id}"
    _run_systemctl("disable", "--now", f"{unit_name}.timer", check=False)
    _run_systemctl("reset-failed", f"{unit_name}.timer", f"{unit_name}.service", check=False)
    systemd_dir = default_systemd_user_dir()
    _unlink_if_exists(systemd_dir / f"{unit_name}.timer")
    _unlink_if_exists(systemd_dir / f"{unit_name}.service")
    _run_systemctl("daemon-reload", check=False)


def _remove_legacy_wrappers() -> int:
    removed = 0
    for bin_dir in _dedupe_paths(default_user_bin_dir(), _legacy_user_bin_dir()):
        for name in _LEGACY_WRAPPER_NAMES:
            candidates = [bin_dir / f"{name}.cmd"] if is_windows() else [bin_dir / name]
            for path in candidates:
                if _unlink_if_exists(path):
                    removed += 1
    return removed


def _remove_legacy_windows_user_path() -> None:
    if not is_windows():
        return
    metadata_path = _legacy_windows_user_path_metadata_path()
    try:
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except Exception:
        raw = {}
    try:
        if isinstance(raw, dict) and raw.get("added_to_user_path"):
            bin_dir_raw = str(raw.get("bin_dir", "") or "").strip()
            if bin_dir_raw:
                raw_user_path, value_type = _read_windows_user_path_value()
                updated_user_path, removed = _remove_windows_path_entry(raw_user_path, pathlib.Path(bin_dir_raw))
                if removed:
                    _write_windows_user_path_value(updated_user_path, value_type=value_type)
    finally:
        _unlink_if_exists(metadata_path)


def _normalize_windows_path_entry(value: pathlib.Path | str) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    return ntpath.normcase(ntpath.normpath(text))


def _split_windows_path_entries(raw_path: str) -> list[str]:
    return [entry.strip() for entry in str(raw_path or "").split(";") if entry.strip()]


def _remove_windows_path_entry(raw_path: str, entry: pathlib.Path | str) -> tuple[str, bool]:
    entries = _split_windows_path_entries(raw_path)
    target = _normalize_windows_path_entry(entry)
    if not target:
        return ";".join(entries), False
    kept_entries: list[str] = []
    removed = False
    for item in entries:
        if not removed and _normalize_windows_path_entry(item) == target:
            removed = True
            continue
        kept_entries.append(item)
    return ";".join(kept_entries), removed


def _read_windows_user_path_value() -> tuple[str, int | None]:
    if not is_windows():
        return "", None
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        try:
            value, value_type = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ
    return str(value or ""), int(value_type)


def _notify_windows_environment_changed() -> None:
    if not is_windows():
        return
    try:
        import ctypes

        hwnd_broadcast = 0xFFFF
        wm_setting_change = 0x001A
        smto_abort_if_hung = 0x0002
        result = ctypes.c_void_p()
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_setting_change,
            0,
            "Environment",
            smto_abort_if_hung,
            5000,
            ctypes.byref(result),
        )
    except Exception:
        return


def _write_windows_user_path_value(raw_path: str, *, value_type: int | None) -> None:
    if not is_windows():
        return
    import winreg

    normalized_type = value_type if value_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else winreg.REG_EXPAND_SZ
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
        if raw_path:
            winreg.SetValueEx(key, "Path", 0, normalized_type, str(raw_path))
        else:
            try:
                winreg.DeleteValue(key, "Path")
            except FileNotFoundError:
                pass
    _notify_windows_environment_changed()


def _remove_legacy_completion_files() -> None:
    legacy_config = _legacy_config_root()
    bash_dir = _legacy_user_bash_completion_dir()
    if bash_dir is not None:
        for command_name in _LEGACY_COMPLETION_COMMAND_NAMES:
            _unlink_if_exists(bash_dir / command_name)
    zsh_rc = _legacy_user_zsh_rc_path()
    if zsh_rc is not None:
        _remove_managed_block(
            zsh_rc,
            start_marker=_LEGACY_ZSH_PROFILE_BLOCK_START,
            end_marker=_LEGACY_ZSH_PROFILE_BLOCK_END,
        )
    powershell_profile = _legacy_user_powershell_profile_path()
    if powershell_profile is not None:
        _remove_managed_block(
            powershell_profile,
            start_marker=_LEGACY_POWERSHELL_PROFILE_BLOCK_START,
            end_marker=_LEGACY_POWERSHELL_PROFILE_BLOCK_END,
        )
    zsh_completion = _legacy_user_zsh_completion_path(legacy_config)
    if zsh_completion is not None:
        _unlink_if_exists(zsh_completion)
    powershell_completion = _legacy_user_powershell_completion_path(legacy_config)
    if powershell_completion is not None:
        _unlink_if_exists(powershell_completion)


def _remove_managed_block(path: pathlib.Path, *, start_marker: str, end_marker: str) -> None:
    if not path.exists():
        return
    existing = path.read_text(encoding="utf-8")
    rendered = _strip_managed_block(existing, start_marker=start_marker, end_marker=end_marker).strip()
    if not rendered:
        path.unlink()
        return
    path.write_text(f"{rendered}\n", encoding="utf-8")


def _strip_managed_block(text: str, *, start_marker: str, end_marker: str) -> str:
    rendered = str(text or "")
    while True:
        start = rendered.find(start_marker)
        if start < 0:
            return rendered
        end = rendered.find(end_marker, start)
        if end < 0:
            return rendered
        end += len(end_marker)
        if end < len(rendered) and rendered[end] == "\n":
            end += 1
        rendered = rendered[:start] + rendered[end:]


def _dedupe_paths(*paths: pathlib.Path | None) -> tuple[pathlib.Path, ...]:
    rendered: list[pathlib.Path] = []
    seen: set[str] = set()
    for path in paths:
        if path is None:
            continue
        normalized = pathlib.Path(path)
        key = str(normalized)
        if key in seen:
            continue
        seen.add(key)
        rendered.append(normalized)
    return tuple(rendered)


def _unlink_if_exists(path: pathlib.Path) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except IsADirectoryError:
        shutil.rmtree(path)
        return True


def _remove_empty_parent(path: pathlib.Path, *, stop_at: pathlib.Path) -> None:
    current = pathlib.Path(path)
    stop = pathlib.Path(stop_at)
    while current != stop and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
