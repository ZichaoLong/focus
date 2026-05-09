"""
Feishu 侧一等 slash 命令事实源。

这里只定义仓库明确维护的 Feishu slash surface，供 help / cards / tests 复用。
upstream Codex TUI 内的原生命令不在这里。
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.feishu_command_syntax import feishu_visible_command_syntax


@dataclass(frozen=True)
class SharedCommandSpec:
    key: str
    slash_name: str
    feishu_usage: str
    feishu_summary: str


_SHARED_COMMAND_SPECS = (
    SharedCommandSpec(
        key="help",
        slash_name="/help",
        feishu_usage="/help [chat|group|thread|runtime|identity]",
        feishu_summary="查看帮助概览与主题入口。",
    ),
    SharedCommandSpec(
        key="commands",
        slash_name="/commands",
        feishu_usage="/commands",
        feishu_summary="按帮助分组查看常用命令列表。",
    ),
    SharedCommandSpec(
        key="profile",
        slash_name="/profile",
        feishu_usage="/profile [name]",
        feishu_summary="查看或切换当前绑定 thread 的 resume profile。",
    ),
    SharedCommandSpec(
        key="memory",
        slash_name="/memory",
        feishu_usage="/memory [off|read|read_write]",
        feishu_summary="查看或切换当前绑定 thread 的 thread-wise memory mode。",
    ),
    SharedCommandSpec(
        key="compact",
        slash_name="/compact",
        feishu_usage="/compact",
        feishu_summary="压缩当前绑定 thread 的上下文历史。",
    ),
    SharedCommandSpec(
        key="reset-backend",
        slash_name="/reset-backend",
        feishu_usage="/reset-backend",
        feishu_summary="预览并重置当前实例 backend。",
    ),
    SharedCommandSpec(
        key="archive",
        slash_name="/archive",
        feishu_usage="/archive [thread_id|thread_name]",
        feishu_summary="归档当前线程或指定线程。",
    ),
    SharedCommandSpec(
        key="threads",
        slash_name="/threads",
        feishu_usage="/threads",
        feishu_summary="查看当前目录线程。",
    ),
    SharedCommandSpec(
        key="preflight",
        slash_name="/preflight",
        feishu_usage="/preflight",
        feishu_summary="预检当前 chat 下一条普通消息与 detach 可用性。",
    ),
    SharedCommandSpec(
        key="resume",
        slash_name="/resume",
        feishu_usage=feishu_visible_command_syntax("/resume <thread_id|thread_name>"),
        feishu_summary="恢复指定线程。",
    ),
    SharedCommandSpec(
        key="detach",
        slash_name="/detach",
        feishu_usage="/detach",
        feishu_summary="暂停当前会话接收当前线程的飞书推送。",
    ),
    SharedCommandSpec(
        key="attach",
        slash_name="/attach",
        feishu_usage="/attach [binding|thread|service]",
        feishu_summary="恢复当前会话、当前线程或当前实例的飞书推送。",
    ),
    SharedCommandSpec(
        key="skills",
        slash_name="/skills",
        feishu_usage="/skills",
        feishu_summary="查看当前目录可见的 skills，并启用或禁用。",
    ),
    SharedCommandSpec(
        key="plugins",
        slash_name="/plugins",
        feishu_usage="/plugins [plugin_id]",
        feishu_summary="查看当前目录可见的 plugins，或查看指定 plugin 详情。",
    ),
)

_SHARED_COMMANDS_BY_KEY = {spec.key: spec for spec in _SHARED_COMMAND_SPECS}


def iter_shared_commands() -> tuple[SharedCommandSpec, ...]:
    return _SHARED_COMMAND_SPECS


def get_shared_command(key: str) -> SharedCommandSpec:
    return _SHARED_COMMANDS_BY_KEY[key]
