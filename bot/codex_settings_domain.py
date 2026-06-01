"""
Codex settings domain.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from secrets import compare_digest
from typing import Any

from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTriggerResponse,
)

from bot.adapters.base import RuntimeConfigSummary, RuntimeProfileSummary
from bot.cards import (
    CommandResult,
    build_approval_policy_card,
    build_collaboration_mode_card,
    build_model_effort_card,
    build_permissions_profile_card,
    build_profile_card,
    make_card_response,
)
from bot.config import ensure_init_token, load_system_config_raw, save_system_config
from bot.feishu_command_syntax import feishu_visible_command_syntax
from bot.runtime_view import RuntimeView
from bot.permissions_profile import (
    PERMISSION_PROFILE_CHOICES,
    permissions_profile_choice_key,
    permissions_profile_label,
)

logger = logging.getLogger(__name__)

_UNSET = object()
_INIT_COMMAND = feishu_visible_command_syntax("/init <token>")
_DEBUG_CONTACT_COMMAND = feishu_visible_command_syntax("/debug-contact <open_id>")
_PROFILE_WITH_NAME_COMMAND = feishu_visible_command_syntax("/profile <name>")
_PROFILE_CLEAR_COMMAND = feishu_visible_command_syntax("/profile-clear")
_MODEL_WITH_NAME_COMMAND = feishu_visible_command_syntax("/model <name|auto>")
_EFFORT_WITH_NAME_COMMAND = feishu_visible_command_syntax("/effort <auto|none|minimal|low|medium|high|xhigh>")
_MODEL_AUTO = "auto"
_EFFORT_AUTO = "auto"
_REASONING_EFFORT_VALUES = ("none", "minimal", "low", "medium", "high", "xhigh")


@dataclass(frozen=True, slots=True)
class SettingsDomainPorts:
    get_message_context: Callable[[str], dict[str, Any]]
    get_sender_display_name: Callable[..., str]
    debug_sender_name_resolution: Callable[[str], dict[str, Any]]
    get_bot_identity_snapshot: Callable[[], dict[str, Any]]
    add_admin_open_id: Callable[[str], None]
    set_configured_bot_open_id: Callable[[str], None]
    load_codex_config: Callable[[], dict[str, Any]]
    save_codex_config: Callable[[dict[str, Any]], None]
    reset_current_instance_backend: Callable[[bool], dict[str, Any]]
    get_runtime_view: Callable[[str, str, str], RuntimeView]
    update_runtime_settings: Callable[..., None]
    safe_read_runtime_config: Callable[[], RuntimeConfigSummary | None]


@dataclass(frozen=True, slots=True)
class ProfileCommandOutcome:
    command_result: CommandResult
    applied_profile: str = ""
    cleared_profile: bool = False
    reset_offered_profile: str = ""
    reset_offered_clear: bool = False
    reset_requires_force: bool = False
    already_set: bool = False


class CodexSettingsDomain:
    def __init__(
        self,
        *,
        ports: SettingsDomainPorts,
        approval_policies: set[str],
    ) -> None:
        self._ports = ports
        self._approval_policies = approval_policies

    def _runtime_view(self, sender_id: str, chat_id: str, message_id: str = "") -> RuntimeView:
        return self._ports.get_runtime_view(sender_id, chat_id, message_id)

    def _update_runtime_settings(
        self,
        sender_id: str,
        chat_id: str,
        *,
        message_id: str = "",
        approval_policy: Any = _UNSET,
        permissions_profile_id: Any = _UNSET,
        collaboration_mode: Any = _UNSET,
        model: Any = _UNSET,
        reasoning_effort: Any = _UNSET,
    ) -> None:
        changes: dict[str, Any] = {"message_id": message_id}
        if approval_policy is not _UNSET:
            changes["approval_policy"] = approval_policy
        if permissions_profile_id is not _UNSET:
            changes["permissions_profile_id"] = permissions_profile_id
        if collaboration_mode is not _UNSET:
            changes["collaboration_mode"] = collaboration_mode
        if model is not _UNSET:
            changes["model"] = model
        if reasoning_effort is not _UNSET:
            changes["reasoning_effort"] = reasoning_effort
        self._ports.update_runtime_settings(sender_id, chat_id, **changes)

    def handle_init_command(
        self,
        sender_id: str,
        chat_id: str,
        arg: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        del sender_id, chat_id
        ports = self._ports
        context = ports.get_message_context(message_id) if message_id else {}
        provided_token = str(arg or "").strip()
        if not provided_token:
            return CommandResult(text=f"用法：`{_INIT_COMMAND}`\n`token` 默认保存在本机配置目录的 `init.token` 文件。")
        expected_token = ensure_init_token()
        if not compare_digest(provided_token, expected_token):
            return CommandResult(text="初始化口令错误。请检查本机配置目录中的 `init.token`。")
        sender_open_id = str(context.get("sender_open_id", "") or "").strip()
        sender_user_id = str(context.get("sender_user_id", "") or "").strip()
        sender_type = str(context.get("sender_type", "user") or "user").strip()
        if not sender_open_id:
            return CommandResult(text="初始化失败：当前消息上下文里没有发送者 `open_id`，暂时无法写入管理员配置。")
        sender_name = ports.get_sender_display_name(
            user_id=sender_user_id,
            open_id=sender_open_id,
            sender_type=sender_type,
        )
        config = load_system_config_raw()
        admin_open_ids = {
            str(item).strip()
            for item in config.get("admin_open_ids", [])
            if isinstance(item, str) and str(item).strip()
        }
        admin_added = sender_open_id not in admin_open_ids
        admin_open_ids.add(sender_open_id)
        configured_bot_open_id = str(config.get("bot_open_id", "") or "").strip()
        identity = ports.get_bot_identity_snapshot()
        discovered_bot_open_id = str(identity.get("discovered_open_id", "") or "").strip()
        bot_open_id_written = False
        if discovered_bot_open_id and discovered_bot_open_id != configured_bot_open_id:
            configured_bot_open_id = discovered_bot_open_id
            bot_open_id_written = True

        updated_config = dict(config)
        updated_config["admin_open_ids"] = sorted(admin_open_ids)
        if configured_bot_open_id:
            updated_config["bot_open_id"] = configured_bot_open_id

        try:
            save_system_config(updated_config)
        except Exception as exc:
            logger.exception("保存初始化配置失败")
            return CommandResult(text=f"初始化失败：保存配置时出错：{exc}")

        ports.add_admin_open_id(sender_open_id)
        if configured_bot_open_id:
            ports.set_configured_bot_open_id(configured_bot_open_id)

        lines = [
            "初始化结果：",
            (
                f"- admin_open_ids：已加入 `{sender_name}`"
                if admin_added
                else f"- admin_open_ids：`{sender_name}` 已在管理员列表中"
            ),
        ]
        if configured_bot_open_id:
            lines.append(
                f"- bot_open_id：`{configured_bot_open_id}`"
                + ("（本次已写入）" if bot_open_id_written else "（保持不变）")
            )
        else:
            lines.extend(
                [
                    "- bot_open_id：未写入",
                    f"- 请检查 `application:application:self_manage` 权限后重试 `{_INIT_COMMAND}`，或手动填写 `system.yaml.bot_open_id`。",
                ]
            )
        lines.append("- 当前命令只会更新管理员和 bot open id，不会改动 `trigger_open_ids`。")
        return CommandResult(text="\n".join(lines))

    def handle_whoami_command(self, sender_id: str, chat_id: str, *, message_id: str = "") -> CommandResult:
        del sender_id, chat_id
        ports = self._ports
        context = ports.get_message_context(message_id) if message_id else {}
        sender_user_id = str(context.get("sender_user_id", "")).strip()
        sender_open_id = str(context.get("sender_open_id", "")).strip()
        sender_type = str(context.get("sender_type", "user") or "user").strip()
        name = ports.get_sender_display_name(
            user_id=sender_user_id,
            open_id=sender_open_id,
            sender_type=sender_type,
        )
        return CommandResult(text="\n".join(
            [
                "你的身份信息：",
                f"- name: `{name}`",
                f"- user_id: `{sender_user_id or '（空）'}`",
                f"- open_id: `{sender_open_id or '（空）'}`",
                "",
                "配置管理员时，把 `open_id` 写进 `system.yaml` 的 `admin_open_ids`。",
                "其中 `user_id` 仅用于排障；若未开 `contact:user.employee_id:readonly`，这里允许为空。",
            ]
        ))

    def handle_debug_contact_command(
        self,
        sender_id: str,
        chat_id: str,
        arg: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        del sender_id, chat_id, message_id
        normalized_open_id = str(arg or "").strip()
        if not normalized_open_id:
            return CommandResult(
                text=f"用法：`{_DEBUG_CONTACT_COMMAND}`\n用于排查联系人接口名字解析、缓存命中与 fallback 原因。"
            )
        snapshot = self._ports.debug_sender_name_resolution(normalized_open_id)
        cache_state = "hit" if snapshot.get("cache_hit") else "miss"
        lines = [
            "联系人解析诊断：",
            f"- open_id: `{snapshot.get('open_id', '') or '（空）'}`",
            f"- cache: `{cache_state}`",
            f"- cached_name: `{snapshot.get('cached_name', '') or '（空）'}`",
            f"- resolved_name: `{snapshot.get('resolved_name', '') or '（空）'}`",
            f"- source: `{snapshot.get('source', '') or '（空）'}`",
            f"- used_fallback: `{'yes' if snapshot.get('used_fallback') else 'no'}`",
        ]
        fallback_reason = str(snapshot.get("fallback_reason", "") or "").strip()
        if fallback_reason:
            lines.append(f"- fallback_reason: `{fallback_reason}`")
        api_code = snapshot.get("api_code")
        if api_code not in ("", None):
            lines.append(f"- api_code: `{api_code}`")
        api_msg = str(snapshot.get("api_msg", "") or "").strip()
        if api_msg:
            lines.append(f"- api_msg: `{api_msg}`")
        exception_text = str(snapshot.get("exception", "") or "").strip()
        if exception_text:
            lines.append(f"- exception: `{exception_text}`")
        lines.extend(
            [
                "",
                "排查提示：",
                "- 如需 `/whoami`、群授权卡片、群上下文显示可读名字，确认已开 `contact:contact.base:readonly`、`contact:user.base:readonly`。",
                "- 若这里只能 fallback 到 open_id 前缀，请先检查通讯录权限、应用可用范围，以及目标成员是否仍在可见范围内。",
            ]
        )
        return CommandResult(text="\n".join(lines))

    def handle_bot_status_command(self, chat_id: str, *, message_id: str = "") -> CommandResult:
        del chat_id, message_id
        identity = self._ports.get_bot_identity_snapshot()
        configured_open_id = str(identity.get("configured_open_id", "") or "").strip()
        discovered_open_id = str(identity.get("discovered_open_id", "") or "").strip()
        trigger_open_ids = [
            str(item).strip()
            for item in (identity.get("trigger_open_ids") or [])
            if str(item).strip()
        ]
        lines = [
            "机器人身份信息：",
            f"- app_id: `{identity.get('app_id', '') or '（空）'}`",
            f"- configured bot_open_id: `{configured_open_id or '（空）'}`",
            f"- discovered open_id: `{discovered_open_id or '（空）'}`",
            f"- runtime mention matching: `{'enabled' if configured_open_id else 'disabled'}`",
            f"- trigger_open_ids: `{', '.join(trigger_open_ids) or '（空）'}`",
            "- 运行时权威值：`system.yaml.bot_open_id`",
        ]
        if configured_open_id and discovered_open_id and configured_open_id != discovered_open_id:
            lines.extend(
                [
                    "",
                    "警告：",
                    "- 当前运行时仍只按 `system.yaml.bot_open_id` 判定 mention；实时探测值仅用于诊断和初始化。",
                    "- 当前配置值与实时探测值不一致，请优先核对 `system.yaml.bot_open_id` 是否写错。",
                ]
            )
        if not configured_open_id:
            lines.extend(
                [
                    "",
                    "建议：",
                    (
                        f"- 直接执行 `{_INIT_COMMAND}` 自动写入，或手动把 `{discovered_open_id}` 写进 `system.yaml.bot_open_id`"
                        if discovered_open_id
                        else f"- 先让 `/bot-status` 能看到 `discovered open_id`，再手动写入 `system.yaml.bot_open_id`；如需自动写入，再执行 `{_INIT_COMMAND}`"
                    ),
                    "- 运行时只有 `system.yaml.bot_open_id` 会参与群聊 mention 判定；`/bot-status` 的实时探测结果不会自动生效。",
                    "- 如需让“别人 @你本人时由机器人代答”，再把对应人的 open_id 写进 `system.yaml.trigger_open_ids`",
                    "- 如果 `discovered open_id` 为空，检查 `application:application:self_manage` 权限",
                ]
            )
        return CommandResult(text="\n".join(lines))

    def handle_profile_command(self, sender_id: str, chat_id: str, arg: str, *, message_id: str = "") -> CommandResult:
        return self._handle_startup_profile_request(
            sender_id,
            chat_id,
            str(arg or "").strip(),
            message_id=message_id,
        ).command_result

    def handle_profile_clear_command(
        self,
        sender_id: str,
        chat_id: str,
        arg: str = "",
        *,
        message_id: str = "",
    ) -> CommandResult:
        if str(arg or "").strip():
            return CommandResult(
                text=f"用法：`{_PROFILE_CLEAR_COMMAND}`\n说明：该命令不接受额外参数。"
            )
        return self._handle_clear_startup_profile_request(
            sender_id,
            chat_id,
            message_id=message_id,
        ).command_result

    @staticmethod
    def _profile_clear_action_rows(*, with_reset: bool = False, force: bool = False) -> list[dict]:
        label = "强制清空并重置 backend" if force else "清空并重置 backend"
        value = {
            "action": "clear_profile_with_backend_reset" if with_reset else "clear_profile",
            "force": bool(force),
        }
        if not with_reset:
            value.pop("force", None)
            label = "清空 profile"
        return [
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": label},
                        "type": "default" if not with_reset else "primary",
                        "value": value,
                    }
                ],
            },
        ]

    def _runtime_profile_catalog(self) -> tuple[dict[str, RuntimeProfileSummary], list[str]] | tuple[None, None]:
        runtime_config = self._ports.safe_read_runtime_config()
        if runtime_config is None:
            return None, None
        profiles = {profile.name: profile for profile in runtime_config.profiles if profile.name}
        profile_names = [profile.name for profile in runtime_config.profiles if profile.name]
        return profiles, profile_names

    def _managed_startup_profile_state(self) -> tuple[str, str]:
        config = dict(self._ports.load_codex_config() or {})
        mode = str(config.get("app_server_mode", "managed") or "managed").strip().lower() or "managed"
        current_profile = str(config.get("managed_startup_profile", "") or "").strip()
        return mode, current_profile

    @staticmethod
    def _startup_profile_action_rows(*, current_profile: str, include_reset_button: bool = True) -> list[dict]:
        actions: list[dict] = []
        if include_reset_button:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "重置 backend 以应用"},
                    "type": "primary",
                    "value": {
                        "action": "reset_backend",
                        "force": False,
                    },
                }
            )
        if current_profile:
            actions.append(
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "清空 profile"},
                    "type": "default",
                    "value": {
                        "action": "clear_profile",
                    },
                }
            )
        if not actions:
            return []
        return [
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": actions,
            },
        ]

    def _build_startup_profile_summary_card(
        self,
        *,
        current_profile: str,
        profile_names: list[str],
        leading_lines: list[str] | None = None,
    ) -> dict:
        lines = list(leading_lines or [])
        lines.extend(
            [
                f"当前实例 startup profile：`{current_profile or 'auto'}`",
                "作用范围：managed backend 的启动基线。",
                "它不会直接改写当前 thread，也不会立即改动已加载 backend 的 live state。",
                "如需让当前实例马上切到这套基线，请重置 backend。",
            ]
        )
        if not profile_names:
            lines.extend(["", "未在共享 `CODEX_HOME` 中发现可用的 profile-v2。"])
        return build_profile_card(
            content="\n".join(lines),
            profile_names=profile_names,
            current_profile=current_profile,
            extra_action_rows=(
                self._startup_profile_action_rows(current_profile=current_profile)
                or None
            ),
            title="Codex Backend Startup Profile",
        )

    def _handle_startup_profile_request(
        self,
        sender_id: str,
        chat_id: str,
        arg: str,
        *,
        message_id: str = "",
    ) -> ProfileCommandOutcome:
        del sender_id, chat_id, message_id
        ports = self._ports
        mode, current_profile = self._managed_startup_profile_state()
        if mode != "managed":
            return ProfileCommandOutcome(
                command_result=CommandResult(
                    text=(
                        "当前实例使用的是 remote app-server；实例级 startup `/profile` 只适用于 managed backend。\n"
                        "如需切换 profile，请在对应 backend 的启动配置或本地 `codex` 命令侧处理。"
                    )
                )
            )
        profiles, profile_names = self._runtime_profile_catalog()
        if profiles is None or profile_names is None:
            return ProfileCommandOutcome(
                command_result=CommandResult(text="读取 Codex 运行时配置失败，无法查看或切换 startup profile。")
            )
        if not arg:
            return ProfileCommandOutcome(
                command_result=CommandResult(
                    card=self._build_startup_profile_summary_card(
                        current_profile=current_profile,
                        profile_names=profile_names,
                    )
                )
            )

        target_profile = str(arg or "").strip()
        if target_profile not in profiles:
            return ProfileCommandOutcome(
                command_result=CommandResult(
                    text=f"未找到 profile：`{target_profile}`\n用法：`{_PROFILE_WITH_NAME_COMMAND}`\n先发 `/profile` 查看可用 profile。"
                )
            )
        if target_profile == current_profile:
            return ProfileCommandOutcome(
                command_result=CommandResult(
                    card=self._build_startup_profile_summary_card(
                        current_profile=current_profile,
                        profile_names=profile_names,
                        leading_lines=[f"当前实例的 startup profile 已是：`{target_profile}`", ""],
                    )
                ),
                already_set=True,
            )

        config = dict(ports.load_codex_config() or {})
        config["managed_startup_profile"] = target_profile
        try:
            ports.save_codex_config(config)
        except Exception as exc:
            logger.exception("保存 managed startup profile 失败")
            return ProfileCommandOutcome(
                command_result=CommandResult(text=f"切换 startup profile 失败：{exc}")
            )
        return ProfileCommandOutcome(
            command_result=CommandResult(
                card=self._build_startup_profile_summary_card(
                    current_profile=target_profile,
                    profile_names=profile_names,
                    leading_lines=[
                        f"已设置当前实例的 startup profile：`{target_profile}`",
                        "该设置会在下次 managed backend 启动时生效。",
                        "",
                    ],
                )
            ),
            applied_profile=target_profile,
        )

    def _handle_clear_startup_profile_request(
        self,
        sender_id: str,
        chat_id: str,
        *,
        message_id: str = "",
    ) -> ProfileCommandOutcome:
        del sender_id, chat_id, message_id
        ports = self._ports
        mode, current_profile = self._managed_startup_profile_state()
        if mode != "managed":
            return ProfileCommandOutcome(
                command_result=CommandResult(
                    text=(
                        "当前实例使用的是 remote app-server；实例级 startup `/profile-clear` 只适用于 managed backend。"
                    )
                )
            )
        profiles, profile_names = self._runtime_profile_catalog()
        if profiles is None or profile_names is None:
            return ProfileCommandOutcome(
                command_result=CommandResult(text="读取 Codex 运行时配置失败，无法清空 startup profile。")
            )
        if not current_profile:
            return ProfileCommandOutcome(
                command_result=CommandResult(
                    card=self._build_startup_profile_summary_card(
                        current_profile="",
                        profile_names=profile_names,
                        leading_lines=["当前实例未设置 startup profile。", ""],
                    )
                ),
                already_set=True,
            )
        config = dict(ports.load_codex_config() or {})
        config.pop("managed_startup_profile", None)
        try:
            ports.save_codex_config(config)
        except Exception as exc:
            logger.exception("清空 managed startup profile 失败")
            return ProfileCommandOutcome(
                command_result=CommandResult(text=f"清空 startup profile 失败：{exc}")
            )
        return ProfileCommandOutcome(
            command_result=CommandResult(
                card=self._build_startup_profile_summary_card(
                    current_profile="",
                    profile_names=profile_names,
                    leading_lines=[
                        "已清空当前实例的 startup profile override。",
                        "当前将回落到 `CODEX_HOME/config.toml` 顶层配置。",
                        "",
                    ],
                )
            ),
            cleared_profile=True,
        )

    def _apply_profile_after_backend_reset(
        self,
        sender_id: str,
        chat_id: str,
        target_profile: str,
        *,
        force: bool,
        message_id: str = "",
    ) -> ProfileCommandOutcome:
        initial = self._handle_startup_profile_request(sender_id, chat_id, target_profile, message_id=message_id)
        if initial.command_result.card is None and not initial.applied_profile and not initial.already_set:
            return initial
        try:
            reset_result = self._ports.reset_current_instance_backend(force)
        except Exception as exc:
            logger.exception("reset backend 失败")
            return ProfileCommandOutcome(command_result=CommandResult(text=f"reset backend 失败：{exc}"))
        _, current_profile = self._managed_startup_profile_state()
        profiles, profile_names = self._runtime_profile_catalog()
        if profiles is None or profile_names is None:
            return ProfileCommandOutcome(command_result=CommandResult(text="reset 完成，但重新读取 profile 列表失败。"))
        leading_lines = [
            f"已设置当前实例的 startup profile：`{current_profile or 'auto'}`",
            "已重置当前实例 backend。",
        ]
        if reset_result.get("interrupted_binding_ids"):
            leading_lines.append(
                "已中断运行中的 binding："
                + ", ".join(f"`{binding_id}`" for binding_id in reset_result["interrupted_binding_ids"])
            )
        if reset_result.get("fail_closed_request_count"):
            leading_lines.append(
                f"已自动结束待处理审批/输入请求：`{reset_result['fail_closed_request_count']}`"
            )
        return ProfileCommandOutcome(
            command_result=CommandResult(
                card=self._build_startup_profile_summary_card(
                    current_profile=current_profile,
                    profile_names=profile_names,
                    leading_lines=leading_lines + [""],
                )
            ),
            applied_profile=current_profile,
        )

    def _clear_profile_after_backend_reset(
        self,
        sender_id: str,
        chat_id: str,
        *,
        force: bool,
        message_id: str = "",
    ) -> ProfileCommandOutcome:
        initial = self._handle_clear_startup_profile_request(
            sender_id,
            chat_id,
            message_id=message_id,
        )
        if initial.command_result.card is None and not initial.cleared_profile and not initial.already_set:
            return initial
        try:
            reset_result = self._ports.reset_current_instance_backend(force)
        except Exception as exc:
            logger.exception("reset backend 失败")
            return ProfileCommandOutcome(command_result=CommandResult(text=f"reset backend 失败：{exc}"))
        profiles, profile_names = self._runtime_profile_catalog()
        if profiles is None or profile_names is None:
            return ProfileCommandOutcome(command_result=CommandResult(text="reset 完成，但重新读取 profile 列表失败。"))
        leading_lines = [
            "已清空当前实例的 startup profile override。",
            "已重置当前实例 backend。",
        ]
        if reset_result.get("interrupted_binding_ids"):
            leading_lines.append(
                "已中断运行中的 binding："
                + ", ".join(f"`{binding_id}`" for binding_id in reset_result["interrupted_binding_ids"])
            )
        if reset_result.get("fail_closed_request_count"):
            leading_lines.append(
                f"已自动结束待处理审批/输入请求：`{reset_result['fail_closed_request_count']}`"
            )
        return ProfileCommandOutcome(
            command_result=CommandResult(
                card=self._build_startup_profile_summary_card(
                    current_profile="",
                    profile_names=profile_names,
                    leading_lines=leading_lines + [""],
                )
            ),
            cleared_profile=True,
        )

    @staticmethod
    def _runtime_model_display_text(model: str) -> str:
        normalized = str(model or "").strip()
        return normalized or _MODEL_AUTO

    @staticmethod
    def _runtime_effort_display_text(reasoning_effort: str) -> str:
        normalized = str(reasoning_effort or "").strip()
        return normalized or _EFFORT_AUTO

    @staticmethod
    def _normalize_reasoning_effort_override(target: str) -> str:
        normalized_target = str(target or "").strip().lower()
        if normalized_target == _EFFORT_AUTO:
            return ""
        if normalized_target in _REASONING_EFFORT_VALUES:
            return normalized_target
        supported = "、".join(f"`{item}`" for item in (_EFFORT_AUTO, *_REASONING_EFFORT_VALUES))
        raise ValueError(f"reasoning effort 仅支持：{supported}")

    def _build_model_effort_summary_card(
        self,
        *,
        runtime: RuntimeView,
    ) -> dict:
        current_thread_id = str(runtime.current_thread_id or "").strip()
        startup_mode, startup_profile = self._managed_startup_profile_state()
        lines = [
            f"当前会话 model override：`{self._runtime_model_display_text(runtime.model)}`",
            f"当前会话 effort override：`{self._runtime_effort_display_text(runtime.reasoning_effort)}`",
            "作用范围：只影响当前飞书会话的后续 turn，不影响已打开的 `fcodex` TUI。",
            "",
            f"- `{_MODEL_AUTO}`：清除当前会话的 model override；回到当前 backend 已生效的默认 model",
            f"- `{_EFFORT_AUTO}`：清除当前会话的 effort override；回到当前 backend 已生效的默认 effort / model default",
            "- `none`：显式不使用 reasoning effort",
            "- 显式设置具体 model 时，只覆盖当前会话后续 turn 的 `model` 名称",
            "- 当前卡片不枚举 provider 模型列表；可直接输入 model 名称",
        ]
        if startup_mode == "managed":
            lines.extend(
                [
                    "",
                    f"当前实例 startup profile：`{startup_profile or 'auto'}`",
                    "注意：startup profile 只定义 managed backend 的启动基线；修改后需重置 backend 才会影响这里的回退值。",
                ]
            )
        if current_thread_id:
            lines.extend(
                [
                    "",
                    f"当前 thread：`{current_thread_id[:8]}…`",
                    (
                        "当前 effective effort 来源："
                        + (
                            f"turn override `{self._runtime_effort_display_text(runtime.reasoning_effort)}`"
                            if str(runtime.reasoning_effort or "").strip()
                            else "backend default / model default"
                        )
                    ),
                ]
            )
        return build_model_effort_card(
            current_model=runtime.model,
            current_reasoning_effort=runtime.reasoning_effort,
            content="\n".join(lines),
            running=runtime.running,
        )

    def handle_model_command(self, sender_id: str, chat_id: str, arg: str, *, message_id: str = "") -> CommandResult:
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        if not arg:
            return CommandResult(card=self._build_model_effort_summary_card(runtime=runtime))
        target = str(arg or "").strip()
        if not target:
            return CommandResult(text=f"用法：`{_MODEL_WITH_NAME_COMMAND}`")
        normalized_target = target.lower()
        desired_model = "" if normalized_target == _MODEL_AUTO else target
        if str(runtime.model or "").strip() == desired_model:
            label = self._runtime_model_display_text(desired_model)
            return CommandResult(
                text=(
                    f"当前会话的 model override 已是：`{label}`\n"
                    "作用范围：只影响当前飞书会话的后续 turn。"
                )
            )
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            model=desired_model,
        )
        label = self._runtime_model_display_text(desired_model)
        message = (
            f"已切换当前会话的 model override：`{label}`\n"
            "作用范围：只影响当前飞书会话的后续 turn，不影响已打开的 `fcodex` TUI。"
        )
        if runtime.running:
            message += "\n如果当前正在执行，新设置从下一轮生效。"
        return CommandResult(text=message)

    def handle_effort_command(self, sender_id: str, chat_id: str, arg: str, *, message_id: str = "") -> CommandResult:
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        if not arg:
            return CommandResult(card=self._build_model_effort_summary_card(runtime=runtime))
        target = str(arg or "").strip()
        if not target:
            return CommandResult(text=f"用法：`{_EFFORT_WITH_NAME_COMMAND}`")
        try:
            desired_effort = self._normalize_reasoning_effort_override(target)
        except ValueError as exc:
            return CommandResult(text=f"非法 reasoning effort：`{target}`\n用法：`{_EFFORT_WITH_NAME_COMMAND}`\n{exc}")
        if str(runtime.reasoning_effort or "").strip() == desired_effort:
            label = self._runtime_effort_display_text(desired_effort)
            return CommandResult(
                text=(
                    f"当前会话的 effort override 已是：`{label}`\n"
                    "作用范围：只影响当前飞书会话的后续 turn。"
                )
            )
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            reasoning_effort=desired_effort,
        )
        label = self._runtime_effort_display_text(desired_effort)
        message = (
            f"已切换当前会话的 effort override：`{label}`\n"
            "作用范围：只影响当前飞书会话的后续 turn，不影响已打开的 `fcodex` TUI。"
        )
        if runtime.running:
            message += "\n如果当前正在执行，新设置从下一轮生效。"
        return CommandResult(text=message)

    def handle_approval_command(self, sender_id: str, chat_id: str, arg: str, *, message_id: str = "") -> CommandResult:
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        if arg:
            policy = arg.strip().lower()
            if policy not in self._approval_policies:
                return CommandResult(text="审批策略仅支持：`untrusted`、`on-request`、`never`")
            self._update_runtime_settings(
                sender_id,
                chat_id,
                message_id=message_id,
                approval_policy=policy,
            )
            running = runtime.running
            message = f"已切换审批策略：`{policy}`\n作用范围：只影响当前飞书会话的后续 turn。"
            if running:
                message += "\n如果当前正在执行，新设置从下一轮生效。"
            return CommandResult(text=message)
        return CommandResult(card=build_approval_policy_card(runtime.approval_policy, running=runtime.running))

    def handle_permissions_command(self, sender_id: str, chat_id: str, arg: str, *, message_id: str = "") -> CommandResult:
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        if arg:
            choice = arg.strip().lower()
            config = PERMISSION_PROFILE_CHOICES.get(choice)
            if config is None:
                return CommandResult(text="权限基线仅支持：`read-only`、`workspace`、`danger-full-access`")
            self._update_runtime_settings(
                sender_id,
                chat_id,
                message_id=message_id,
                permissions_profile_id=config["profile_id"],
            )
            running = runtime.running
            message = (
                f"已切换权限基线：`{config['label']}`\n"
                f"Profile ID：`{config['profile_id']}`\n"
                "它只决定执行边界；是否需要停下来审批，仍由 `/approval` 单独控制。\n"
                "作用范围：只影响当前飞书会话的后续 turn。"
            )
            if running:
                message += "\n如果当前正在执行，新设置从下一轮生效。"
            return CommandResult(text=message)
        return CommandResult(
            card=build_permissions_profile_card(
                runtime.permissions_profile_id,
                running=runtime.running,
            )
        )

    def handle_collab_mode_command(self, sender_id: str, chat_id: str, arg: str, *, message_id: str = "") -> CommandResult:
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        if arg:
            mode = arg.strip().lower()
            if mode not in {"default", "plan"}:
                return CommandResult(text="协作模式仅支持：`default`、`plan`")
            self._update_runtime_settings(
                sender_id,
                chat_id,
                message_id=message_id,
                collaboration_mode=mode,
            )
            running = runtime.running
            message = f"已切换协作模式：`{mode}`\n作用范围：只影响当前飞书会话的后续 turn，不影响已打开的 `fcodex` TUI。"
            if running:
                message += "\n如果当前正在执行，新设置从下一轮生效。"
            return CommandResult(text=message)
        return CommandResult(card=build_collaboration_mode_card(
            runtime.collaboration_mode,
            running=runtime.running,
        ))

    def handle_set_model(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        target_model = str(action_value.get("model", "") or "").strip()
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            model=target_model,
        )
        running = runtime.running
        toast = f"已切换 model override：{self._runtime_model_display_text(target_model)}"
        if running:
            toast += "；下一轮生效"
        return make_card_response(
            card=self._build_model_effort_summary_card(runtime=self._runtime_view(sender_id, chat_id, message_id)),
            toast=toast,
            toast_type="success",
        )

    def handle_submit_model_override(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        form_value = action_value.get("_form_value") or {}
        if not isinstance(form_value, dict):
            return make_card_response(toast="表单缺少 model 输入。", toast_type="warning")
        submitted = str(form_value.get("model_override", "") or "").strip()
        if not submitted:
            return make_card_response(toast="请输入 model 名称；如需清除 override，请点 auto。", toast_type="warning")
        desired_model = "" if submitted.lower() == _MODEL_AUTO else submitted
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            model=desired_model,
        )
        toast = f"已切换 model override：{self._runtime_model_display_text(desired_model)}"
        if runtime.running:
            toast += "；下一轮生效"
        return make_card_response(
            card=self._build_model_effort_summary_card(runtime=self._runtime_view(sender_id, chat_id, message_id)),
            toast=toast,
            toast_type="success",
        )

    def resolve_runtime_settings_form_submit_payload(self, action_value: dict[str, Any]) -> dict[str, str] | None:
        form_value = action_value.get("_form_value") or {}
        if not isinstance(form_value, dict) or not form_value:
            return None
        if "model_override" in form_value:
            return {"action": "submit_model_override"}
        return None

    def handle_set_reasoning_effort(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        target_effort = str(action_value.get("reasoning_effort", "") or "").strip()
        try:
            desired_effort = self._normalize_reasoning_effort_override(target_effort or _EFFORT_AUTO)
        except ValueError as exc:
            return make_card_response(toast=str(exc), toast_type="warning")
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            reasoning_effort=desired_effort,
        )
        toast = f"已切换 effort override：{self._runtime_effort_display_text(desired_effort)}"
        if runtime.running:
            toast += "；下一轮生效"
        return make_card_response(
            card=self._build_model_effort_summary_card(runtime=self._runtime_view(sender_id, chat_id, message_id)),
            toast=toast,
            toast_type="success",
        )

    def handle_set_approval_policy(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        policy = str(action_value.get("policy", "")).strip().lower()
        if policy not in self._approval_policies:
            return make_card_response(toast="非法审批策略", toast_type="warning")
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            approval_policy=policy,
        )
        running = runtime.running
        toast = f"已切换审批策略：{policy}"
        if running:
            toast += "；下一轮生效"
        return make_card_response(
            card=build_approval_policy_card(policy, running=running),
            toast=toast,
            toast_type="success",
        )

    def handle_set_permissions_profile(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        choice = str(action_value.get("profile", "")).strip().lower()
        config = PERMISSION_PROFILE_CHOICES.get(choice)
        if config is None:
            return make_card_response(toast="非法权限基线", toast_type="warning")
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            permissions_profile_id=config["profile_id"],
        )
        running = runtime.running
        toast = f"已切换权限基线：{config['label']}"
        if running:
            toast += "；下一轮生效"
        return make_card_response(
            card=build_permissions_profile_card(
                config["profile_id"],
                running=running,
            ),
            toast=toast,
            toast_type="success",
        )

    def handle_set_collaboration_mode(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        mode = str(action_value.get("mode", "")).strip().lower()
        if mode not in {"default", "plan"}:
            return make_card_response(toast="非法协作模式", toast_type="warning")
        runtime = self._runtime_view(sender_id, chat_id, message_id)
        self._update_runtime_settings(
            sender_id,
            chat_id,
            message_id=message_id,
            collaboration_mode=mode,
        )
        running = runtime.running
        toast = f"已切换协作模式：{mode}"
        if running:
            toast += "；下一轮生效"
        return make_card_response(
            card=build_collaboration_mode_card(mode, running=running),
            toast=toast,
            toast_type="success",
        )

    def handle_set_profile(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        target_profile = str(action_value.get("profile", "")).strip()
        if not target_profile:
            return make_card_response(toast="缺少 profile 名称", toast_type="warning")
        outcome = self._handle_startup_profile_request(sender_id, chat_id, target_profile, message_id=message_id)
        result = outcome.command_result
        if result.card is None:
            return make_card_response(toast=result.text or "切换 startup profile 失败", toast_type="warning")
        if outcome.applied_profile:
            toast = f"已设置当前实例的 startup profile：{target_profile}"
            toast_type = "success"
        elif outcome.already_set:
            toast = f"当前实例的 startup profile 已是：{target_profile}"
            toast_type = "success"
        else:
            toast = result.text or "当前不能切换该 startup profile。"
            toast_type = "warning"
        return make_card_response(
            card=result.card,
            toast=toast,
            toast_type=toast_type,
        )

    def handle_clear_profile(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        del action_value
        outcome = self._handle_clear_startup_profile_request(
            sender_id,
            chat_id,
            message_id=message_id,
        )
        result = outcome.command_result
        if result.card is None:
            return make_card_response(toast=result.text or "清空 startup profile 失败", toast_type="warning")
        if outcome.cleared_profile:
            toast = "已清空当前实例的 startup profile override"
            toast_type = "success"
        elif outcome.already_set:
            toast = "当前实例未设置 startup profile"
            toast_type = "success"
        else:
            toast = result.text or "当前不能清空该 startup profile。"
            toast_type = "warning"
        return make_card_response(
            card=result.card,
            toast=toast,
            toast_type=toast_type,
        )

    def handle_apply_profile_with_backend_reset(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        target_profile = str(action_value.get("profile", "")).strip()
        if not target_profile:
            return make_card_response(toast="缺少 profile 名称", toast_type="warning")
        outcome = self._apply_profile_after_backend_reset(
            sender_id,
            chat_id,
            target_profile,
            force=bool(action_value.get("force")),
            message_id=message_id,
        )
        result = outcome.command_result
        if result.card is None:
            return make_card_response(toast=result.text or "应用 startup profile 失败", toast_type="warning")
        if outcome.applied_profile:
            toast = f"已应用 `{outcome.applied_profile}` 并重置 backend。"
            return make_card_response(card=result.card, toast=toast, toast_type="success")
        if outcome.already_set:
            return make_card_response(
                card=result.card,
                toast=f"当前实例的 startup profile 已是：{target_profile}",
                toast_type="success",
            )
        return make_card_response(
            card=result.card,
            toast=result.text or "当前仍无法应用该 startup profile。",
            toast_type="warning",
        )

    def handle_clear_profile_with_backend_reset(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        outcome = self._clear_profile_after_backend_reset(
            sender_id,
            chat_id,
            force=bool(action_value.get("force")),
            message_id=message_id,
        )
        result = outcome.command_result
        if result.card is None:
            return make_card_response(toast=result.text or "清空 startup profile 失败", toast_type="warning")
        if outcome.cleared_profile:
            return make_card_response(
                card=result.card,
                toast="已清空当前实例的 startup profile 并重置 backend。",
                toast_type="success",
            )
        if outcome.already_set:
            return make_card_response(
                card=result.card,
                toast="当前实例未设置 startup profile。",
                toast_type="success",
            )
        return make_card_response(
            card=result.card,
            toast=result.text or "当前仍无法清空该 startup profile。",
            toast_type="warning",
        )
