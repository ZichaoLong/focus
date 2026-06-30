"""Unified local management CLI for FOCUS."""

from __future__ import annotations

import sys

from bot.version import __version__

_MANAGE_RESOURCES = {"config", "instance", "skill", "uninstall", "purge", "bootstrap-install"}
_RUNTIME_RESOURCES = {"binding", "prompt", "thread", "image"}
_SERVICE_LIFECYCLE_ACTIONS = {"start", "stop", "restart", "autostart", "log"}
_SERVICE_RUNTIME_ACTIONS = {"status", "reset-backend", "attach"}


def _print_help() -> None:
    print(
        "focusctl 管理 FOCUS 本地系统。\n\n"
        "用法:\n"
        "  focusctl [--instance <name>] <resource> <command> [args ...]\n\n"
        "资源:\n"
        "  config      查看或打开 system/codex/env/init-token 配置\n"
        "  instance    管理本机已知实例；`instance list` 是已知实例视图\n"
        "  service     管理后台服务、运行态 control plane 与 app-server\n"
        "  binding     查看、恢复、暂停或清理 Feishu binding\n"
        "  thread      查看或管理 Codex thread\n"
        "  prompt      向 binding 合成提交 prompt\n"
        "  image       向 thread attached bindings 发送本地图片\n"
        "  skill       安装或卸载 FOCUS 提供的 workspace skills\n\n"
        "常用命令:\n"
        "  focusctl config system --open\n"
        "  focusctl config env --open\n"
        "  focusctl instance create explorer\n"
        "  focusctl instance list\n"
        "  focusctl service start\n"
        "  focusctl service status\n"
        "  focusctl service list\n"
        "  focusctl service autostart enable\n"
        "  focusctl binding list\n"
        "  focusctl binding clear-stale --dry-run\n"
        "  focusctl thread list --scope cwd\n"
        "  focusctl thread archive --thread-id <id>\n"
        "  focusctl image send --thread-id <id> --path ./diagram.png\n\n"
        "工作入口:\n"
        "  focus / fcodex 是 Codex TUI thin wrapper；focusctl 不进入 TUI。\n"
    )


def _consume_global_options(argv: list[str]) -> tuple[list[str], list[str]]:
    global_args: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        if item == "--":
            rest.extend(argv[index + 1 :])
            break
        if item in {"-h", "--help"}:
            global_args.append(item)
            index += 1
            continue
        if item == "--version":
            global_args.append(item)
            index += 1
            continue
        if item == "--instance":
            if index + 1 >= len(argv):
                rest.extend(argv[index:])
                break
            global_args.extend([item, argv[index + 1]])
            index += 2
            continue
        if item.startswith("--instance="):
            global_args.append(item)
            index += 1
            continue
        rest.extend(argv[index:])
        break
    return global_args, rest


def _single_instance_args(global_args: list[str]) -> list[str]:
    instance_values = [arg for arg in global_args if arg.startswith("--instance=")]
    index = 0
    while index < len(global_args):
        if global_args[index] == "--instance" and index + 1 < len(global_args):
            instance_values.append(global_args[index + 1])
            index += 2
            continue
        index += 1
    if len(instance_values) > 1:
        raise ValueError("当前命令只接受一个 `--instance`；批量 service lifecycle 请分别执行。")
    return list(global_args)


def _run_manage(args: list[str]) -> None:
    from bot.manage_cli import main as manage_main

    manage_main(args)


def _run_runtime(args: list[str]) -> None:
    from bot.feishu_codexctl import main as runtime_main

    runtime_main(args)


def main(argv: list[str] | None = None) -> None:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if not raw_args or raw_args in (["-h"], ["--help"]):
        _print_help()
        raise SystemExit(0)
    if raw_args == ["--version"]:
        print(f"focusctl {__version__}")
        raise SystemExit(0)

    global_args, rest = _consume_global_options(raw_args)
    if "--version" in global_args:
        print(f"focusctl {__version__}")
        raise SystemExit(0)
    if "-h" in global_args or "--help" in global_args:
        _print_help()
        raise SystemExit(0)
    if not rest:
        _print_help()
        raise SystemExit(0)
    if rest[0] in {"-h", "--help"}:
        _print_help()
        raise SystemExit(0)

    resource = rest[0]
    try:
        if resource in _MANAGE_RESOURCES:
            _run_manage([*global_args, *rest])
            return
        if resource in _RUNTIME_RESOURCES:
            _run_runtime([*_single_instance_args(global_args), *rest])
            return
        if resource == "service":
            if len(rest) < 2 or rest[1] in {"-h", "--help"}:
                print(
                    "focusctl service commands:\n"
                    "  start | stop | restart | autostart <enable|disable|status> | log\n"
                    "  status | reset-backend | attach | list"
                )
                raise SystemExit(0)
            action = rest[1]
            action_args = rest[2:]
            if action in _SERVICE_LIFECYCLE_ACTIONS:
                _run_manage([*global_args, action, *action_args])
                return
            if action == "list":
                _run_runtime([*_single_instance_args(global_args), "instance", "list", *action_args])
                return
            if action in _SERVICE_RUNTIME_ACTIONS:
                _run_runtime([*_single_instance_args(global_args), "service", action, *action_args])
                return
            raise ValueError(f"未知 service 命令：{action}")
        raise ValueError(f"未知资源：{resource}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
