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
    build_markdown_card,
    make_card_response,
)
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
                result = self._update_goal_status(sender_id, chat_id, "active", message_id=message_id)
                return make_card_response(card=result.card, toast="已恢复 goal。", toast_type="success")
            if action == "goal_clear":
                result = self._clear_goal(sender_id, chat_id, message_id=message_id)
                return make_card_response(card=result.card, toast="已清除 goal。", toast_type="success")
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
        thread_id, thread_title = self._current_thread(sender_id, chat_id, message_id=message_id)
        goal = self._ports.set_thread_goal(thread_id, objective=objective)
        self._project_goal(sender_id, chat_id, goal, message_id=message_id)
        return CommandResult(
            card=build_goal_card(
                thread_id=thread_id,
                thread_title=thread_title,
                goal=goal,
                notice="已设置当前 thread goal。",
            )
        )

    def _update_goal_status(
        self,
        sender_id: str,
        chat_id: str,
        status: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        thread_id, thread_title = self._current_thread(sender_id, chat_id, message_id=message_id)
        goal = self._ports.set_thread_goal(thread_id, status=status)
        self._project_goal(sender_id, chat_id, goal, message_id=message_id)
        notice = "已暂停当前 thread goal。" if status == "paused" else "已恢复当前 thread goal。"
        return CommandResult(
            card=build_goal_card(
                thread_id=thread_id,
                thread_title=thread_title,
                goal=goal,
                notice=notice,
            )
        )

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
