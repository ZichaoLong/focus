"""
feishu-codex 飞书卡片构建。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTriggerResponse,
    CallBackCard,
    CallBackToast,
)

from bot.adapters.base import ThreadGoalSummary
from bot.card_text_projection import (
    TERMINAL_RESULT_CARD_TITLE,
    render_final_reply_text_block,
)
from bot.constants import display_path, format_timestamp, shorten
from bot.execution_transcript import ExecutionReplySegment
from bot.feishu_card_markdown import (
    sanitize_runtime_markdown_for_feishu_card,
    sanitize_terminal_result_markdown_for_feishu_json2,
)
from bot.feishu_command_syntax import feishu_visible_command_syntax
from bot.feishu_bot import _MAX_CARD_TABLES, count_card_tables, limit_card_tables
from bot.permissions_profile import PERMISSION_PROFILE_CHOICES, permissions_profile_choice_key, permissions_profile_label
from bot.shared_command_surface import get_shared_command


def make_card_response(
    card: dict | None = None,
    toast: str | None = None,
    toast_type: str = "info",
) -> P2CardActionTriggerResponse:
    """构造卡片动作的响应（可更新卡片 / 弹 toast）"""
    resp = P2CardActionTriggerResponse()
    if toast:
        resp.toast = CallBackToast()
        resp.toast.type = toast_type
        resp.toast.content = toast
    if card:
        resp.card = CallBackCard()
        resp.card.type = "raw"
        resp.card.data = card
    return resp


@dataclass(frozen=True)
class CommandResult:
    """Command handler return value; handler dispatches the reply."""

    text: str = ""
    card: dict | None = None
    after_dispatch: Callable[[], None] | None = None


_HISTORY_TEXT_MAX = 300
_PLAN_CONTENT_MAX = 4000
_GOAL_OBJECTIVE_MAX = 400
_SHARED_RESUME_COMMAND = get_shared_command("resume")
_SHARED_RESET_BACKEND_COMMAND = get_shared_command("reset-backend")
_LOCAL_THREAD_LIST_CWD = "feishu-codexctl thread list --scope cwd"
_LOCAL_RESUME_COMMAND = feishu_visible_command_syntax("fcodex resume <thread_id|thread_name>")


def _card_config() -> dict:
    return {"wide_screen_mode": True, "update_multi": True}


def _card_config_v2() -> dict:
    return {"update_multi": True}


def _format_ts_ms(value: int) -> str:
    try:
        timestamp = float(value) / 1000.0
    except (TypeError, ValueError):
        return "（未知）"
    if timestamp <= 0:
        return "（未知）"
    return format_timestamp(timestamp)


def _format_ts_seconds(value: int) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return "（未知）"
    if timestamp <= 0:
        return "（未知）"
    return format_timestamp(timestamp)


def goal_status_label(status: str) -> str:
    return {
        "active": "进行中",
        "paused": "已暂停",
        "blocked": "已阻塞",
        "usageLimited": "触发 usage 限制",
        "budgetLimited": "触发预算限制",
        "complete": "已完成",
    }.get(str(status or "").strip(), "未知")


def goal_template(status: str, *, has_goal: bool) -> str:
    if not has_goal:
        return "blue"
    normalized = str(status or "").strip()
    if normalized == "active":
        return "turquoise"
    if normalized == "paused":
        return "grey"
    if normalized == "complete":
        return "green"
    if normalized in {"blocked", "usageLimited", "budgetLimited"}:
        return "orange"
    return "blue"


def format_goal_summary_markdown(
    *,
    objective: str,
    status: str,
    token_budget: int | None,
    tokens_used: int,
    time_used_seconds: int,
) -> list[str]:
    normalized_objective = str(objective or "").strip()
    if not normalized_objective:
        return []
    lines = [
        f"当前 goal：`{str(status or '').strip() or 'unknown'}` ({goal_status_label(status)}) {shorten(normalized_objective, 120)}"
    ]
    metrics: list[str] = []
    if token_budget is not None:
        metrics.append(f"预算：`{int(token_budget)}`")
    metrics.append(f"已用 tokens：`{int(tokens_used or 0)}`")
    metrics.append(f"时长：`{int(time_used_seconds or 0)}s`")
    lines.append("goal 摘要：" + "；".join(metrics))
    return lines


def build_markdown_card(title: str, content: str, *, template: str = "blue") -> dict:
    """构造简单说明卡片。"""
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": [{"tag": "markdown", "content": sanitize_runtime_markdown_for_feishu_card(content)}],
    }


def build_markdown_action_card(
    title: str,
    content: str,
    *,
    action_rows: list[dict] | None = None,
    template: str = "blue",
) -> dict:
    elements: list[dict] = [
        {"tag": "markdown", "content": sanitize_runtime_markdown_for_feishu_card(content)},
    ]
    if action_rows:
        elements.append({"tag": "hr"})
        elements.extend(action_rows)
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": elements,
    }


def build_terminal_result_card(
    final_reply_text: str,
) -> dict:
    """构造终态结果卡。"""
    raw_text = str(final_reply_text or "")
    normalized = sanitize_terminal_result_markdown_for_feishu_json2(raw_text)
    return {
        "schema": "2.0",
        "config": _card_config_v2(),
        "header": {
            "title": {"tag": "plain_text", "content": TERMINAL_RESULT_CARD_TITLE},
            "template": "green",
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": render_final_reply_text_block(normalized),
                }
            ]
        },
    }


def build_profile_card(
    *,
    content: str,
    profile_names: list[str],
    current_profile: str,
    extra_action_rows: list[dict] | None = None,
    title: str = "Codex Backend Startup Profile",
) -> dict:
    """构造 profile 选择卡片。"""
    elements: list[dict] = [
        {"tag": "markdown", "content": content},
    ]
    if profile_names:
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": profile_name},
                            "type": "primary" if profile_name == current_profile else "default",
                            "value": {
                                "action": "set_profile",
                                "profile": profile_name,
                            },
                        }
                        for profile_name in profile_names
                    ],
                },
            ]
        )
    if extra_action_rows:
        elements.extend(extra_action_rows)
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "elements": elements,
    }


def build_backend_reset_card(
    *,
    content: str,
    force: bool | None = None,
    extra_action_rows: list[dict] | None = None,
    title: str = "Codex Backend Reset",
    template: str = "blue",
) -> dict:
    """构造 backend reset 预览/结果卡片。"""
    elements: list[dict] = [
        {"tag": "markdown", "content": content},
    ]
    if force is not None:
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "强制重置 backend" if force else "重置 backend",
                            },
                            "type": "danger" if force else "primary",
                            "value": {
                                "action": "reset_backend",
                                "force": bool(force),
                            },
                        }
                    ],
                },
            ]
        )
    elif extra_action_rows:
        elements.extend(extra_action_rows)
    else:
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": f"重新检查请发送 `{_SHARED_RESET_BACKEND_COMMAND.slash_name}`。",
                },
            ]
        )
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "elements": elements,
    }


def build_goal_card(
    *,
    thread_id: str,
    thread_title: str,
    goal: ThreadGoalSummary | None,
    notice: str = "",
) -> dict:
    has_goal = goal is not None and bool(str(goal.objective or "").strip())
    normalized_thread_id = str(thread_id or "").strip()
    normalized_thread_title = str(thread_title or "").strip()
    elements: list[dict] = []

    lines = [
        (
            f"线程：`{normalized_thread_id[:8]}…` {normalized_thread_title or '（无标题）'}"
            if normalized_thread_id
            else "线程：-"
        )
    ]
    if notice:
        lines.extend(["", notice])
    if has_goal and goal is not None:
        lines.extend(
            [
                "",
                f"目标：{shorten(goal.objective, _GOAL_OBJECTIVE_MAX)}",
                f"状态：`{goal.status}` ({goal_status_label(goal.status)})",
                (
                    f"Token Budget：`{goal.token_budget}`"
                    if goal.token_budget is not None
                    else "Token Budget：`未设置`"
                ),
                f"已用 Tokens：`{goal.tokens_used}`",
                f"已用时长：`{goal.time_used_seconds}s`",
                f"创建时间：`{_format_ts_seconds(goal.created_at)}`",
                f"更新时间：`{_format_ts_seconds(goal.updated_at)}`",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "当前 thread 暂无 goal。",
                f"设置方式：`{feishu_visible_command_syntax('/goal set <objective>')}`",
            ]
        )
    elements.append(
        {
            "tag": "markdown",
            "content": sanitize_runtime_markdown_for_feishu_card("\n".join(lines)),
        }
    )

    actions: list[dict] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "刷新"},
            "type": "default",
            "value": {"action": "goal_refresh"},
        }
    ]
    if has_goal and goal is not None:
        if goal.status == "active":
            actions.insert(
                0,
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "暂停"},
                    "type": "default",
                    "value": {"action": "goal_pause"},
                },
            )
        elif goal.status == "paused":
            actions.insert(
                0,
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "恢复"},
                    "type": "primary",
                    "value": {"action": "goal_resume"},
                },
            )
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "清除"},
                "type": "danger",
                "value": {"action": "goal_clear"},
            }
        )
    elements.extend(
        [
            {"tag": "hr"},
            {"tag": "action", "actions": actions},
        ]
    )

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex Goal"},
            "template": goal_template(goal.status if goal is not None else "", has_goal=has_goal),
        },
        "elements": elements,
    }


def build_goal_detached_confirm_card(
    *,
    thread_id: str,
    thread_title: str,
    objective: str = "",
    status: str = "",
) -> dict:
    normalized_thread_id = str(thread_id or "").strip()
    normalized_thread_title = str(thread_title or "").strip()
    normalized_objective = str(objective or "").strip()
    normalized_status = str(status or "").strip()
    action_label = "恢复当前 thread goal" if normalized_status == "active" and not normalized_objective else "更新当前 thread goal"
    lines = [
        (
            f"线程：`{normalized_thread_id[:8]}…` {normalized_thread_title or '（无标题）'}"
            if normalized_thread_id
            else "线程：-"
        ),
        "",
        "当前会话处于 `detached`。",
        f"{action_label} 可能让已 loaded 的 backend 在后台继续执行，但当前会话不会自动恢复飞书推送。",
    ]
    if normalized_objective:
        lines.append(f"目标：{shorten(normalized_objective, _GOAL_OBJECTIVE_MAX)}")
    if normalized_status:
        lines.append(f"状态：`{normalized_status}` ({goal_status_label(normalized_status)})")
    lines.extend(
        [
            "",
            "请选择：",
            "- 恢复推送并继续：先把当前会话 attach 回来，再应用这次 goal 变更",
            "- 保持 detached：只应用 goal 变更，不恢复当前会话推送",
        ]
    )
    return build_markdown_action_card(
        "Codex Goal",
        "\n".join(lines),
        template="orange",
        action_rows=[
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "恢复推送并继续"},
                        "type": "primary",
                        "value": {
                            "action": "goal_apply_confirm",
                            "attach_binding": "true",
                            "objective": normalized_objective,
                            "status": normalized_status,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "保持 detached"},
                        "type": "default",
                        "value": {
                            "action": "goal_apply_confirm",
                            "attach_binding": "",
                            "objective": normalized_objective,
                            "status": normalized_status,
                        },
                    },
                ],
            }
        ],
    )


def _back_to_help_action() -> dict:
    return {
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "返回帮助"},
                "type": "default",
                "value": {
                    "action": "show_help_page",
                    "page": "overview",
                },
            }
        ],
    }


def build_execution_card(
    log_text: str,
    reply_segments: list[ExecutionReplySegment],
    *,
    running: bool = False,
    elapsed: int = 0,
    cancelled: bool = False,
) -> dict:
    """构造主执行卡片。"""
    if running:
        template = "turquoise"
        header_content = (
            f"Codex 执行过程（执行中 {elapsed}s）"
            if elapsed > 0
            else "Codex 执行过程（执行中）"
        )
    elif cancelled:
        template = "grey"
        header_content = "Codex 执行过程（已停止）"
    else:
        template = "blue"
        header_content = "Codex 执行过程"

    panel_icon = {
        "tag": "standard_icon",
        "token": "right-small-ccm_outlined",
        "size": "16px 16px",
    }

    def _panel(title: str, content: str, expanded: bool) -> dict:
        safe_content = sanitize_runtime_markdown_for_feishu_card(content)
        return {
            "tag": "collapsible_panel",
            "expanded": expanded,
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "icon": panel_icon,
                "icon_position": "left",
                "icon_expanded_angle": 90,
            },
            "elements": [{"tag": "markdown", "content": safe_content or ""}],
        }

    def _panel_with_elements(title: str, panel_elements: list[dict], expanded: bool) -> dict:
        return {
            "tag": "collapsible_panel",
            "expanded": expanded,
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "icon": panel_icon,
                "icon_position": "left",
                "icon_expanded_angle": 90,
            },
            "elements": panel_elements or [{"tag": "markdown", "content": ""}],
        }

    def _reply_panel_elements(segments: list[ExecutionReplySegment]) -> list[dict]:
        panel_elements: list[dict] = []
        remaining = _MAX_CARD_TABLES
        for segment in segments:
            if segment.kind == "divider":
                if panel_elements:
                    panel_elements.append({"tag": "hr"})
                continue
            text = segment.text
            if remaining > 0:
                text = limit_card_tables(text, remaining)
                remaining -= count_card_tables(text)
            panel_elements.append(
                {
                    "tag": "markdown",
                    "content": sanitize_runtime_markdown_for_feishu_card(text),
                }
            )
        return panel_elements

    elements: list[dict] = []
    reply_panel_elements = _reply_panel_elements(reply_segments)
    if log_text and reply_panel_elements:
        log_tables = count_card_tables(log_text)
        if log_tables > _MAX_CARD_TABLES:
            log_text = limit_card_tables(log_text, _MAX_CARD_TABLES)
        elements.append(_panel("执行过程", log_text, expanded=False))
        elements.append(_panel_with_elements("回复", reply_panel_elements, expanded=True))
    elif reply_panel_elements:
        elements.append(_panel_with_elements("回复", reply_panel_elements, expanded=True))
    elif log_text:
        elements.append(_panel("执行过程", limit_card_tables(log_text), expanded=False))
    else:
        elements.append(
            {
                "tag": "markdown",
                "content": "*暂无输出*" if running else "无",
            }
        )

    if running:
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "取消执行"},
                "type": "danger",
                "value": {"action": "cancel_turn"},
            }
        )

    return {
        "schema": "2.0",
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": header_content},
            "template": template,
        },
        "body": {"elements": elements},
    }


def build_command_approval_card(
    request_id: str,
    *,
    command: str,
    cwd: str = "",
    reason: str = "",
) -> dict:
    """构造命令审批卡片。"""
    cwd_display = display_path(cwd) if cwd else "-"
    content = [f"**工作目录**: `{cwd_display}`", "**命令**:", f"```bash\n{command or '(空命令)'}\n```"]
    if reason:
        content.append(f"**原因**: {reason}")

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 命令执行审批"},
            "template": "orange",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(content)},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "允许本次"},
                        "type": "primary",
                        "value": {
                            "action": "command_allow_once",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "允许本会话"},
                        "type": "default",
                        "value": {
                            "action": "command_allow_session",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "拒绝"},
                        "type": "danger",
                        "value": {
                            "action": "command_deny",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "中止本轮"},
                        "type": "danger",
                        "value": {
                            "action": "command_abort",
                            "request_id": request_id,
                        },
                    },
                ],
            },
        ],
    }


def build_file_change_approval_card(
    request_id: str,
    *,
    grant_root: str = "",
    reason: str = "",
) -> dict:
    """构造文件修改审批卡片。"""
    lines = []
    if grant_root:
        lines.append(f"**授权根目录**: `{display_path(grant_root)}`")
    else:
        lines.append("**授权范围**: 当前变更")
    if reason:
        lines.append(f"**原因**: {reason}")

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 文件修改审批"},
            "template": "orange",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(lines)},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "允许本次"},
                        "type": "primary",
                        "value": {
                            "action": "file_change_accept",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "允许本会话"},
                        "type": "default",
                        "value": {
                            "action": "file_change_accept_session",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "拒绝"},
                        "type": "danger",
                        "value": {
                            "action": "file_change_decline",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "中止本轮"},
                        "type": "danger",
                        "value": {
                            "action": "file_change_cancel",
                            "request_id": request_id,
                        },
                    },
                ],
            },
        ],
    }


def build_permissions_approval_card(
    request_id: str,
    *,
    permissions: dict,
    reason: str = "",
) -> dict:
    """构造额外权限审批卡片。"""
    fs_profile = permissions.get("fileSystem") or {}
    network_profile = permissions.get("network") or {}
    lines: list[str] = []

    read_paths = fs_profile.get("read") or []
    write_paths = fs_profile.get("write") or []
    if read_paths:
        lines.append("**新增读权限**:")
        lines.extend(f"- `{display_path(path)}`" for path in read_paths[:10])
    if write_paths:
        lines.append("**新增写权限**:")
        lines.extend(f"- `{display_path(path)}`" for path in write_paths[:10])
    if network_profile.get("enabled"):
        lines.append("**新增网络权限**: 已启用")
    if reason:
        lines.append(f"**原因**: {reason}")
    if not lines:
        lines.append("*未提供具体权限详情*")

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 额外权限审批"},
            "template": "orange",
        },
        "elements": [
            {"tag": "markdown", "content": "\n".join(lines)},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "允许本次"},
                        "type": "primary",
                        "value": {
                            "action": "permissions_allow_once",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "允许本会话"},
                        "type": "default",
                        "value": {
                            "action": "permissions_allow_session",
                            "request_id": request_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "拒绝"},
                        "type": "danger",
                        "value": {
                            "action": "permissions_deny",
                            "request_id": request_id,
                        },
                    },
                ],
            },
        ],
    }


def build_approval_handled_card(title: str, decision: str, detail: str = "") -> dict:
    """构造已处理审批卡片。"""
    content = f"已{decision}。"
    if detail:
        content = f"{content}\n{detail}"
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "grey",
        },
        "elements": [{"tag": "markdown", "content": content}],
    }


def build_approval_policy_card(current_policy: str, *, running: bool = False) -> dict:
    """构造原生审批策略选择卡片。"""
    labels = {
        "untrusted": "untrusted",
        "on-request": "on-request",
        "never": "never",
    }
    descs = {
        "untrusted": "偏保守，更多操作会先停下来等你确认。",
        "on-request": "仅在模型明确请求时，才停下来等你确认。",
        "never": "不请求审批，直接执行。",
    }

    current_label = labels.get(current_policy, current_policy or "（未设置）")
    current_desc = (
        "它只决定什么时候停下来等你确认，不改变文件或网络边界。\n"
        "多数情况下，优先使用 `/permissions`。\n"
        "作用范围：只影响当前飞书会话的后续 turn，不影响已打开的 `fcodex` TUI。"
    )
    if running:
        current_desc += "\n\n当前若有执行中的 turn，切换仅对下一轮生效。"

    buttons = []
    elements = [
        {
            "tag": "markdown",
            "content": f"当前审批策略：**{current_label}**\n{current_desc}",
        },
        {"tag": "hr"},
    ]
    for policy, label in labels.items():
        elements.append({"tag": "markdown", "content": f"**{label}**\n{descs[policy]}"})
        buttons.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": f"{'✓ ' if policy == current_policy else ''}{label}",
                },
                "type": "primary" if policy == current_policy else "default",
                "value": {
                    "action": "set_approval_policy",
                    "policy": policy,
                },
            }
        )
    elements.append({"tag": "action", "layout": "trisection", "actions": buttons})

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 审批策略"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_permissions_profile_card(
    current_permissions_profile_id: str,
    *,
    running: bool = False,
) -> dict:
    """构造权限基线选择卡片。"""
    current_choice = permissions_profile_choice_key(current_permissions_profile_id)
    current_label = permissions_profile_label(current_permissions_profile_id)
    current_desc = (
        "它只决定执行边界，不决定是否停下来审批。\n"
        "审批策略请单独使用 `/approval`。\n"
        "作用范围：只影响当前飞书会话的后续 turn，不影响已打开的 `fcodex` TUI。\n\n"
        f"Profile ID：`{current_permissions_profile_id or '（空）'}`"
    )
    if running:
        current_desc += "\n\n当前若有执行中的 turn，切换仅对下一轮生效。"

    buttons = []
    elements = [
        {
            "tag": "markdown",
            "content": f"当前权限基线：**{current_label}**\n{current_desc}",
        },
        {"tag": "hr"},
    ]
    for key, config in PERMISSION_PROFILE_CHOICES.items():
        elements.append(
            {
                "tag": "markdown",
                "content": f"**{config['label']}**\n{config['description']}",
            }
        )
        buttons.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": f"{'✓ ' if key == current_choice else ''}{config['label']}",
                },
                "type": "primary" if key == current_choice else "default",
                "value": {
                    "action": "set_permissions_profile",
                    "profile": key,
                },
            }
        )
    elements.append({"tag": "action", "layout": "trisection", "actions": buttons})
    elements.append(_back_to_help_action())

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 权限基线"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_model_effort_card(
    *,
    current_model: str,
    current_reasoning_effort: str,
    content: str,
    running: bool = False,
) -> dict:
    """构造 model / effort 联合运行时设置卡片。"""
    current_model_value = str(current_model or "").strip()
    current_effort_value = str(current_reasoning_effort or "").strip()
    elements = [
        {
            "tag": "markdown",
            "content": content,
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": (
                "**model override**\n"
                "输入任意非空 model 名称即可；如需回到默认解析结果，请点 `auto`。"
            ),
        },
        {
            "tag": "form",
            "name": "model_override_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "model_override",
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "输入 model 名称，例如 gpt-5.5 或 glm-4.5…",
                    },
                    "default_value": current_model_value,
                },
                {
                    "tag": "button",
                    "name": "submit_model_override",
                    "text": {"tag": "plain_text", "content": "保存 model"},
                    "type": "primary",
                    "form_action_type": "submit",
                    "value": {
                        "action": "submit_model_override",
                    },
                },
            ],
        },
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": f"{'✓ ' if not current_model_value else ''}auto",
                    },
                    "type": "primary" if not current_model_value else "default",
                    "value": {
                        "action": "set_model",
                        "model": "",
                    },
                }
            ],
        },
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": (
                "**effort override**\n"
                "`auto` 表示清除 override，先回到 thread profile effort；若 thread profile effort 也未设置，则回到 model default。`none` 表示显式不用 reasoning effort。"
            ),
        },
    ]
    effort_actions = [
        ("auto", ""),
        ("none", "none"),
        ("minimal", "minimal"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
    ]
    buttons = []
    for label, value in effort_actions:
        selected = (not current_effort_value and not value) or current_effort_value == value
        buttons.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": f"{'✓ ' if selected else ''}{label}",
                },
                "type": "primary" if selected else "default",
                "value": {
                    "action": "set_reasoning_effort",
                    "reasoning_effort": value,
                },
            }
        )
    for index in range(0, len(buttons), 3):
        row_actions = buttons[index:index + 3]
        row = {"tag": "action", "actions": row_actions}
        if len(row_actions) == 3:
            row["layout"] = "trisection"
        elements.append(row)
    if running:
        elements.append(
            {
                "tag": "markdown",
                "content": "当前若有执行中的 turn，切换仅对下一轮生效。",
            }
        )
    elements.append(_back_to_help_action())
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 模型 / Effort"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_collaboration_mode_card(current_mode: str, *, running: bool = False) -> dict:
    """构造协作模式选择卡片。"""
    labels = {
        "default": "default",
        "plan": "plan",
    }
    descs = {
        "default": "更接近直接执行。",
        "plan": "更容易先规划、提问，并展示计划卡片。",
    }

    current_desc = (
        f"{descs[current_mode]}\n"
        "如果你希望模型先澄清再动手，通常用 `plan`。\n"
        "作用范围：只影响当前飞书会话的后续 turn，不影响已打开的 `fcodex` TUI。"
    )
    if running:
        current_desc += "\n\n当前若有执行中的 turn，切换仅对下一轮生效。"

    elements = [
        {
            "tag": "markdown",
            "content": f"当前协作模式：**{labels[current_mode]}**\n{current_desc}",
        },
        {"tag": "hr"},
    ]
    buttons = []
    for mode, label in labels.items():
        elements.append({"tag": "markdown", "content": f"**{label}**\n{descs[mode]}"})
        buttons.append(
            {
                "tag": "button",
                "text": {
                    "tag": "plain_text",
                    "content": f"{'✓ ' if mode == current_mode else ''}{label}",
                },
                "type": "primary" if mode == current_mode else "default",
                "value": {
                    "action": "set_collaboration_mode",
                    "mode": mode,
                },
            }
        )
    elements.append({"tag": "action", "layout": "trisection", "actions": buttons})
    elements.append(_back_to_help_action())

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 协作模式"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_group_mode_card(current_mode: str, *, can_manage: bool) -> dict:
    """构造群聊工作态选择卡片。"""
    labels = {
        "assistant": "assistant",
        "all": "all",
        "mention_only": "mention-only",
    }
    descs = {
        "assistant": "缓存群聊消息，仅在有效 mention 时回复；适合群讨论助手。",
        "all": "群内消息都会直接触发机器人回复；风险最高，容易刷屏。",
        "mention_only": "只有有效 mention 的消息才会触发响应；不缓存上下文。",
    }
    current_desc = descs.get(current_mode, current_mode)
    content = (
        f"当前群聊工作态：**{labels.get(current_mode, current_mode)}**\n"
        f"{current_desc}\n\n"
        "作用范围：只影响当前群。\n\n"
        "在 `assistant` / `mention-only` 中，群命令本身也需要先显式 mention 触发对象。"
    )
    if not can_manage:
        content += "\n\n仅管理员可切换工作态。"

    elements = [{"tag": "markdown", "content": content}, {"tag": "hr"}]
    buttons = []
    for mode, label in labels.items():
        elements.append({"tag": "markdown", "content": f"**{label}**\n{descs[mode]}"})
        if can_manage:
            buttons.append(
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": label,
                    },
                    "type": "primary" if mode == current_mode else "default",
                    "value": {
                        "action": "set_group_mode",
                        "mode": mode,
                    },
                }
            )
    if buttons:
        elements.append({"tag": "action", "layout": "trisection", "actions": buttons})
    elements.append(_back_to_help_action())

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 群聊工作态"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_group_activation_card(
    *,
    activated: bool,
    activated_by: str = "",
    activated_at: int = 0,
    can_manage: bool,
) -> dict:
    """构造 owner-activated 群聊状态卡片。"""
    state_label = "已激活" if activated else "未激活"
    template = "green" if activated else "yellow"
    lines = [f"当前群聊状态：**{state_label}**"]
    if activated:
        if activated_by:
            lines.append(f"激活管理员：`{activated_by}`")
        if activated_at > 0:
            lines.append(f"激活时间：`{_format_ts_ms(activated_at)}`")
        lines.extend(
            [
                "",
                "当前群成员可直接在这里日常对话，并处理自己发起 turn 的审批或补充输入。",
                "所有会改变共享状态的命令与设置，仍然只允许管理员操作。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "当前群聊还没有被管理员初始化。",
                "非管理员暂时不能使用机器人；请让管理员执行 `/group activate`。",
            ]
        )
    if can_manage:
        lines.extend(
            [
                "",
                "管理员可用：`/group activate`、`/group deactivate`。",
            ]
        )
    else:
        lines.extend(["", "仅管理员可激活或停用当前群聊。"])

    elements = [{"tag": "markdown", "content": "\n".join(lines)}, {"tag": "hr"}]
    if can_manage:
        elements.append(
            {
                "tag": "action",
                "layout": "bisected",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "激活当前群"},
                        "type": "primary" if activated else "default",
                        "value": {
                            "action": "set_group_activation",
                            "activated": True,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "停用当前群"},
                        "type": "danger" if activated else "default",
                        "value": {
                            "action": "set_group_activation",
                            "activated": False,
                        },
                    },
                ],
            }
        )

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 群聊授权"},
            "template": template,
        },
        "elements": elements,
    }

def build_ask_user_card(
    request_id: str,
    questions: list[dict],
    answers: dict[str, str] | None = None,
) -> dict:
    """构造 requestUserInput 卡片。"""
    answers = answers or {}
    elements: list[dict] = []

    pending_ids = [q.get("id", "") for q in questions if q.get("id", "") not in answers]
    current_id = pending_ids[0] if pending_ids else ""

    for index, question in enumerate(questions, start=1):
        qid = question.get("id", "")
        header = question.get("header") or f"问题 {index}"
        question_text = question.get("question", "")
        options = question.get("options") or []
        allow_custom = bool(question.get("isOther", False)) or not options
        is_secret = bool(question.get("isSecret", False))

        if qid in answers:
            answer_text = "（已提交隐藏内容）" if is_secret else answers[qid]
            elements.append(
                {
                    "tag": "markdown",
                    "content": f"**{header}**\n~~已回答：{answer_text}~~",
                }
            )
            elements.append({"tag": "hr"})
            continue

        if qid != current_id:
            elements.append({"tag": "markdown", "content": f"**{header}**\n*待回答*"})
            elements.append({"tag": "hr"})
            continue

        elements.append(
            {
                "tag": "markdown",
                "content": f"**{header}**\n\n{question_text}",
            }
        )

        if options:
            option_lines = []
            for opt in options:
                label = opt.get("label", "")
                desc = opt.get("description", "")
                option_lines.append(f"**{label}**: {desc}" if desc else f"**{label}**")
            elements.append({"tag": "markdown", "content": "\n".join(option_lines)})
            elements.append({"tag": "hr"})
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": opt.get("label", "选项")},
                            "type": "primary" if idx == 0 else "default",
                            "value": {
                                "action": "answer_user_input_option",
                                "request_id": request_id,
                                "question_id": qid,
                                "answer": opt.get("label", ""),
                            },
                        }
                        for idx, opt in enumerate(options)
                    ],
                }
            )

        if allow_custom:
            elements.append(
                {
                    "tag": "form",
                    "name": f"user_input_form_{qid}",
                    "elements": [
                        {
                            "tag": "input",
                            "name": f"user_input_{qid}",
                            "placeholder": {
                                "tag": "plain_text",
                                "content": "输入自定义回答…",
                            },
                        },
                        {
                            "tag": "button",
                            "name": f"submit_{qid}",
                            "text": {"tag": "plain_text", "content": "提交"},
                            "type": "default",
                            "form_action_type": "submit",
                            "value": {
                                "action": "answer_user_input_custom",
                                "request_id": request_id,
                                "question_id": qid,
                            },
                        },
                    ],
                }
            )

        if is_secret and allow_custom:
            elements.append(
                {
                    "tag": "markdown",
                    "content": "*注意：飞书卡片输入框本身不是保密控件，敏感信息请谨慎输入。*",
                }
            )

        elements.append({"tag": "hr"})

    pending_count = len(pending_ids)
    title = "Codex 需要你的输入" if pending_count <= 1 else f"Codex 需要你的输入（剩余 {pending_count} 题）"

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "elements": elements or [{"tag": "markdown", "content": "已全部回答。"}],
    }


def build_ask_user_answered_card(
    questions: list[dict],
    answers: dict[str, str],
) -> dict:
    """构造问答已完成卡片。"""
    lines = []
    for question in questions:
        qid = question.get("id", "")
        header = question.get("header") or qid or "问题"
        answer = answers.get(qid, "（未回答）")
        if question.get("isSecret", False) and qid in answers:
            answer = "（已提交隐藏内容）"
        lines.append(f"**{header}**\n{answer}")

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 用户输入 - 已提交"},
            "template": "grey",
        },
        "elements": [{"tag": "markdown", "content": "\n\n".join(lines) or "已提交。"}],
    }


def build_thread_row(thread: dict, current_thread_id: str) -> list[dict]:
    """构造单个线程行。"""
    thread_id = thread["thread_id"]
    current = thread_id == current_thread_id
    title = thread.get("title", "（无标题）")

    summary_parts = [f"**{thread_id[:8]}…**", f"`{display_path(thread.get('cwd', ''))}`"]
    if thread.get("model_provider"):
        summary_parts.append(f"`{thread['model_provider']}`")
    summary_parts.append(format_timestamp(thread.get("updated_at")))
    line = " | ".join(summary_parts) + f"\n{shorten(title, 120)}"

    return [
        {"tag": "markdown", "content": line},
        {
            "tag": "action",
            "layout": "trisection",
            "actions": [
                {
                    "tag": "button",
                    "text": {
                        "tag": "plain_text",
                        "content": "当前" if current else "恢复",
                    },
                    "type": "primary" if current else "default",
                    "value": {
                        "action": "resume_thread",
                        "thread_id": thread_id,
                        "thread_title": title,
                    },
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "归档"},
                    "type": "default",
                    "value": {
                        "action": "archive_thread",
                        "thread_id": thread_id,
                    },
                },
            ],
        },
        {"tag": "hr"},
    ]


def build_threads_card(
    threads: list[dict],
    current_thread_id: str,
    working_dir: str,
    total_count: int,
    *,
    shown_count: int = 0,
    expanded: bool = False,
) -> dict:
    """构造线程列表卡片。"""
    working_dir_display = display_path(working_dir) or working_dir or "."

    elements: list[dict] = [
        {
            "tag": "markdown",
            "content": (
                f"当前目录：`{working_dir_display}`\n"
                "已按当前目录跨 provider 汇总显示线程。\n"
                f"按最近更新时间排序，共 {total_count} 个线程。\n"
                f"想恢复其他目录的线程，或按名字做全局精确查找，请用 `{_SHARED_RESUME_COMMAND.feishu_usage}`。\n"
                f"如需在本地继续同一线程，请用 `{_LOCAL_RESUME_COMMAND}`；"
                f"本地查看线程请用 `{_LOCAL_THREAD_LIST_CWD}`。"
            ),
        },
        {"tag": "hr"},
    ]

    if expanded or total_count <= shown_count:
        display_threads = threads
    else:
        display_threads = threads[:shown_count]

    for thread in display_threads:
        elements.extend(build_thread_row(thread, current_thread_id))

    if not threads:
        elements.append({"tag": "markdown", "content": "*当前目录下暂无可恢复线程。*"})

    bottom_actions: list[dict] = []
    if not expanded and total_count > shown_count and threads:
        bottom_actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "更多"},
                "type": "default",
                "value": {
                    "action": "show_more_threads",
                },
            }
        )
    bottom_actions.append(
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "收起"},
            "type": "default",
            "value": {
                "action": "close_threads_card",
            },
        }
    )
    elements.append({"tag": "action", "actions": bottom_actions})

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 当前目录线程"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_threads_closed_card() -> dict:
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 当前目录线程（已收起）"},
            "template": "grey",
        },
        "elements": [
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "展开线程列表"},
                        "type": "primary",
                        "value": {
                            "action": "reopen_threads_card",
                        },
                    }
                ],
            },
        ],
    }


def build_threads_pending_card(thread_id: str, *, title: str) -> dict:
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "Codex 当前目录线程"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"正在恢复线程：`{thread_id[:8]}…` {shorten(title or '（无标题）', 120)}\n"
                    "完成后会自动刷新当前线程列表。"
                ),
            }
        ],
    }


def build_rename_card(session: dict) -> dict:
    """构造重命名卡片。"""
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": "重命名线程"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": (
                    f"**{session['thread_id'][:8]}…** | `{display_path(session.get('cwd', ''))}`\n"
                    f"当前标题：{session.get('title', '（无标题）')}"
                ),
            },
            {"tag": "hr"},
            {
                "tag": "form",
                "name": "rename_thread_form",
                "elements": [
                    {
                        "tag": "input",
                        "name": "rename_title",
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "输入新标题…",
                        },
                        "default_value": session.get("title", ""),
                    },
                    {
                        "tag": "button",
                        "name": "submit_rename",
                        "text": {"tag": "plain_text", "content": "确认"},
                        "type": "primary",
                        "form_action_type": "submit",
                        "value": {
                            "action": "rename_thread",
                            "thread_id": session["thread_id"],
                        },
                    },
                ],
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "取消"},
                        "type": "default",
                        "value": {
                            "action": "cancel_rename",
                        },
                    }
                ],
            },
        ],
    }


def build_history_preview_card(
    thread_id: str,
    rounds: list[tuple[str, str]],
    *,
    summary: str = "",
) -> dict:
    """构造历史预览卡片。"""
    elements: list[dict] = []
    if summary:
        elements.append({"tag": "markdown", "content": summary})
        elements.append({"tag": "hr"})
    for user_text, assistant_text in rounds:
        elements.append({"tag": "markdown", "content": f"👤 **你**\n{shorten(user_text, _HISTORY_TEXT_MAX)}"})
        elements.append({"tag": "markdown", "content": f"🤖 **Codex**\n{shorten(assistant_text, _HISTORY_TEXT_MAX)}"})
        elements.append({"tag": "hr"})

    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": f"线程 {thread_id[:8]}… 最近对话"},
            "template": "green",
        },
        "elements": elements or [{"tag": "markdown", "content": "*暂无可展示历史。*"}],
    }


def build_plan_card(
    turn_id: str,
    *,
    explanation: str = "",
    plan_steps: list[dict] | None = None,
    plan_text: str = "",
) -> dict:
    """构造计划卡片。"""
    plan_steps = plan_steps or []
    elements: list[dict] = []

    if explanation:
        elements.append(
            {
                "tag": "markdown",
                "content": sanitize_runtime_markdown_for_feishu_card(
                    f"**说明**\n{shorten(explanation, _PLAN_CONTENT_MAX)}"
                ),
            }
        )
        elements.append({"tag": "hr"})

    if plan_steps:
        status_labels = {
            "pending": "[ ]",
            "inProgress": "[~]",
            "completed": "[x]",
        }
        lines = [
            f"{status_labels.get(step.get('status', ''), '[ ]')} {shorten(step.get('step', ''), 240)}"
            for step in plan_steps
            if step.get("step")
        ]
        if lines:
            elements.append(
                {
                    "tag": "markdown",
                    "content": sanitize_runtime_markdown_for_feishu_card("**计划步骤**\n" + "\n".join(lines)),
                }
            )
            elements.append({"tag": "hr"})

    if plan_text:
        elements.append(
            {
                "tag": "markdown",
                "content": sanitize_runtime_markdown_for_feishu_card(
                    f"**计划正文**\n{shorten(plan_text, _PLAN_CONTENT_MAX)}"
                ),
            }
        )

    if not elements:
        elements.append({"tag": "markdown", "content": "*暂未收到可展示的计划内容。*"})

    title = f"Codex 计划 {turn_id[:8]}…" if turn_id else "Codex 计划"
    return {
        "config": _card_config(),
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "green",
        },
        "elements": elements,
    }
