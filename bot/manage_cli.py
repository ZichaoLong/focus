"""
Cross-platform management CLI for local feishu-codex installation.
"""

from __future__ import annotations

import argparse
import filecmp
import importlib
import json
import ntpath
import os
import pathlib
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

from bot.env_file import ensure_env_template
from bot.file_permissions import ensure_private_file_permissions
from bot.codex_command_resolver import detect_stable_codex_command
from bot.instance_layout import (
    DEFAULT_INSTANCE_NAME,
    apply_instance_environment,
    list_known_instance_names,
    require_instance_exists,
    resolve_instance_paths,
    validate_instance_name,
)
from bot.install_templates import CODEX_YAML_TEMPLATE, SYSTEM_YAML_TEMPLATE, render_initial_codex_yaml
from bot.instance_resolution import list_running_instances
from bot.platform_paths import (
    default_config_root,
    default_data_root,
    default_log_file,
    default_user_bin_dir,
    is_windows,
)
from bot.shell_completion import CompletionInstallResult, install_shell_completion_files, remove_shell_completion_files
from bot.service_manager import ServiceManagerError, build_service_definition, current_service_manager
from bot.stores.service_instance_lease import ServiceInstanceLease


class _HelpFormatter(argparse.RawTextHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        if "argument command: invalid choice: 'install'" in message:
            self.exit(
                2,
                (
                    f"{self.prog}: error: 公开命令中已无 `install`；"
                    "首次安装或修复请从仓库根目录运行 `bash install.sh`"
                    " 或 `./install.ps1`。\n"
                ),
            )
        sanitized = message.replace("bootstrap-install, ", "").replace(", bootstrap-install", "")
        super().error(sanitized)


_MANAGED_SKILL_MARKER = ".feishu-codex-managed"
_WINDOWS_USER_PATH_METADATA_FILE = "windows-user-path.json"


@dataclass(frozen=True, slots=True)
class _ManagedSkillSpec:
    name: str
    package: str


_MANAGED_SKILLS: tuple[_ManagedSkillSpec, ...] = (
    _ManagedSkillSpec(name="feishu-send-image", package="bot.managed_skills.feishu_send_image"),
    _ManagedSkillSpec(name="feishu-scheduled-prompts", package="bot.managed_skills.feishu_scheduled_prompts"),
)
_DEFAULT_MANAGED_SKILL_NAME = _MANAGED_SKILLS[0].name


def _windows_user_path_metadata_path() -> pathlib.Path:
    return default_config_root() / "install-state" / _WINDOWS_USER_PATH_METADATA_FILE


def _read_windows_user_path_metadata() -> tuple[pathlib.Path | None, bool]:
    path = _windows_user_path_metadata_path()
    if not path.exists():
        return None, False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, False
    if not isinstance(raw, dict):
        return None, False
    bin_dir_raw = str(raw.get("bin_dir", "") or "").strip()
    bin_dir = pathlib.Path(bin_dir_raw).expanduser() if bin_dir_raw else None
    return bin_dir, bool(raw.get("added_to_user_path", False))


def _write_windows_user_path_metadata(*, bin_dir: pathlib.Path, added_to_user_path: bool) -> None:
    path = _windows_user_path_metadata_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "bin_dir": str(pathlib.Path(bin_dir)),
                "added_to_user_path": bool(added_to_user_path),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _remove_windows_user_path_metadata() -> None:
    path = _windows_user_path_metadata_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _normalize_windows_path_entry(value: pathlib.Path | str) -> str:
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    return ntpath.normcase(ntpath.normpath(text))


def _split_windows_path_entries(raw_path: str) -> list[str]:
    return [entry.strip() for entry in str(raw_path or "").split(";") if entry.strip()]


def _windows_path_contains_entry(entries: list[str], entry: pathlib.Path | str) -> bool:
    target = _normalize_windows_path_entry(entry)
    if not target:
        return False
    return any(_normalize_windows_path_entry(item) == target for item in entries)


def _append_windows_path_entry(raw_path: str, entry: pathlib.Path | str) -> tuple[str, bool]:
    entries = _split_windows_path_entries(raw_path)
    rendered_entry = str(pathlib.Path(entry))
    if _windows_path_contains_entry(entries, rendered_entry):
        return ";".join(entries), False
    entries.append(rendered_entry)
    return ";".join(entries), True


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

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_void_p()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
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


def _ensure_windows_user_path(bin_dir: pathlib.Path) -> None:
    if not is_windows():
        return
    recorded_bin_dir, recorded_added = _read_windows_user_path_metadata()
    same_recorded_bin = (
        recorded_bin_dir is not None
        and _normalize_windows_path_entry(recorded_bin_dir) == _normalize_windows_path_entry(bin_dir)
    )
    raw_user_path, value_type = _read_windows_user_path_value()
    updated_user_path = raw_user_path
    changed = False
    if recorded_added and recorded_bin_dir is not None and not same_recorded_bin:
        updated_user_path, removed = _remove_windows_path_entry(updated_user_path, recorded_bin_dir)
        changed = changed or removed
    updated_user_path, added = _append_windows_path_entry(updated_user_path, bin_dir)
    changed = changed or added
    if changed:
        _write_windows_user_path_value(updated_user_path, value_type=value_type)
    _write_windows_user_path_metadata(
        bin_dir=bin_dir,
        added_to_user_path=bool(added or (recorded_added and same_recorded_bin)),
    )


def _remove_windows_user_path() -> None:
    if not is_windows():
        return
    recorded_bin_dir, recorded_added = _read_windows_user_path_metadata()
    try:
        if recorded_added and recorded_bin_dir is not None:
            raw_user_path, value_type = _read_windows_user_path_value()
            updated_user_path, removed = _remove_windows_path_entry(raw_user_path, recorded_bin_dir)
            if removed:
                _write_windows_user_path_value(updated_user_path, value_type=value_type)
    finally:
        _remove_windows_user_path_metadata()


def _hide_subcommand_from_help(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser], name: str
) -> None:
    subparsers._choices_actions = [
        action
        for action in subparsers._choices_actions
        if getattr(action, "dest", None) != name
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="feishu-codex",
        description=(
            "跨平台本地管理 CLI：负责安装、service 生命周期、配置入口和实例管理。\n\n"
            "说明：\n"
            "- 首次安装与修复都请从仓库根目录执行 `bash install.sh` 或 `./install.ps1`\n"
            "- `feishu-codex` 是唯一公开管理面；底层会调用原生 service manager\n"
            "  管理后台进程与“登录后自动启动”：Linux=systemd、macOS=LaunchAgent、Windows=Task Scheduler\n"
            "- 安装脚本会重建 shared wrapper，并为所有已知实例重建 service 定义/注册材料；\n"
            "  只刷新 `*.example` 并补齐缺失 scaffold，不覆盖现有配置或数据\n"
            "- `start|stop|restart|status` 只管理当前运行态；`autostart` 单独管理登录后自动启动\n"
            "- 命名实例必须先显式 `instance create`；其他命令不会隐式创建命名实例\n"
            "- `uninstall|purge` 只清理本机安装面；不会删除你在各工作区安装的 `.agents/skills`\n"
            "- `run` 是跨平台单一 daemon 入口，通常由底层 service manager 调用\n"
        ),
        epilog=(
            "常见流程:\n"
            "  首次安装 / 修复:\n"
            "    bash install.sh\n"
            "    # Windows PowerShell: .\\install.ps1\n"
            "\n"
            "  默认实例启动:\n"
            "    feishu-codex config system --open\n"
            "    feishu-codex start\n"
            "\n"
            "  多实例:\n"
            "    feishu-codex instance create corp-a\n"
            "    feishu-codex --instance corp-a config system --open\n"
            "    feishu-codex --instance corp-a autostart enable\n"
            "    feishu-codex --instance corp-a start\n"
            "\n"
            "  在目标目录启用发图 skill（可选）:\n"
            "    feishu-codex skill install\n"
            "\n"
            "  批量查看 / 控制多个实例:\n"
            "    feishu-codex --instance default --instance corp-a status\n"
            "    feishu-codex --instance default --instance corp-a autostart status\n"
        ),
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "--instance",
        action="append",
        default=argparse.SUPPRESS,
        metavar="NAME",
        help=(
            "目标实例；默认按当前 CLI 实例解析规则选择。可重复传入，仅对 `start|stop|restart|status|autostart ...` "
            "这类天然可批量命令生效。命名实例必须先用 `instance create` 创建。"
            "对 `instance ...` 子命令无效。"
        ),
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        title="commands",
        metavar="command",
    )

    subparsers.add_parser(
        "bootstrap-install",
        help="内部安装入口；一般不手动调用。",
        description="内部安装入口；通常由 `install.py` 调用。",
        formatter_class=_HelpFormatter,
    )
    _hide_subcommand_from_help(subparsers, "bootstrap-install")
    subparsers.add_parser(
        "start",
        help="启动目标实例后台 service。",
        description="启动目标实例后台 service，不改变登录后自动启动设置。",
        formatter_class=_HelpFormatter,
    )
    subparsers.add_parser(
        "stop",
        help="停止目标实例后台 service。",
        description="停止目标实例后台 service，不改变登录后自动启动设置。",
        formatter_class=_HelpFormatter,
    )
    subparsers.add_parser(
        "restart",
        help="重启目标实例后台 service。",
        description="重启目标实例后台 service，不改变登录后自动启动设置。service 定义缺失时会直接报错。",
        formatter_class=_HelpFormatter,
    )
    subparsers.add_parser(
        "status",
        help="查看目标实例当前运行态。",
        description=(
            "查看目标实例当前运行态。\n"
            "这描述的是后台进程当前是否在运行，而不是登录后自动启动是否开启。"
        ),
        formatter_class=_HelpFormatter,
    )

    autostart_parser = subparsers.add_parser(
        "autostart",
        help="管理目标实例“登录后自动启动”设置。",
        description=(
            "管理目标实例“登录后自动启动”设置。\n"
            "底层会调用当前平台原生 service manager 完成设置；不会直接改动当前运行态。"
        ),
        formatter_class=_HelpFormatter,
    )
    autostart_subparsers = autostart_parser.add_subparsers(
        dest="autostart_command",
        required=True,
        title="autostart commands",
        metavar="autostart-command",
    )
    autostart_subparsers.add_parser(
        "enable",
        help="开启登录后自动启动。",
        description="开启目标实例登录后自动启动，不会立即启动它。",
        formatter_class=_HelpFormatter,
    )
    autostart_subparsers.add_parser(
        "disable",
        help="关闭登录后自动启动。",
        description="关闭目标实例登录后自动启动，不会立即停止它。",
        formatter_class=_HelpFormatter,
    )
    autostart_subparsers.add_parser(
        "status",
        help="查看登录后自动启动是否开启。",
        description="查看目标实例登录后自动启动是否开启。",
        formatter_class=_HelpFormatter,
    )
    subparsers.add_parser(
        "run",
        help="以前台方式运行目标实例 daemon；通常由 service manager 调用。",
        description="以前台方式运行目标实例 daemon；通常由 systemd/launchd/Task Scheduler 调用。",
        formatter_class=_HelpFormatter,
    )

    log_parser = subparsers.add_parser(
        "log",
        help="查看目标实例日志文件并持续跟随。",
        description="查看目标实例日志文件并持续跟随。",
        formatter_class=_HelpFormatter,
    )
    log_parser.add_argument("--lines", type=int, default=40, help="启动时先输出的历史日志行数。")

    config_parser = subparsers.add_parser(
        "config",
        help="查看或打开当前实例相关配置文件。",
        description=(
            "查看或打开当前实例相关配置文件。\n"
            "可用目标：`system`、`codex`、`env`、`init-token`。"
        ),
        formatter_class=_HelpFormatter,
    )
    config_parser.add_argument(
        "target",
        nargs="?",
        choices=["system", "codex", "env", "init-token"],
        help="要查看的配置目标；省略时打印各配置文件路径。",
    )
    config_parser.add_argument("--open", action="store_true", help="用本地编辑器打开目标文件。")

    instance_parser = subparsers.add_parser(
        "instance",
        help="创建、列出、删除命名实例。",
        description=(
            "实例管理。\n"
            "注意：`feishu-codex instance ...` 不接受顶层 `--instance`；目标实例名写在子命令参数里。"
        ),
        formatter_class=_HelpFormatter,
    )
    instance_subparsers = instance_parser.add_subparsers(
        dest="instance_command",
        required=True,
        title="instance commands",
        metavar="instance-command",
    )
    instance_create_parser = instance_subparsers.add_parser(
        "create",
        help="创建命名实例，并准备对应后台 service 定义/注册材料。",
        description="创建命名实例，并准备对应后台 service 定义/注册材料；不会自动启动，也不会自动开启登录后自动启动。",
        formatter_class=_HelpFormatter,
    )
    instance_create_parser.add_argument("name", help="要创建的实例名，例如 `corp-a`。")
    instance_subparsers.add_parser(
        "list",
        help="列出本机已知实例及其本地目录。",
        description="列出本机已知实例及其本地目录。",
        formatter_class=_HelpFormatter,
    )
    instance_remove_parser = instance_subparsers.add_parser(
        "remove",
        help="删除命名实例及其实例级 service 注册材料。",
        description="删除命名实例及其实例级 service 注册材料；不会删除 `default` 实例。",
        formatter_class=_HelpFormatter,
    )
    instance_remove_parser.add_argument("name", help="要删除的实例名，例如 `corp-a`。")

    skill_parser = subparsers.add_parser(
        "skill",
        help="安装或卸载 feishu-codex 提供的工作区 skill。",
        description=(
            "Skill 管理。\n"
            "在当前目录 `.agents/skills` 安装或卸载 feishu-codex 自带的工作区 skills。\n"
            "在 `~` 下执行时，home 下线程可发现；在仓库目录下执行时，只对该仓库生效。\n"
            "注意：`feishu-codex skill ...` 不接受顶层 `--instance`。"
        ),
        formatter_class=_HelpFormatter,
    )
    skill_subparsers = skill_parser.add_subparsers(
        dest="skill_command",
        required=True,
        title="skill commands",
        metavar="skill-command",
    )
    skill_subparsers.add_parser(
        "install",
        help="安装 feishu-codex 自带的受管 skills 到当前目录。",
        description=(
            "把 feishu-codex 自带的受管 skills 安装到当前目录 `.agents/skills`。\n"
            "当前包括：`feishu-send-image`、`feishu-scheduled-prompts`。"
        ),
        formatter_class=_HelpFormatter,
    )
    skill_subparsers.add_parser(
        "uninstall",
        help="卸载当前目录下 feishu-codex 受管安装的 skills。",
        description=(
            "删除当前目录 `.agents/skills` 下 feishu-codex 受管安装的 skills；"
            "不会删除其他来源的 skills。"
        ),
        formatter_class=_HelpFormatter,
    )

    subparsers.add_parser(
        "uninstall",
        help="卸载所有 service 定义 / 自启动注册与 wrapper，保留配置与数据。",
        description="卸载所有 service 定义 / 自启动注册与 wrapper，保留配置与数据。",
        formatter_class=_HelpFormatter,
    )
    subparsers.add_parser(
        "purge",
        help="卸载所有 service 定义 / 自启动注册与 wrapper，并删除配置与数据。",
        description="卸载所有 service 定义 / 自启动注册与 wrapper，并删除配置与数据。",
        formatter_class=_HelpFormatter,
    )
    return parser


def _managed_venv_dir() -> pathlib.Path:
    return default_data_root() / ".venv"


def _venv_python() -> pathlib.Path:
    venv_dir = _managed_venv_dir()
    if is_windows():
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _managed_skill_spec(skill_name: str) -> _ManagedSkillSpec:
    normalized = str(skill_name or "").strip()
    for spec in _MANAGED_SKILLS:
        if spec.name == normalized:
            return spec
    raise ValueError(f"未知受管 skill：{normalized}")


def _managed_skill_source_dir(skill_name: str = _DEFAULT_MANAGED_SKILL_NAME) -> pathlib.Path:
    package = importlib.import_module(_managed_skill_spec(skill_name).package)
    return pathlib.Path(package.__file__).resolve().parent / "skill"


def _managed_skill_target_dir(skill_name: str = _DEFAULT_MANAGED_SKILL_NAME) -> pathlib.Path:
    return pathlib.Path.cwd() / ".agents" / "skills" / skill_name


def _managed_skill_marker_path(skill_dir: pathlib.Path) -> pathlib.Path:
    return skill_dir / _MANAGED_SKILL_MARKER


def _write_managed_skill_marker(skill_dir: pathlib.Path) -> None:
    skill_name = pathlib.Path(skill_dir).name
    _managed_skill_marker_path(skill_dir).write_text(
        f"managed_by=feishu-codex\nskill={skill_name}\n",
        encoding="utf-8",
    )


def _is_feishu_codex_managed_skill(skill_dir: pathlib.Path) -> bool:
    marker = _managed_skill_marker_path(skill_dir)
    if not marker.exists():
        return False
    try:
        contents = marker.read_text(encoding="utf-8")
    except OSError:
        return False
    skill_name = pathlib.Path(skill_dir).name
    return "managed_by=feishu-codex" in contents and f"skill={skill_name}" in contents


def _skill_tree_matches_source(skill_dir: pathlib.Path, source_dir: pathlib.Path) -> bool:
    normalized_target = pathlib.Path(skill_dir)
    normalized_source = pathlib.Path(source_dir)
    if not normalized_target.is_dir() or not normalized_source.is_dir():
        return False
    comparison = filecmp.dircmp(
        normalized_source,
        normalized_target,
        ignore=[_MANAGED_SKILL_MARKER, "__pycache__"],
    )
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(
        normalized_source,
        normalized_target,
        comparison.common_files,
        shallow=False,
    )
    if mismatch or errors:
        return False
    return all(
        _skill_tree_matches_source(normalized_target / common_dir, normalized_source / common_dir)
        for common_dir in comparison.common_dirs
    )


def _ensure_text_file(path: pathlib.Path, contents: str, *, overwrite: bool, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return
    path.write_text(contents, encoding="utf-8")
    if private:
        ensure_private_file_permissions(path)


def _ensure_init_token(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8").strip():
        return
    path.write_text(secrets.token_urlsafe(24) + "\n", encoding="utf-8")
    ensure_private_file_permissions(path)


def _ensure_instance_scaffold(instance_name: str) -> None:
    paths = apply_instance_environment(instance_name)
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.global_data_dir.mkdir(parents=True, exist_ok=True)
    _ensure_text_file(paths.config_dir / "system.yaml.example", SYSTEM_YAML_TEMPLATE, overwrite=True)
    _ensure_text_file(paths.config_dir / "codex.yaml.example", CODEX_YAML_TEMPLATE, overwrite=True)
    _ensure_text_file(paths.config_dir / "system.yaml", SYSTEM_YAML_TEMPLATE, overwrite=False, private=True)
    _ensure_text_file(paths.config_dir / "codex.yaml", render_initial_codex_yaml(), overwrite=False)
    ensure_env_template()
    _ensure_init_token(paths.config_dir / "init.token")


def _module_command(module_name: str, *args: str) -> tuple[str, ...]:
    return (str(_venv_python()), "-m", module_name, *args)


def _wrapper_path(command_name: str) -> pathlib.Path:
    bin_dir = default_user_bin_dir()
    if is_windows():
        return bin_dir / f"{command_name}.cmd"
    return bin_dir / command_name


def _service_daemon_command(instance_name: str) -> tuple[str, ...]:
    return (
        str(_wrapper_path("feishu-codex")),
        "--instance",
        validate_instance_name(instance_name),
        "run",
    )


def _write_wrapper(path: pathlib.Path, module_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entrypoint = f"from {module_name} import main; main()"
    if is_windows():
        wrapper_path = path.with_suffix(".cmd")
        wrapper_path.write_text(
            "\r\n".join(
                [
                    "@echo off",
                    f'"{_venv_python()}" -c "{entrypoint}" %*',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env sh",
                f'exec "{_venv_python()}" -c \'{entrypoint}\' "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def _install_wrappers() -> pathlib.Path:
    bin_dir = default_user_bin_dir()
    _write_wrapper(bin_dir / "feishu-codex", "bot.manage_cli")
    _write_wrapper(bin_dir / "feishu-codexd", "bot.__main__")
    _write_wrapper(bin_dir / "feishu-codexctl", "bot.feishu_codexctl")
    _write_wrapper(bin_dir / "fcodex", "bot.fcodex")
    return bin_dir


def _open_in_editor(path: pathlib.Path) -> int:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not editor:
        editor = "notepad" if is_windows() else "nano"
    argv = [*shlex.split(editor), str(path)]
    return subprocess.call(argv)


def _tail_log(path: pathlib.Path, *, lines: int) -> int:
    if not path.exists():
        print(f"log file not found: {path}", file=sys.stderr)
        return 2
    buffer = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in buffer[-max(lines, 0) :]:
        print(line)
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(0, os.SEEK_END)
        try:
            while True:
                line = handle.readline()
                if line:
                    print(line, end="")
                    continue
                time.sleep(0.5)
        except KeyboardInterrupt:
            return 0


def _service_definition(instance_name: str):
    normalized = validate_instance_name(instance_name)
    paths = resolve_instance_paths(normalized)
    return build_service_definition(
        instance_name=normalized,
        paths=paths,
        daemon_command=_service_daemon_command(normalized),
    )


def _prepare_cli_instance(instance_name: str) -> str:
    normalized = validate_instance_name(instance_name)
    if normalized == DEFAULT_INSTANCE_NAME:
        _ensure_instance_scaffold(normalized)
        return normalized
    return require_instance_exists(normalized)


def _normalize_requested_instances(instance_names: list[str] | tuple[str, ...] | None) -> list[str]:
    raw_values = list(instance_names or [])
    if not raw_values:
        raw_values = [DEFAULT_INSTANCE_NAME]
    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        normalized = validate_instance_name(raw)
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _single_requested_instance(
    instance_names: list[str] | tuple[str, ...] | None,
    *,
    command_label: str,
) -> str:
    normalized_values = _normalize_requested_instances(instance_names)
    if len(normalized_values) != 1:
        raise ValueError(f"`{command_label}` 当前只支持单个实例；请只传一个 `--instance`。")
    return normalized_values[0]


def _load_daemon_entry():
    return importlib.import_module("bot.__main__")


def _print_install_summary(
    bin_dir: pathlib.Path,
    rebuilt_instances: list[str],
    *,
    completion_result: CompletionInstallResult,
) -> None:
    print("安装完成。")
    print(f"配置根目录: {default_config_root()}")
    print(f"数据根目录: {default_data_root()}")
    print(f"命令目录: {bin_dir}")
    if completion_result.bash_dir is not None:
        print(f"Bash completion: {completion_result.bash_dir}")
    if completion_result.zsh_script_path is not None:
        print(f"zsh completion: {completion_result.zsh_script_path}")
    if completion_result.powershell_script_path is not None:
        print(f"PowerShell completion: {completion_result.powershell_script_path}")
    print("  - 本地服务进程管理 feishu-codex --help")
    print("  - 本地查看、管理 binding / thread 状态  feishu-codexctl --help")
    print(f"已重建实例: {', '.join(rebuilt_instances)}。不覆盖各实例现有用户配置")
    if not (shutil.which("codex") or detect_stable_codex_command()):
        print("警告: 未检测到 `codex` 命令，请先安装 Codex CLI。")
    if is_windows():
        print("Windows 用户 PATH: 已确保包含命令目录；新开 PowerShell / cmd 后应可直接发现命令。")
    print("")
    print("下一步:")
    print("  1. 配置飞书应用、provider 环境变量")
    print(f"    - feishu-codex config --open system")
    print(f"    - feishu-codex config --open env（按需）")
    print("  2. 启动服务并设置登陆后自动启动")
    print("    - feishu-codex start")
    print("    - feishu-codex autostart enable")
    print("  3. 飞书侧初始化")
    print("    - 查看初始化口令 feishu-codex config init-token")
    print("    - 在飞书侧发送 /init <token>")
    print("  4. 新建并配置命名实例")
    print("    - feishu-codex instance create corp-a")
    print("    - feishu-codex --instance corp-a start|autostart|config ...")
    print("  5. 如需在某个目录下启用 feishu-codex 附带 skills（可选）")
    print("    - 先 cd 到目标目录，再执行 feishu-codex skill install")
    print("    - 如需移除，回到同一目录执行 feishu-codex skill uninstall")
    print("    - 注意：feishu-codex uninstall/purge 不会删除各工作区中的 .agents/skills")
    if (
        completion_result.bash_dir is not None
        or completion_result.zsh_script_path is not None
        or completion_result.powershell_script_path is not None
    ):
        print("  6. Shell completion")
        if completion_result.bash_dir is not None:
            print("    - Bash：新开一个 Bash shell 通常会自动生效")
            print(f"    - 当前 shell 也可手动执行 source {completion_result.bash_dir / 'feishu-codex'}")
        if completion_result.zsh_script_path is not None:
            if completion_result.zsh_rc_path is not None:
                print(f"    - zsh：已写入自动加载钩子 {completion_result.zsh_rc_path}；新开 shell 即可生效")
            print(f"    - zsh：当前 shell 也可手动执行 source {completion_result.zsh_script_path}")
        if completion_result.powershell_script_path is not None:
            if completion_result.powershell_profile_path is not None:
                print(
                    "    - PowerShell：已写入自动加载 profile "
                    f"{completion_result.powershell_profile_path}；重开 PowerShell 即可生效"
                )
            else:
                print("    - PowerShell：当前执行策略禁止自动加载本地 profile 脚本；未写入自动加载钩子")
                print("    - PowerShell：如需自动生效，可先执行 Set-ExecutionPolicy -Scope CurrentUser RemoteSigned")
            print(f"    - PowerShell：当前 shell 也可手动执行 . '{completion_result.powershell_script_path}'")


def _handle_bootstrap_install() -> int:
    instance_names = list_known_instance_names()
    for instance_name in instance_names:
        _ensure_instance_scaffold(instance_name)
    bin_dir = _install_wrappers()
    _ensure_windows_user_path(bin_dir)
    if is_windows():
        remove_shell_completion_files()
        completion_result = CompletionInstallResult()
    else:
        completion_result = install_shell_completion_files(venv_python=_venv_python())
    manager = current_service_manager()
    for instance_name in instance_names:
        manager.ensure_service(_service_definition(instance_name))
    _print_install_summary(
        bin_dir,
        instance_names,
        completion_result=completion_result,
    )
    return 0


def _handle_service_action(instance_name: str, action: str) -> int:
    normalized = _prepare_cli_instance(instance_name)
    definition = _service_definition(normalized)
    manager = current_service_manager()
    if action == "start":
        display_name = manager.display_name(definition)
        manager.start(definition)
        print(f"started service: {display_name}")
        return 0
    if action == "stop":
        display_name = manager.display_name(definition)
        manager.stop(definition)
        print(f"stopped service: {display_name}")
        return 0
    if action == "restart":
        display_name = manager.display_name(definition)
        manager.restart(definition)
        print(f"restarted service: {display_name}")
        return 0
    if action == "status":
        status = manager.status(definition)
        print(f"service: {'installed' if status.installed else 'missing'}")
        print(f"running: {'yes' if status.running else 'no'}")
        if status.source and status.detail:
            print(f"{status.source}: {status.detail}")
        elif status.detail:
            print(f"detail: {status.detail}")
        return 0 if status.running else 3
    raise ValueError(f"unknown service action: {action}")


def _merge_batch_exit_codes(exit_codes: list[int]) -> int:
    if not exit_codes:
        return 0
    if any(code == 2 for code in exit_codes):
        return 2
    non_zero_codes = [code for code in exit_codes if code != 0]
    if non_zero_codes:
        return max(non_zero_codes)
    return 0


def _run_instance_batch(
    instance_names: list[str] | tuple[str, ...] | None,
    *,
    runner,
) -> int:
    normalized_values = _normalize_requested_instances(instance_names)
    if len(normalized_values) == 1:
        return int(runner(normalized_values[0]))

    exit_codes: list[int] = []
    for index, instance_name in enumerate(normalized_values):
        if index:
            print("")
        print(f"instance: {instance_name}")
        try:
            exit_codes.append(int(runner(instance_name)))
        except (ServiceManagerError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            exit_codes.append(2)
    return _merge_batch_exit_codes(exit_codes)


def _handle_service_actions(instance_names: list[str] | tuple[str, ...] | None, action: str) -> int:
    return _run_instance_batch(
        instance_names,
        runner=lambda instance_name: _handle_service_action(instance_name, action),
    )


def _handle_autostart_action(instance_name: str, action: str) -> int:
    normalized = _prepare_cli_instance(instance_name)
    definition = _service_definition(normalized)
    manager = current_service_manager()
    if action == "enable":
        display_name = manager.display_name(definition)
        manager.autostart_enable(definition)
        print(f"autostart enabled: {display_name}")
        return 0
    if action == "disable":
        display_name = manager.display_name(definition)
        manager.autostart_disable(definition)
        print(f"autostart disabled: {display_name}")
        return 0
    if action == "status":
        status = manager.autostart_status(definition)
        print(f"autostart: {'enabled' if status.enabled else 'disabled'}")
        if status.source and status.detail:
            print(f"{status.source}: {status.detail}")
        elif status.detail:
            print(f"detail: {status.detail}")
        return 0 if status.enabled else 3
    raise ValueError(f"unknown autostart action: {action}")


def _handle_autostart_actions(instance_names: list[str] | tuple[str, ...] | None, action: str) -> int:
    return _run_instance_batch(
        instance_names,
        runner=lambda instance_name: _handle_autostart_action(instance_name, action),
    )


def _handle_run(instance_name: str) -> int:
    daemon_entry = _load_daemon_entry()
    daemon_entry.main(["--instance", _prepare_cli_instance(instance_name)])
    return 0


def _handle_config(instance_name: str, target: str | None, *, open_editor: bool) -> int:
    normalized = validate_instance_name(instance_name)
    if target == "env":
        ensure_env_template()
    else:
        normalized = _prepare_cli_instance(normalized)
    paths = resolve_instance_paths(normalized)
    candidates = {
        "system": paths.config_dir / "system.yaml",
        "codex": paths.config_dir / "codex.yaml",
        "env": default_config_root() / "feishu-codex.env",
        "init-token": paths.config_dir / "init.token",
    }
    if target is None:
        print(f"instance: {normalized}")
        for key, path in candidates.items():
            print(f"{key}: {path}")
        return 0
    resolved = candidates[target]
    print(resolved)
    if open_editor:
        return _open_in_editor(resolved)
    return 0


def _remove_wrappers() -> None:
    bin_dir = default_user_bin_dir()
    if is_windows():
        for name in ("feishu-codex", "feishu-codexd", "feishu-codexctl", "fcodex"):
            try:
                (bin_dir / f"{name}.cmd").unlink()
            except FileNotFoundError:
                pass
        _remove_windows_user_path()
    else:
        for name in ("feishu-codex", "feishu-codexd", "feishu-codexctl", "fcodex"):
            try:
                (bin_dir / name).unlink()
            except FileNotFoundError:
                pass
    remove_shell_completion_files()


def _handle_uninstall(*, purge: bool) -> int:
    try:
        manager = current_service_manager()
    except ServiceManagerError:
        manager = None
    for instance_name in list_known_instance_names():
        definition = _service_definition(instance_name)
        if manager is not None:
            try:
                manager.uninstall(definition)
            except ServiceManagerError:
                pass
    if manager is not None and hasattr(manager, "uninstall_shared"):
        try:
            manager.uninstall_shared()
        except ServiceManagerError:
            pass
    _remove_wrappers()
    if purge:
        shutil.rmtree(default_config_root(), ignore_errors=True)
        shutil.rmtree(default_data_root(), ignore_errors=True)
        print("已删除配置、数据、service 定义与命令包装器。")
    else:
        print("已删除 service 定义与命令包装器，配置和数据保留。")
    return 0


def _handle_instance_create(instance_name: str) -> int:
    normalized = validate_instance_name(instance_name)
    _ensure_instance_scaffold(normalized)
    _install_wrappers()
    current_service_manager().ensure_service(_service_definition(normalized))
    paths = resolve_instance_paths(normalized)
    print(f"已初始化实例: {normalized}")
    print(f"config dir: {paths.config_dir}")
    print(f"data dir: {paths.data_dir}")
    print(f"shared env: {default_config_root() / 'feishu-codex.env'}")
    return 0


def _handle_instance_list() -> int:
    running_entries = {entry.instance_name: entry for entry in list_running_instances()}
    instance_names = sorted(set(list_known_instance_names()) | set(running_entries))
    print("instance\tstate\tconfig_dir\tdata_dir")
    for instance_name in instance_names:
        paths = resolve_instance_paths(instance_name)
        state = "running" if instance_name in running_entries else "stopped"
        print(f"{instance_name}\t{state}\t{paths.config_dir}\t{paths.data_dir}")
    return 0


def _remove_empty_parent(path: pathlib.Path, *, stop_at: pathlib.Path) -> None:
    current = pathlib.Path(path)
    boundary = pathlib.Path(stop_at)
    while True:
        if current == boundary:
            return
        try:
            current.rmdir()
        except FileNotFoundError:
            return
        except OSError:
            return
        parent = current.parent
        if parent == current:
            return
        current = parent


def _handle_instance_remove(instance_name: str) -> int:
    normalized = validate_instance_name(instance_name)
    if normalized == DEFAULT_INSTANCE_NAME:
        raise ValueError("不能删除 `default` 实例；如需整体清理，请用 `feishu-codex uninstall` 或 `purge`。")

    paths = resolve_instance_paths(normalized)

    try:
        manager = current_service_manager()
    except ServiceManagerError:
        manager = None

    if manager is not None:
        try:
            manager.uninstall(_service_definition(normalized))
        except ServiceManagerError:
            pass

    metadata = ServiceInstanceLease(paths.data_dir).load_metadata()
    if metadata is not None:
        raise ValueError(
            "目标实例仍有运行中的 service owner；请先确认该实例已经停止。"
            f" instance={normalized} owner_pid={metadata.owner_pid or 'unknown'}"
        )

    shutil.rmtree(paths.config_dir, ignore_errors=True)
    shutil.rmtree(paths.data_dir, ignore_errors=True)
    _remove_empty_parent(paths.config_dir.parent, stop_at=default_config_root())
    _remove_empty_parent(paths.data_dir.parent, stop_at=default_data_root())
    print(f"已删除实例: {normalized}")
    print(f"config dir: {paths.config_dir}")
    print(f"data dir: {paths.data_dir}")
    return 0


def _handle_skill_install() -> int:
    target_parent = pathlib.Path.cwd() / ".agents" / "skills"
    target_parent.mkdir(parents=True, exist_ok=True)
    install_plan: list[tuple[_ManagedSkillSpec, pathlib.Path, pathlib.Path, str]] = []
    for spec in _MANAGED_SKILLS:
        source_dir = _managed_skill_source_dir(spec.name)
        if not source_dir.is_dir():
            raise ValueError(f"skill 源目录不存在：{source_dir}")
        target_dir = _managed_skill_target_dir(spec.name)
        action = "copy"
        if target_dir.exists():
            if not target_dir.is_dir():
                raise ValueError(f"skill 目标路径已存在且不是目录：{target_dir}")
            if not _is_feishu_codex_managed_skill(target_dir):
                if _skill_tree_matches_source(target_dir, source_dir):
                    action = "keep"
                else:
                    raise ValueError(
                        "目标 skill 已存在且不是 feishu-codex 受管安装；"
                        f"请先手动处理：{target_dir}"
                    )
        install_plan.append((spec, source_dir, target_dir, action))

    for spec, source_dir, target_dir, action in install_plan:
        if action == "keep":
            print(f"当前目录已可用 skill: {spec.name}")
            print(f"target: {target_dir}")
            continue
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(source_dir, target_dir)
        _write_managed_skill_marker(target_dir)
        print(f"已安装 skill: {spec.name}")
        print(f"source: {source_dir}")
        print(f"target: {target_dir}")
    return 0


def _handle_skill_uninstall() -> int:
    removed_any = False
    for spec in _MANAGED_SKILLS:
        target_dir = _managed_skill_target_dir(spec.name)
        if not target_dir.exists():
            print(f"未安装 skill: {spec.name}")
            print(f"target: {target_dir}")
            continue
        if not target_dir.is_dir():
            raise ValueError(f"skill 目标路径不是目录：{target_dir}")
        if not _is_feishu_codex_managed_skill(target_dir):
            raise ValueError(
                "目标 skill 不是 feishu-codex 受管安装；拒绝删除："
                f" {target_dir}"
            )
        shutil.rmtree(target_dir)
        removed_any = True
        print(f"已卸载 skill: {spec.name}")
        print(f"target: {target_dir}")
    if not removed_any:
        print("当前目录没有 feishu-codex 受管安装的 skill。")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    requested_instances = getattr(args, "instance", [])
    try:
        if args.command == "bootstrap-install":
            raise SystemExit(_handle_bootstrap_install())
        if args.command in {"start", "stop", "restart", "status"}:
            raise SystemExit(_handle_service_actions(requested_instances, args.command))
        if args.command == "autostart":
            raise SystemExit(_handle_autostart_actions(requested_instances, args.autostart_command))
        if args.command == "run":
            raise SystemExit(_handle_run(_single_requested_instance(requested_instances, command_label="run")))
        if args.command == "log":
            raise SystemExit(
                _tail_log(
                    default_log_file(
                        resolve_instance_paths(
                            _single_requested_instance(requested_instances, command_label="log")
                        ).data_dir
                    ),
                    lines=args.lines,
                )
            )
        if args.command == "config":
            raise SystemExit(
                _handle_config(
                    _single_requested_instance(requested_instances, command_label="config"),
                    args.target,
                    open_editor=args.open,
                )
            )
        if args.command == "instance":
            if requested_instances:
                raise ValueError("`feishu-codex instance ...` 不接受顶层 `--instance`；请把目标实例写在子命令参数里。")
            if args.instance_command == "create":
                raise SystemExit(_handle_instance_create(args.name))
            if args.instance_command == "list":
                raise SystemExit(_handle_instance_list())
            if args.instance_command == "remove":
                raise SystemExit(_handle_instance_remove(args.name))
        if args.command == "skill":
            if requested_instances:
                raise ValueError("`feishu-codex skill ...` 不接受顶层 `--instance`。")
            if args.skill_command == "install":
                raise SystemExit(_handle_skill_install())
            if args.skill_command == "uninstall":
                raise SystemExit(_handle_skill_uninstall())
        if args.command == "uninstall":
            raise SystemExit(_handle_uninstall(purge=False))
        if args.command == "purge":
            raise SystemExit(_handle_uninstall(purge=True))
    except ServiceManagerError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(2)


if __name__ == "__main__":
    main()
