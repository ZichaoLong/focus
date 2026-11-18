"""Feishu presentation for runtime administration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        P2CardActionTriggerResponse,
    )

from bot.backend_reset.contract import (
    BackendResetResultContractError,
    decode_backend_reset_force,
    decode_backend_reset_result,
)
from bot.backend_reset.diagnostics import BackendResetDiagnosticsPorts
from bot.backend_reset.presenter import BackendResetPresenter
from bot.binding_identity import format_binding_id
from bot.cards import (
    CommandResult,
    build_markdown_card,
    format_goal_summary_markdown,
    make_card_response,
)
from bot.constants import display_path
from bot.runtime_state import (
    FEISHU_RUNTIME_DETACHED,
)
from bot.runtime_admin.application import (
    ChatBindingKey,
    RuntimeAdminApplication,
    RuntimeAdminPorts,
)

logger = logging.getLogger(__name__)


class RuntimeAdminController(RuntimeAdminApplication):
    def __init__(self, *, ports: RuntimeAdminPorts, **kwargs) -> None:
        if ports.presentation is None:
            raise ValueError("Feishu runtime admin requires presentation capabilities")
        super().__init__(ports=ports, **kwargs)
        self._permissions_summary = ports.presentation.permissions_summary
        self._reply_text = ports.presentation.reply_text
        self._reply_card = ports.presentation.reply_card
        self._backend_reset_presenter = BackendResetPresenter(
            BackendResetDiagnosticsPorts(
                instance_name=self._instance_name,
                format_binding_ids=self._format_binding_ids,
                short_thread_ids=self._short_thread_ids,
            )
        )

    def _render_permissions_summary(self, snapshot: dict[str, Any]) -> str:
        try:
            return self._permissions_summary(snapshot["permissions_profile_id"])
        except TypeError:
            return self._permissions_summary(
                snapshot.get("approval_policy", ""),
                snapshot.get("permissions_profile_id", ""),
            )

    def render_binding_status_markdown(
        self,
        snapshot: dict[str, Any],
        *,
        include_profile_lines: bool,
    ) -> tuple[str, str]:
        thread_id = snapshot["thread_id"]
        if thread_id:
            thread_line = f"当前线程：`{thread_id[:8]}…` {snapshot['thread_title'] or '（无标题）'}"
        else:
            thread_line = "当前线程：-"
        lines = [
            f"目录：`{display_path(snapshot['working_dir'])}`",
            thread_line,
        ]
        lines.extend(
            format_goal_summary_markdown(
                objective=str(snapshot.get("goal_objective", "") or ""),
                status=str(snapshot.get("goal_status", "") or ""),
                token_budget=snapshot.get("goal_token_budget"),
                tokens_used=int(snapshot.get("goal_tokens_used") or 0),
                time_used_seconds=int(snapshot.get("goal_time_used_seconds") or 0),
            )
        )
        if include_profile_lines:
            lines.extend(
                [
                    f"权限基线：`{self._render_permissions_summary(snapshot)}`",
                    f"审批策略：`{snapshot['approval_policy']}`",
                    f"Codex model override：`{snapshot['model'] or 'auto'}`",
                    f"Codex effort override：`{snapshot.get('reasoning_effort', '') or 'auto'}`",
                ]
            )
        operator_status = snapshot.get("operator_status")
        if isinstance(operator_status, dict):
            warnings = operator_status.get("warnings")
            warning_count = len(warnings) if isinstance(warnings, list) else 0
            lines.append(
                f"运行健康：`{str(operator_status.get('status', 'unknown') or 'unknown')}`"
                f"；当前进程告警：`{warning_count}`"
            )
        template = "turquoise" if snapshot["running_turn"] else "blue"
        return "\n".join(lines), template

    def handle_status_command(self, binding: ChatBindingKey) -> CommandResult:
        snapshot = self.binding_status_snapshot(binding)
        content, template = self.render_binding_status_markdown(
            snapshot, include_profile_lines=True
        )
        return CommandResult(
            card=build_markdown_card("Codex 当前状态", content, template=template)
        )

    @staticmethod
    def _next_prompt_preflight_line(snapshot: dict[str, Any]) -> str:
        if not snapshot["next_prompt_allowed"]:
            return (
                "下一条普通消息："
                f"`blocked` (`{snapshot['next_prompt_reason_code']}`) {snapshot['next_prompt_reason']}"
            )
        if not str(snapshot.get("thread_id") or "").strip():
            return "下一条普通消息：`accepted`，会在当前目录新建 thread 后启动 turn。"
        if snapshot["feishu_runtime_state"] == FEISHU_RUNTIME_DETACHED:
            return "下一条普通消息：`accepted`，会先按当前 binding 重新 attach / resume，再启动 turn。"
        return "下一条普通消息：`accepted`，会写入当前绑定 thread。"

    @staticmethod
    def _detach_preflight_line(snapshot: dict[str, Any]) -> str:
        if not snapshot["thread_id"]:
            return "detach：`not-applicable`，当前没有绑定 thread。"
        if snapshot["detach_available"]:
            return "detach：`available`"
        return (
            "detach："
            f"`blocked` (`{snapshot['detach_reason_code']}`) "
            f"{snapshot['detach_reason']}"
        )

    def render_binding_preflight_markdown(
        self,
        snapshot: dict[str, Any],
        *,
        include_profile_lines: bool,
    ) -> tuple[str, str]:
        thread_id = str(snapshot["thread_id"] or "").strip()
        if thread_id:
            thread_line = f"当前线程：`{thread_id[:8]}…` {snapshot['thread_title'] or '（无标题）'}"
        else:
            thread_line = "当前线程：-"
        lines = [
            "作用对象：当前 chat binding；这是 dry-run，不会启动 turn，也不会改变 binding。",
            f"目录：`{display_path(snapshot['working_dir'])}`",
            thread_line,
            f"binding：`{snapshot['binding_state']}`",
            f"飞书推送：`{snapshot['feishu_runtime_state']}`",
            f"backend thread status：`{snapshot['backend_thread_status']}`",
            "",
            self._next_prompt_preflight_line(snapshot),
            self._detach_preflight_line(snapshot),
        ]
        if include_profile_lines:
            lines.extend(
                [
                    "",
                    f"权限基线：`{self._render_permissions_summary(snapshot)}`",
                    f"审批策略：`{snapshot['approval_policy']}`",
                    f"model override：`{snapshot['model'] or 'auto'}`",
                    f"effort override：`{snapshot.get('reasoning_effort', '') or 'auto'}`",
                ]
            )
        if thread_id and snapshot["feishu_runtime_state"] == FEISHU_RUNTIME_DETACHED:
            lines.extend(
                [
                    "",
                    "说明：`detached` 状态下，只有 preflight accepted 才允许重新 attach；blocked 必须保持 pure reject。",
                ]
            )
        template = "green" if snapshot["next_prompt_allowed"] else "yellow"
        return "\n".join(lines), template

    def handle_preflight_command(
        self, binding: ChatBindingKey, arg: str
    ) -> CommandResult:
        if str(arg or "").strip():
            return CommandResult(text="用法：`/preflight`")
        snapshot = self.binding_status_snapshot(binding)
        content, template = self.render_binding_preflight_markdown(
            snapshot, include_profile_lines=True
        )
        return CommandResult(
            card=build_markdown_card("Codex Preflight", content, template=template)
        )

    @staticmethod
    def _format_blocked_attach_entries(items: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for item in items:
            thread_id = str(item.get("thread_id", "") or "").strip()
            binding_ids = [
                str(value or "").strip()
                for value in (item.get("binding_ids") or [])
                if str(value or "").strip()
            ]
            reason = str(item.get("reason", "") or "").strip() or "（无原因）"
            label = f"`{thread_id[:8]}…`" if thread_id else "（未知 thread）"
            if binding_ids:
                label += " " + ", ".join(
                    f"`{binding_id}`" for binding_id in binding_ids
                )
            lines.append(f"- {label}: {reason}")
        return lines

    def handle_reset_backend_command(self, arg: str) -> CommandResult:
        if str(arg or "").strip():
            return CommandResult(text="用法：`/reset-backend`")
        preview = self.backend_reset_preview()
        return CommandResult(
            card=self._backend_reset_presenter.build_preview_card(preview)
        )

    def handle_reset_backend_action(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict[str, Any],
    ) -> P2CardActionTriggerResponse:
        try:
            force = decode_backend_reset_force(action_value)
        except ValueError as exc:
            return make_card_response(
                toast=str(exc),
                toast_type="warning",
            )
        binding = self._binding_application.effective_binding_key(
            sender_id,
            chat_id,
        )
        current_thread_id = ""
        try:
            snapshot = self.binding_status_snapshot(binding)
        except ValueError:
            snapshot = {}
        current_thread_id = str(snapshot.get("thread_id", "") or "").strip()
        try:
            raw_result = self._reset_current_instance_backend(force)
        except Exception as exc:
            preview = self.backend_reset_preview()
            return make_card_response(
                card=self._backend_reset_presenter.build_preview_card(
                    preview,
                    leading_lines=[f"reset backend 失败：{exc}", ""],
                ),
                toast=str(exc) or "reset backend 失败",
                toast_type="warning",
            )
        try:
            result = decode_backend_reset_result(
                raw_result,
                expected_force=force,
            )
        except BackendResetResultContractError as exc:
            logger.error("backend reset returned an invalid result: %s", exc)
            return make_card_response(
                card=self._backend_reset_presenter.build_outcome_unknown_card(),
                toast="backend 可能已重置，但结果未知；请勿立即重复操作。",
                toast_type="warning",
            )
        return make_card_response(
            card=self._backend_reset_presenter.build_result_card(
                result,
                current_thread_id=current_thread_id,
            ),
            toast="已重置当前实例 backend。",
            toast_type="success",
        )

    def _build_thread_attach_result_card(self, result: dict[str, Any]) -> dict:
        lines = [
            f"线程：`{result['thread_id'][:8]}…` {result.get('thread_title', '') or '（无标题）'}",
            f"目录：`{display_path(str(result.get('working_dir', '') or ''))}`",
            f"已附着 binding：{self._format_binding_ids(result.get('attached_binding_ids') or [])}",
        ]
        if result.get("already_attached_binding_ids"):
            lines.append(
                f"原本已附着：{self._format_binding_ids(result.get('already_attached_binding_ids') or [])}"
            )
        if result.get("active_observer_binding_ids"):
            lines.append(
                "说明：已在 active turn 中途接入；从现在起接收后续进展与终态，"
                "此前过程可能不完整，且当前 turn 不授予飞书取消或审批权限。"
            )
        if not result.get("changed"):
            lines.append(
                "说明：当前 thread 相关 binding 原本就没有需要恢复的 detached 推送。"
            )
        return build_markdown_card(
            "Codex 已附着飞书推送", "\n".join(lines), template="green"
        )

    def _build_service_attach_result_card(self, result: dict[str, Any]) -> dict:
        lines = [
            f"当前实例：`{result.get('instance_name') or self._instance_name()}`",
            f"已附着 threads：{self._short_thread_ids(result.get('attached_thread_ids') or [])}",
            f"已附着 bindings：{self._format_binding_ids(result.get('attached_binding_ids') or [])}",
        ]
        if result.get("already_attached_thread_ids"):
            lines.append(
                f"原本已附着 threads：{self._short_thread_ids(result.get('already_attached_thread_ids') or [])}"
            )
        if result.get("active_observer_thread_ids"):
            lines.append(
                "说明：部分 thread 已作为 active observer 中途接入；"
                "此前过程可能不完整，且不取得当前 turn 的取消或审批权限。"
            )
        blocked_threads = result.get("blocked_threads") or []
        template = "green"
        if blocked_threads:
            template = "yellow"
            lines.extend(["", "**未恢复项**"])
            lines.extend(self._format_blocked_attach_entries(blocked_threads))
        elif not result.get("attached_binding_ids"):
            lines.append("说明：当前实例没有需要恢复的 detached 推送。")
        return build_markdown_card(
            "Codex 已附着飞书推送", "\n".join(lines), template=template
        )

    def handle_attach_command(self, binding: ChatBindingKey, arg: str) -> CommandResult:
        normalized = str(arg or "").strip().lower()
        scope = normalized or "binding"
        if scope not in {"binding", "thread", "service"}:
            return CommandResult(text="用法：`/attach [binding|thread|service]`")
        try:
            if scope == "binding":
                result = self.attach_binding(binding, writer_binding=binding)
                body = [
                    f"binding：`{result['binding_id']}`",
                    f"线程：`{result['thread_id'][:8]}…` {result.get('thread_title', '') or '（无标题）'}",
                    f"目录：`{display_path(str(result.get('working_dir', '') or ''))}`",
                ]
                if result["already_attached"]:
                    body.append("说明：当前 binding 原本就已是 `attached`。")
                    template = "blue"
                else:
                    body.append(
                        "说明：当前 binding 已恢复为 `attached`，后续可继续接收该 thread 的推送。"
                    )
                    if result.get("active_observer"):
                        body.append(
                            "当前 turn 为中途 observer 接入：此前过程可能不完整；"
                            "从现在起接收后续进展与终态，但不取得当前 turn 的取消或审批权限。"
                        )
                    template = "green"
                return CommandResult(
                    card=build_markdown_card(
                        "Codex 已附着飞书推送", "\n".join(body), template=template
                    )
                )
            if scope == "thread":
                thread_id = self._binding_application.binding_thread_id_or_raise(
                    binding
                )
                return CommandResult(
                    card=self._build_thread_attach_result_card(
                        self._binding_application.attach_thread(
                            thread_id,
                            writer_binding=binding,
                        )
                    )
                )
            return CommandResult(
                card=self._build_service_attach_result_card(
                    self._binding_application.attach_service(writer_binding=binding)
                )
            )
        except Exception as exc:
            return CommandResult(text=f"attach 失败：{exc}")

    def handle_attach_action(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict[str, Any],
    ) -> P2CardActionTriggerResponse:
        binding = self._binding_application.effective_binding_key(
            sender_id,
            chat_id,
        )
        scope = str(action_value.get("scope", "") or "").strip().lower()
        thread_id = str(action_value.get("thread_id", "") or "").strip()
        self._submit_to_runtime(
            self._run_attach_action_on_runtime,
            binding,
            scope,
            message_id=message_id,
            thread_id=thread_id,
        )
        if scope == "service":
            ack_card = build_markdown_card(
                "Codex 正在恢复飞书推送",
                "正在恢复当前实例推送；完成后会自动回复结果。",
            )
        elif scope == "thread":
            ack_card = build_markdown_card(
                "Codex 正在恢复飞书推送",
                "正在恢复当前线程推送；完成后会自动回复结果。",
            )
        else:
            ack_card = build_markdown_card(
                "Codex 正在恢复飞书推送",
                "正在恢复当前会话推送；完成后会自动回复结果。",
            )
        return make_card_response(card=ack_card)

    def _run_attach_action_on_runtime(
        self,
        binding: ChatBindingKey,
        scope: str,
        *,
        message_id: str = "",
        thread_id: str = "",
    ) -> None:
        chat_id = binding[1]
        try:
            if scope == "service":
                card = self._build_service_attach_result_card(
                    self._binding_application.attach_service(writer_binding=binding)
                )
            elif scope == "thread":
                target_thread_id = (
                    thread_id
                    or self._binding_application.binding_thread_id_or_raise(binding)
                )
                card = self._build_thread_attach_result_card(
                    self._binding_application.attach_thread(
                        target_thread_id,
                        writer_binding=binding,
                    )
                )
            else:
                result = self.attach_binding(binding, writer_binding=binding)
                description = (
                    "说明：当前会话原本就已是 `attached`。"
                    if result["already_attached"]
                    else "说明：当前会话已恢复接收该 thread 的飞书推送。"
                )
                if result.get("active_observer"):
                    description += (
                        " 当前 turn 为中途 observer 接入；此前过程可能不完整，"
                        "且不取得取消或审批权限。"
                    )
                template = "blue" if result["already_attached"] else "green"
                card = build_markdown_card(
                    "Codex 已附着飞书推送",
                    "\n".join(
                        [
                            f"binding：`{format_binding_id(binding)}`",
                            description,
                        ]
                    ),
                    template=template,
                )
        except Exception as exc:
            self._reply_card(
                chat_id,
                build_markdown_card(
                    "Codex 飞书推送附着失败", str(exc) or "attach 失败", template="red"
                ),
                message_id=message_id,
            )
            return
        self._reply_card(chat_id, card, message_id=message_id)

    def handle_dismiss_attach_action(self) -> P2CardActionTriggerResponse:
        return make_card_response(
            card=build_markdown_card(
                "Codex Backend Reset",
                "已保持 `detached` 状态。\n如需稍后恢复推送，可发送 `/attach`、`/resume`，或直接发送下一条普通消息。",
                template="blue",
            ),
            toast="已保持 detached。",
            toast_type="info",
        )

    def handle_detach_command(self, binding: ChatBindingKey, arg: str) -> CommandResult:
        if str(arg or "").strip():
            return CommandResult(text="用法：`/detach`")
        try:
            result = self.detach_binding(binding)
        except ValueError as exc:
            return CommandResult(text=str(exc))
        body = [
            f"binding：`{result['binding_id']}`",
            f"线程：`{result['thread_id'][:8]}…` {result['thread_title'] or '（无标题）'}",
            f"目录：`{display_path(result['working_dir'])}`",
            f"飞书推送：`{'detached' if result['changed'] or result['already_detached'] else 'attached'}`",
            f"backend thread status：`{result['backend_thread_status']}`",
        ]
        if result["already_detached"]:
            body.append("说明：当前会话原本就已是 `detached`。")
            template = "blue"
        elif result["backend_still_loaded"]:
            body.append(
                "说明：当前会话已 detach；backend 仍保持 loaded，通常是还有本地 `fcodex` 或其他外部订阅者。"
            )
            template = "green"
        else:
            body.append(
                "说明：当前会话已 detach；如果这是最后一个 attached 的 Feishu binding，服务已自动停止该 thread 的 Feishu 订阅。"
            )
            template = "green"
        return CommandResult(
            card=build_markdown_card(
                "Codex 已暂停飞书推送", "\n".join(body), template=template
            )
        )
