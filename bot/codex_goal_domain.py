from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTriggerResponse,
)

from bot.adapters.base import ThreadGoalSummary
from bot.cards import (
    CommandResult,
    build_goal_card,
    build_goal_detached_confirm_card,
    build_markdown_card,
    make_card_response,
)
from bot.runtime_state import FEISHU_RUNTIME_DETACHED
from bot.runtime_view import RuntimeView

_GOAL_USAGE = (
    "用法：`/goal`\n"
    "别名：`/goal show`\n"
    "设置：`/goal set <objective>`\n"
    "暂停：`/goal pause`\n"
    "恢复：`/goal resume`\n"
    "清除：`/goal clear`"
)


@dataclass(frozen=True, slots=True)
class GoalDomainPorts:
    get_runtime_view: Callable[[str, str, str], RuntimeView]
    get_thread_goal: Callable[[str], ThreadGoalSummary | None]
    set_thread_goal: Callable[..., ThreadGoalSummary]
    clear_thread_goal: Callable[[str], bool]
    attach_current_binding: Callable[[str, str, str], None]
    update_runtime_goal_projection: Callable[[str, str, str, ThreadGoalSummary | None], None]


class CodexGoalDomain:
    def __init__(self, *, ports: GoalDomainPorts) -> None:
        self._ports = ports

    def handle_goal_command(
        self,
        sender_id: str,
        chat_id: str,
        arg: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        normalized = str(arg or "").strip()
        if not normalized:
            return self._show_goal(sender_id, chat_id, message_id=message_id)
        subcommand, _, tail = normalized.partition(" ")
        subcommand = subcommand.strip().lower()
        payload = tail.strip()
        try:
            if subcommand == "show":
                if payload:
                    return CommandResult(text=_GOAL_USAGE)
                return self._show_goal(sender_id, chat_id, message_id=message_id)
            if subcommand == "set":
                if not payload:
                    return CommandResult(text=_GOAL_USAGE)
                return self._set_goal(sender_id, chat_id, payload, message_id=message_id)
            if subcommand == "pause":
                if payload:
                    return CommandResult(text=_GOAL_USAGE)
                return self._update_goal_status(sender_id, chat_id, "paused", message_id=message_id)
            if subcommand == "resume":
                if payload:
                    return CommandResult(text=_GOAL_USAGE)
                return self._update_goal_status(sender_id, chat_id, "active", message_id=message_id)
            if subcommand == "clear":
                if payload:
                    return CommandResult(text=_GOAL_USAGE)
                return self._clear_goal(sender_id, chat_id, message_id=message_id)
        except Exception as exc:
            return CommandResult(
                card=build_markdown_card("Codex Goal 操作失败", str(exc) or "goal 操作失败", template="red")
            )
        return CommandResult(text=_GOAL_USAGE)

    def handle_goal_action(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict[str, str],
    ) -> P2CardActionTriggerResponse:
        action = str(action_value.get("action", "") or "").strip()
        try:
            if action == "goal_refresh":
                result = self._show_goal(sender_id, chat_id, message_id=message_id)
                return make_card_response(card=result.card)
            if action == "goal_pause":
                result = self._update_goal_status(sender_id, chat_id, "paused", message_id=message_id)
                return make_card_response(card=result.card, toast="已暂停 goal。", toast_type="success")
            if action == "goal_resume":
                confirm_card = self._build_detached_goal_confirm_card(
                    sender_id,
                    chat_id,
                    objective="",
                    status="active",
                    message_id=message_id,
                )
                if confirm_card is not None:
                    return make_card_response(card=confirm_card)
                result = self._update_goal_status_direct(sender_id, chat_id, "active", message_id=message_id)
                return make_card_response(card=result.card, toast="已恢复 goal。", toast_type="success")
            if action == "goal_clear":
                result = self._clear_goal(sender_id, chat_id, message_id=message_id)
                return make_card_response(card=result.card, toast="已清除 goal。", toast_type="success")
            if action == "goal_apply_confirm":
                result, toast = self._apply_goal_confirmed(
                    sender_id,
                    chat_id,
                    objective=str(action_value.get("objective", "") or "").strip(),
                    status=str(action_value.get("status", "") or "").strip(),
                    attach_binding=str(action_value.get("attach_binding", "") or "").strip().lower() == "true",
                    message_id=message_id,
                )
                return make_card_response(card=result.card, toast=toast, toast_type="success")
        except Exception as exc:
            return make_card_response(toast=str(exc) or "goal 操作失败", toast_type="warning")
        return P2CardActionTriggerResponse()

    def _current_thread(self, sender_id: str, chat_id: str, *, message_id: str = "") -> tuple[str, str]:
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        thread_id = runtime.current_thread_id.strip()
        if not thread_id:
            raise ValueError("当前没有绑定 thread；请先直接发送消息、执行 `/new`，或 `/resume` 目标线程。")
        return thread_id, runtime.current_thread_title.strip()

    def _project_goal(
        self,
        sender_id: str,
        chat_id: str,
        goal: ThreadGoalSummary | None,
        *,
        message_id: str = "",
    ) -> None:
        self._ports.update_runtime_goal_projection(sender_id, chat_id, message_id, goal)

    def _show_goal(self, sender_id: str, chat_id: str, *, message_id: str = "") -> CommandResult:
        thread_id, thread_title = self._current_thread(sender_id, chat_id, message_id=message_id)
        goal = self._ports.get_thread_goal(thread_id)
        self._project_goal(sender_id, chat_id, goal, message_id=message_id)
        return CommandResult(card=build_goal_card(thread_id=thread_id, thread_title=thread_title, goal=goal))

    def _set_goal(
        self,
        sender_id: str,
        chat_id: str,
        objective: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        confirm_card = self._build_detached_goal_confirm_card(
            sender_id,
            chat_id,
            objective=objective,
            status="",
            message_id=message_id,
        )
        if confirm_card is not None:
            return CommandResult(card=confirm_card)
        return self._set_goal_direct(sender_id, chat_id, objective, message_id=message_id)

    def _update_goal_status(
        self,
        sender_id: str,
        chat_id: str,
        status: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        confirm_card = self._build_detached_goal_confirm_card(
            sender_id,
            chat_id,
            objective="",
            status=status,
            message_id=message_id,
        )
        if confirm_card is not None:
            return CommandResult(card=confirm_card)
        return self._update_goal_status_direct(sender_id, chat_id, status, message_id=message_id)

    def _clear_goal(self, sender_id: str, chat_id: str, *, message_id: str = "") -> CommandResult:
        thread_id, thread_title = self._current_thread(sender_id, chat_id, message_id=message_id)
        cleared = self._ports.clear_thread_goal(thread_id)
        self._project_goal(sender_id, chat_id, None, message_id=message_id)
        notice = "已清除当前 thread goal。" if cleared else "当前 thread 原本就没有 goal。"
        return CommandResult(
            card=build_goal_card(
                thread_id=thread_id,
                thread_title=thread_title,
                goal=None,
                notice=notice,
            )
        )

    def _build_detached_goal_confirm_card(
        self,
        sender_id: str,
        chat_id: str,
        *,
        objective: str,
        status: str,
        message_id: str = "",
    ) -> dict | None:
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        thread_id = runtime.current_thread_id.strip()
        if not thread_id or runtime.binding.feishu_runtime_state != FEISHU_RUNTIME_DETACHED:
            return None
        return build_goal_detached_confirm_card(
            thread_id=thread_id,
            thread_title=runtime.current_thread_title.strip(),
            objective=objective,
            status=status,
        )

    def _apply_goal_confirmed(
        self,
        sender_id: str,
        chat_id: str,
        *,
        objective: str,
        status: str,
        attach_binding: bool,
        message_id: str = "",
    ) -> tuple[CommandResult, str]:
        normalized_objective = str(objective or "").strip()
        normalized_status = str(status or "").strip()
        if attach_binding:
            self._ports.attach_current_binding(sender_id, chat_id, message_id)
        if normalized_objective:
            result = self._set_goal_direct(
                sender_id,
                chat_id,
                normalized_objective,
                message_id=message_id,
                attached_notice=attach_binding,
            )
            return result, "已更新 goal 并恢复当前会话推送。" if attach_binding else "已更新 goal，保持 detached。"
        if normalized_status:
            result = self._update_goal_status_direct(
                sender_id,
                chat_id,
                normalized_status,
                message_id=message_id,
                attached_notice=attach_binding,
            )
            if normalized_status == "active":
                return result, "已恢复 goal 并恢复当前会话推送。" if attach_binding else "已恢复 goal，保持 detached。"
            return result, "已更新 goal 并恢复当前会话推送。" if attach_binding else "已更新 goal，保持 detached。"
        raise ValueError("goal 变更缺少 objective 或 status。")

    def _set_goal_direct(
        self,
        sender_id: str,
        chat_id: str,
        objective: str,
        *,
        message_id: str = "",
        attached_notice: bool = False,
    ) -> CommandResult:
        thread_id, thread_title = self._current_thread(sender_id, chat_id, message_id=message_id)
        goal = self._ports.set_thread_goal(thread_id, objective=objective)
        self._project_goal(sender_id, chat_id, goal, message_id=message_id)
        notice = "已设置当前 thread goal。"
        if attached_notice:
            notice += "\n当前会话已恢复接收该 thread 的飞书推送。"
        return CommandResult(
            card=build_goal_card(
                thread_id=thread_id,
                thread_title=thread_title,
                goal=goal,
                notice=notice,
            )
        )

    def _update_goal_status_direct(
        self,
        sender_id: str,
        chat_id: str,
        status: str,
        *,
        message_id: str = "",
        attached_notice: bool = False,
    ) -> CommandResult:
        thread_id, thread_title = self._current_thread(sender_id, chat_id, message_id=message_id)
        goal = self._ports.set_thread_goal(thread_id, status=status)
        self._project_goal(sender_id, chat_id, goal, message_id=message_id)
        notice = "已暂停当前 thread goal。" if status == "paused" else "已恢复当前 thread goal。"
        if attached_notice:
            notice += "\n当前会话已恢复接收该 thread 的飞书推送。"
        return CommandResult(
            card=build_goal_card(
                thread_id=thread_id,
                thread_title=thread_title,
                goal=goal,
                notice=notice,
            )
        )
