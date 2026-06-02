import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from bot.codex_settings_domain import CodexSettingsDomain, SettingsDomainPorts
from bot.feishu_command_syntax import feishu_visible_command_syntax


_APPROVAL_POLICIES = {"untrusted", "on-request", "never"}
_DISPLAY_DEBUG_CONTACT_COMMAND = feishu_visible_command_syntax("/debug-contact <open_id>")


class _SettingsPortsStub:
    def __init__(self) -> None:
        self.message_contexts: dict[str, dict[str, Any]] = {}
        self.bot_identity: dict[str, Any] = {}
        self.added_admin_open_ids: list[str] = []
        self.configured_bot_open_ids: list[str] = []
        self.runtime = SimpleNamespace(
            running=False,
            approval_policy="on-request",
            permissions_profile_id=":workspace",
            collaboration_mode="default",
            model="",
            reasoning_effort="",
            current_thread_id="thread-1",
        )
        self.runtime_view_calls: list[tuple[str, str, str]] = []
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.debug_sender_snapshots: dict[str, dict[str, Any]] = {}

    def get_message_context(self, message_id: str) -> dict[str, Any]:
        return dict(self.message_contexts.get(message_id, {}))

    def get_sender_display_name(
        self,
        *,
        user_id: str,
        open_id: str,
        sender_type: str,
    ) -> str:
        del user_id, sender_type
        return f"name:{open_id}"

    def debug_sender_name_resolution(self, open_id: str) -> dict[str, Any]:
        return dict(
            self.debug_sender_snapshots.get(
                open_id,
                {
                    "open_id": open_id,
                    "cache_hit": False,
                    "cached_name": "",
                    "resolved_name": open_id[:8],
                    "used_fallback": True,
                    "fallback_reason": "api_non_success",
                    "api_code": 999,
                    "api_msg": "denied",
                    "exception": "",
                    "source": "fallback",
                },
            )
        )

    def get_bot_identity_snapshot(self) -> dict[str, Any]:
        return dict(self.bot_identity)

    def add_admin_open_id(self, open_id: str) -> None:
        self.added_admin_open_ids.append(open_id)

    def set_configured_bot_open_id(self, open_id: str) -> None:
        self.configured_bot_open_ids.append(open_id)

    def get_runtime_view(self, sender_id: str, chat_id: str, message_id: str):
        self.runtime_view_calls.append((sender_id, chat_id, message_id))
        return self.runtime

    def update_runtime_settings(self, sender_id: str, chat_id: str, **kwargs: Any) -> None:
        self.update_calls.append((sender_id, chat_id, kwargs))


def _make_domain(stub: _SettingsPortsStub) -> CodexSettingsDomain:
    return CodexSettingsDomain(
        ports=SettingsDomainPorts(
            get_message_context=stub.get_message_context,
            get_sender_display_name=stub.get_sender_display_name,
            debug_sender_name_resolution=stub.debug_sender_name_resolution,
            get_bot_identity_snapshot=stub.get_bot_identity_snapshot,
            add_admin_open_id=stub.add_admin_open_id,
            set_configured_bot_open_id=stub.set_configured_bot_open_id,
            get_runtime_view=stub.get_runtime_view,
            update_runtime_settings=stub.update_runtime_settings,
        ),
        approval_policies=_APPROVAL_POLICIES,
    )


class CodexSettingsDomainTests(unittest.TestCase):
    def test_debug_contact_command_reports_live_diagnostics(self) -> None:
        stub = _SettingsPortsStub()
        stub.debug_sender_snapshots["ou_user"] = {
            "open_id": "ou_user",
            "cache_hit": True,
            "cached_name": "User",
            "resolved_name": "User",
            "used_fallback": False,
            "fallback_reason": "",
            "api_code": "",
            "api_msg": "",
            "exception": "",
            "source": "contact_api",
        }
        domain = _make_domain(stub)

        result = domain.handle_debug_contact_command("ou_user", "chat-a", "ou_user")

        self.assertIn("联系人解析诊断", result.text)
        self.assertIn("cache: `hit`", result.text)
        self.assertIn("resolved_name: `User`", result.text)
        self.assertIn("used_fallback: `no`", result.text)

    def test_debug_contact_command_requires_open_id_argument(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_debug_contact_command("ou_user", "chat-a", "")

        self.assertIn(_DISPLAY_DEBUG_CONTACT_COMMAND, result.text)

    def test_init_command_saves_admin_and_bot_identity(self) -> None:
        stub = _SettingsPortsStub()
        stub.message_contexts["msg-1"] = {
            "sender_open_id": "ou_user",
            "sender_user_id": "u-1",
            "sender_type": "user",
        }
        stub.bot_identity = {
            "discovered_open_id": "ou_bot",
        }
        domain = _make_domain(stub)
        saved_configs: list[dict[str, Any]] = []

        with patch("bot.codex_settings_domain.ensure_init_token", return_value="token-1"):
            with patch("bot.codex_settings_domain.load_system_config_raw", return_value={"admin_open_ids": []}):
                with patch("bot.codex_settings_domain.save_system_config", side_effect=saved_configs.append):
                    result = domain.handle_init_command("ou_user", "chat-a", "token-1", message_id="msg-1")

        self.assertIn("初始化结果", result.text)
        self.assertEqual(stub.added_admin_open_ids, ["ou_user"])
        self.assertEqual(stub.configured_bot_open_ids, ["ou_bot"])
        self.assertEqual(saved_configs[-1]["admin_open_ids"], ["ou_user"])
        self.assertEqual(saved_configs[-1]["bot_open_id"], "ou_bot")

    def test_model_command_without_arg_returns_summary_card(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime.model = "gpt-5.5"
        stub.runtime.reasoning_effort = "high"
        domain = _make_domain(stub)

        result = domain.handle_model_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前会话 model override：`gpt-5.5`", content)
        self.assertIn("当前会话 effort override：`high`", content)
        self.assertNotIn("startup profile", content)

    def test_model_command_updates_runtime_settings(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_model_command("ou_user", "chat-a", "gpt-5.5", message_id="msg-1")

        self.assertIn("已切换当前会话的 model override：`gpt-5.5`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "model": "gpt-5.5"})],
        )

    def test_effort_command_rejects_invalid_value(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_effort_command("ou_user", "chat-a", "weird", message_id="msg-1")

        self.assertIn("非法 reasoning effort", result.text)
        self.assertEqual(stub.update_calls, [])

    def test_permissions_command_updates_runtime_settings(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_permissions_command("ou_user", "chat-a", "danger-full-access", message_id="msg-1")

        self.assertIn("已切换权限基线：`Danger Full Access`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "permissions_profile_id": ":danger-full-access"})],
        )

    def test_set_permissions_profile_action_returns_updated_card(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime.running = True
        domain = _make_domain(stub)

        response = domain.handle_set_permissions_profile(
            "ou_user",
            "chat-a",
            "msg-1",
            {"profile": "danger-full-access"},
        )

        self.assertEqual(response.toast.content, "已切换权限基线：Danger Full Access；下一轮生效")
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "permissions_profile_id": ":danger-full-access"})],
        )
        self.assertIsNotNone(response.card)

    def test_collab_mode_command_returns_card_and_action_updates_setting(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_collab_mode_command("ou_user", "chat-a", "", message_id="msg-1")
        response = domain.handle_set_collaboration_mode(
            "ou_user",
            "chat-a",
            "msg-1",
            {"mode": "plan"},
        )

        self.assertIsNotNone(result.card)
        self.assertEqual(response.toast.content, "已切换协作模式：plan")
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "collaboration_mode": "plan"})],
        )

    def test_bot_status_command_uses_system_yaml_as_authority(self) -> None:
        stub = _SettingsPortsStub()
        stub.bot_identity = {
            "app_id": "cli-app",
            "configured_open_id": "ou_cfg",
            "discovered_open_id": "ou_live",
            "trigger_open_ids": ["ou_1", "ou_2"],
        }
        domain = _make_domain(stub)

        result = domain.handle_bot_status_command("chat-a")

        self.assertIn("configured bot_open_id: `ou_cfg`", result.text)
        self.assertIn("discovered open_id: `ou_live`", result.text)
        self.assertIn("运行时权威值：`system.yaml.bot_open_id`", result.text)


if __name__ == "__main__":
    unittest.main()
