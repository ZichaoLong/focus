"""
Codex advanced feature surface for Feishu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTriggerResponse,
)

from bot.adapters.base import PluginCatalog, PluginDetailSummary, SkillsSnapshot
from bot.cards import CommandResult, build_markdown_action_card, make_card_response
from bot.constants import display_path
from bot.runtime_view import RuntimeView

logger = logging.getLogger(__name__)

_SKILLS_USAGE = "/skills"
_PLUGINS_USAGE = "/plugins [plugin_id]"

_SKILL_SCOPE_LABELS = {
    "repo": "repo",
    "user": "home",
    "system": "system",
    "admin": "admin",
}


class _GetRuntimeView(Protocol):
    def __call__(self, sender_id: str, chat_id: str, message_id: str = "") -> RuntimeView: ...


class _ListSkills(Protocol):
    def __call__(self, *, cwd: str, force_reload: bool = False) -> SkillsSnapshot: ...


class _SetSkillEnabled(Protocol):
    def __call__(self, *, skill_path: str = "", skill_name: str = "", enabled: bool) -> None: ...


class _ListPlugins(Protocol):
    def __call__(self, *, cwd: str | None = None) -> PluginCatalog: ...


class _ReadPlugin(Protocol):
    def __call__(
        self,
        plugin_name: str,
        *,
        marketplace_name: str = "",
        marketplace_path: str | None = None,
    ) -> PluginDetailSummary: ...


class _SetPluginEnabled(Protocol):
    def __call__(self, plugin_id: str, *, enabled: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class AdvancedFeaturePorts:
    get_runtime_view: _GetRuntimeView
    list_skills: _ListSkills
    set_skill_enabled: _SetSkillEnabled
    list_plugins: _ListPlugins
    read_plugin: _ReadPlugin
    set_plugin_enabled: _SetPluginEnabled


class CodexAdvancedFeaturesDomain:
    def __init__(self, *, ports: AdvancedFeaturePorts) -> None:
        self._ports = ports

    def handle_skills_command(
        self,
        sender_id: str,
        chat_id: str,
        arg: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        if arg.strip():
            return CommandResult(text=f"用法：`{_SKILLS_USAGE}`")
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        try:
            snapshot = self._ports.list_skills(cwd=runtime.working_dir, force_reload=True)
        except Exception as exc:
            logger.exception("读取 skills 失败")
            return CommandResult(text=f"读取 skills 失败：{exc}")
        return CommandResult(card=self._build_skills_card(snapshot, running=runtime.running))

    def handle_set_skill_enabled(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        skill_path = str(action_value.get("skill_path", "") or "").strip()
        enabled = bool(action_value.get("enabled"))
        if not skill_path:
            return make_card_response(toast="缺少 skill_path", toast_type="warning")
        try:
            self._ports.set_skill_enabled(skill_path=skill_path, enabled=enabled)
            snapshot = self._ports.list_skills(cwd=runtime.working_dir, force_reload=True)
        except Exception as exc:
            logger.exception("更新 skill 开关失败")
            return make_card_response(toast=f"更新 skill 失败：{exc}", toast_type="warning")
        card = self._build_skills_card(
            snapshot,
            running=runtime.running,
            leading_lines=[
                f"已{'启用' if enabled else '禁用'} skill：`{str(action_value.get('skill_name', '') or '').strip() or skill_path}`",
                "",
            ],
        )
        return make_card_response(card=card, toast="已更新。", toast_type="success")

    def handle_plugins_command(
        self,
        sender_id: str,
        chat_id: str,
        arg: str,
        *,
        message_id: str = "",
    ) -> CommandResult:
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        target = str(arg or "").strip()
        if not target:
            try:
                catalog = self._ports.list_plugins(cwd=runtime.working_dir)
            except Exception as exc:
                logger.exception("读取 plugins 概览失败")
                return CommandResult(text=f"读取 plugins 失败：{exc}")
            return CommandResult(card=self._build_plugins_overview_card(catalog, cwd=runtime.working_dir))
        return self._build_plugin_detail_command_result(
            runtime=runtime,
            plugin_id=target,
        )

    def handle_show_plugins_overview_action(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        del action_value
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        try:
            catalog = self._ports.list_plugins(cwd=runtime.working_dir)
        except Exception as exc:
            logger.exception("读取 plugins 概览失败")
            return make_card_response(toast=f"读取 plugins 失败：{exc}", toast_type="warning")
        return make_card_response(card=self._build_plugins_overview_card(catalog, cwd=runtime.working_dir))

    def handle_show_plugin_detail_action(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        plugin_id = str(action_value.get("plugin_id", "") or "").strip()
        if not plugin_id:
            return make_card_response(toast="缺少 plugin_id", toast_type="warning")
        result = self._build_plugin_detail_command_result(runtime=runtime, plugin_id=plugin_id)
        if result.card is None:
            return make_card_response(toast=result.text or "读取 plugin 详情失败", toast_type="warning")
        return make_card_response(card=result.card)

    def handle_set_plugin_enabled(
        self,
        sender_id: str,
        chat_id: str,
        message_id: str,
        action_value: dict,
    ) -> P2CardActionTriggerResponse:
        runtime = self._ports.get_runtime_view(sender_id, chat_id, message_id)
        plugin_id = str(action_value.get("plugin_id", "") or "").strip()
        plugin_name = str(action_value.get("plugin_name", "") or "").strip()
        marketplace_name = str(action_value.get("marketplace_name", "") or "").strip()
        marketplace_path = str(action_value.get("marketplace_path", "") or "").strip()
        enabled = bool(action_value.get("enabled"))
        if not plugin_id or not plugin_name:
            return make_card_response(toast="缺少 plugin 标识", toast_type="warning")
        try:
            self._ports.set_plugin_enabled(plugin_id, enabled=enabled)
            detail = self._ports.read_plugin(
                plugin_name,
                marketplace_name=marketplace_name,
                marketplace_path=marketplace_path or None,
            )
        except Exception as exc:
            logger.exception("更新 plugin 开关失败")
            return make_card_response(toast=f"更新 plugin 失败：{exc}", toast_type="warning")
        card = self._build_plugin_detail_card(
            detail,
            running=runtime.running,
            leading_lines=[
                f"已{'启用' if enabled else '禁用'} plugin：`{plugin_id}`",
                "",
            ],
        )
        return make_card_response(card=card, toast="已更新。", toast_type="success")

    def _build_plugin_detail_command_result(self, *, runtime: RuntimeView, plugin_id: str) -> CommandResult:
        try:
            catalog = self._ports.list_plugins(cwd=runtime.working_dir)
        except Exception as exc:
            logger.exception("读取 plugins 列表失败")
            return CommandResult(text=f"读取 plugins 失败：{exc}")
        match = catalog.find_plugin(plugin_id)
        if match is None:
            return CommandResult(
                text=(
                    f"未找到 plugin：`{plugin_id}`\n"
                    f"用法：`{_PLUGINS_USAGE}`\n"
                    "先发 `/plugins` 查看当前目录可见的 plugin id。"
                )
            )
        marketplace, plugin = match
        try:
            detail = self._ports.read_plugin(
                plugin.name,
                marketplace_name=marketplace.name if not marketplace.path else "",
                marketplace_path=marketplace.path,
            )
        except Exception as exc:
            logger.exception("读取 plugin 详情失败")
            return CommandResult(text=f"读取 plugin 详情失败：{exc}")
        return CommandResult(card=self._build_plugin_detail_card(detail, running=runtime.running))

    def _build_skills_card(
        self,
        snapshot: SkillsSnapshot,
        *,
        running: bool,
        leading_lines: list[str] | None = None,
    ) -> dict:
        lines: list[str] = list(leading_lines or [])
        lines.extend(
            [
                "作用对象：**当前目录可见的 skills**。",
                f"当前目录：`{display_path(snapshot.cwd)}`",
                f"已发现 skills：`{len(snapshot.skills)}` 个。",
            ]
        )
        if running:
            lines.append("如果当前 thread 正在执行，skills 开关对下一轮 turn 生效。")
        if snapshot.skills:
            lines.extend(["", "**当前可见 skills**"])
            for skill in snapshot.skills:
                description = str(skill.short_description or skill.description or "").strip()
                lines.append(
                    f"- `{skill.name}` · `{_SKILL_SCOPE_LABELS.get(skill.scope, skill.scope or 'unknown')}` · "
                    f"{'已启用' if skill.enabled else '已禁用'} · `{display_path(skill.path)}`"
                )
                if description:
                    lines.append(f"  {description}")
        else:
            lines.extend(["", "当前目录未发现可见 skills。"])
        if snapshot.errors:
            lines.extend(["", "**加载错误**"])
            for item in snapshot.errors:
                lines.append(f"- `{display_path(item.path)}`：{item.message}")
        action_rows: list[dict] = []
        for skill in snapshot.skills:
            action_rows.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "禁用" if skill.enabled else "启用",
                            },
                            "type": "default",
                            "value": {
                                "action": "set_skill_enabled",
                                "skill_name": skill.name,
                                "skill_path": skill.path,
                                "enabled": not skill.enabled,
                            },
                        }
                    ],
                }
            )
        return build_markdown_action_card("Codex Skills", "\n".join(lines), action_rows=action_rows)

    def _build_plugins_overview_card(
        self,
        catalog: PluginCatalog,
        *,
        cwd: str,
        leading_lines: list[str] | None = None,
    ) -> dict:
        installed_plugins = [
            plugin
            for marketplace in catalog.marketplaces
            for plugin in marketplace.plugins
            if plugin.installed
        ]
        enabled_installed_count = sum(1 for plugin in installed_plugins if plugin.enabled)
        lines: list[str] = list(leading_lines or [])
        lines.extend(
            [
                "作用对象：**当前目录可见的 plugins**。",
                f"当前目录：`{display_path(cwd)}`",
                f"marketplaces：`{len(catalog.marketplaces)}` 个。",
                f"已安装 plugins：`{len(installed_plugins)}` 个；其中已启用：`{enabled_installed_count}` 个。",
            ]
        )
        if installed_plugins:
            lines.extend(["", "**已安装 plugins**"])
            for plugin in installed_plugins:
                lines.append(
                    f"- `{plugin.plugin_id}` · {'已启用' if plugin.enabled else '已禁用'} · "
                    f"`{plugin.marketplace_name}` · `{plugin.source_type}`"
                )
        else:
            lines.extend(["", "当前目录没有已安装 plugin。"])
        if catalog.marketplaces:
            lines.extend(["", "**当前可见 marketplaces**"])
            for marketplace in catalog.marketplaces:
                sample_ids = [f"`{plugin.plugin_id}`" for plugin in marketplace.plugins[:5]]
                sample_text = "、".join(sample_ids) if sample_ids else "（空）"
                if len(marketplace.plugins) > 5:
                    sample_text += f" 等，共 `{len(marketplace.plugins)}` 个"
                lines.append(f"- `{marketplace.name}`：{sample_text}")
        if catalog.marketplace_load_errors:
            lines.extend(["", "**marketplace 加载错误**"])
            for item in catalog.marketplace_load_errors:
                lines.append(f"- `{display_path(item.marketplace_path)}`：{item.message}")
        lines.extend(
            [
                "",
                "查看任意 plugin 详情：`/plugins <plugin_id>`。",
                "飞书侧当前只支持查看详情，以及已安装 plugin 的启用/禁用；不支持安装、卸载与 marketplace 管理。",
            ]
        )
        action_rows: list[dict] = []
        for plugin in installed_plugins:
            action_rows.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": f"详情 {plugin.name}",
                            },
                            "type": "default",
                            "value": {
                                "action": "show_plugin_detail",
                                "plugin_id": plugin.plugin_id,
                            },
                        }
                    ],
                }
            )
        return build_markdown_action_card("Codex Plugins", "\n".join(lines), action_rows=action_rows)

    def _build_plugin_detail_card(
        self,
        detail: PluginDetailSummary,
        *,
        running: bool,
        leading_lines: list[str] | None = None,
    ) -> dict:
        plugin = detail.plugin
        lines: list[str] = list(leading_lines or [])
        lines.extend(
            [
                f"plugin：`{plugin.plugin_id}`",
                f"marketplace：`{plugin.marketplace_name}`",
                f"来源：`{plugin.source_type}`",
                f"已安装：`{'yes' if plugin.installed else 'no'}`",
                f"当前状态：`{'enabled' if plugin.enabled else 'disabled'}`",
                f"availability：`{plugin.availability or '（未知）'}`",
                f"install policy：`{plugin.install_policy or '（未知）'}`",
                f"auth policy：`{plugin.auth_policy or '（未知）'}`",
            ]
        )
        if running:
            lines.append("如果当前 thread 正在执行，plugin 启停对下一轮 turn 生效。")
        if detail.description:
            lines.extend(["", detail.description])
        if plugin.keywords:
            lines.extend(["", f"关键词：{', '.join(f'`{item}`' for item in plugin.keywords)}"])
        if detail.skill_names:
            lines.extend(["", f"skills：{', '.join(f'`{item}`' for item in detail.skill_names)}"])
        if detail.hook_keys:
            lines.extend(["", f"hooks：{', '.join(f'`{item}`' for item in detail.hook_keys)}"])
        if detail.app_names:
            lines.extend(["", f"apps：{', '.join(f'`{item}`' for item in detail.app_names)}"])
        if detail.mcp_servers:
            lines.extend(["", f"MCP servers：{', '.join(f'`{item}`' for item in detail.mcp_servers)}"])
        if not plugin.installed:
            lines.extend(["", "当前飞书侧只支持查看该 plugin 详情；安装与卸载仍请在上游 TUI 或本地命令面处理。"])
        action_rows: list[dict] = [
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "返回概览"},
                        "type": "default",
                        "value": {
                            "action": "show_plugins_overview",
                        },
                    }
                ],
            }
        ]
        if plugin.installed:
            action_rows.insert(
                0,
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "禁用" if plugin.enabled else "启用",
                            },
                            "type": "default",
                            "value": {
                                "action": "set_plugin_enabled",
                                "plugin_id": plugin.plugin_id,
                                "plugin_name": plugin.name,
                                "marketplace_name": plugin.marketplace_name if not plugin.marketplace_path else "",
                                "marketplace_path": plugin.marketplace_path or "",
                                "enabled": not plugin.enabled,
                            },
                        }
                    ],
                },
            )
        return build_markdown_action_card("Codex Plugin Detail", "\n".join(lines), action_rows=action_rows)
