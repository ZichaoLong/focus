import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any

from bot.adapters.base import RuntimeConfigSummary, RuntimeProfileSummary, ThreadSummary
from bot.codex_settings_domain import (
    CodexSettingsDomain,
    SettingsDomainPorts,
)
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
        self.runtime_config = RuntimeConfigSummary(
            profiles=[
                RuntimeProfileSummary(name="default", model_provider="openai"),
                RuntimeProfileSummary(name="work", model_provider="anthropic"),
            ],
            current_memory_mode="read",
        )
        self.local_profile_names: list[str] = ["default", "work"]
        self.codex_config: dict[str, Any] = {"app_server_mode": "managed"}
        self.reset_backend_calls: list[bool] = []
        self.runtime_view_calls: list[tuple[str, str, str]] = []
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.resolution_calls: list[RuntimeConfigSummary | None] = []
        self.debug_sender_snapshots: dict[str, dict[str, Any]] = {}
        self.thread_summaries: dict[str, ThreadSummary] = {
            "thread-1": ThreadSummary(
                thread_id="thread-1",
                cwd="/tmp/project",
                name="demo",
                preview="hello",
                created_at=0,
                updated_at=0,
                source="appServer",
                status="idle",
            )
        }
        self.read_thread_errors: dict[str, Exception] = {}
        self.cleared_thread_bindings: list[tuple[str, str, str]] = []

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

    def get_bot_identity_snapshot(self) -> dict[str, Any]:
        return dict(self.bot_identity)

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

    def add_admin_open_id(self, open_id: str) -> None:
        self.added_admin_open_ids.append(open_id)

    def set_configured_bot_open_id(self, open_id: str) -> None:
        self.configured_bot_open_ids.append(open_id)

    def load_codex_config(self) -> dict[str, Any]:
        return dict(self.codex_config)

    def save_codex_config(self, config: dict[str, Any]) -> None:
        self.codex_config = dict(config)

    def reset_current_instance_backend(self, force: bool) -> dict[str, Any]:
        self.reset_backend_calls.append(bool(force))
        return {
            "force": bool(force),
            "detached_binding_ids": ["p2p:ou_user:chat-a"],
            "interrupted_binding_ids": [],
            "fail_closed_request_count": 0,
            "purged_thread_ids": ["thread-1"],
            "app_server_url": "ws://127.0.0.1:8765",
        }

    def get_runtime_view(self, sender_id: str, chat_id: str, message_id: str):
        self.runtime_view_calls.append((sender_id, chat_id, message_id))
        return self.runtime

    def update_runtime_settings(self, sender_id: str, chat_id: str, **kwargs: Any) -> None:
        self.update_calls.append((sender_id, chat_id, kwargs))

    def safe_read_runtime_config(self) -> RuntimeConfigSummary | None:
        return self.runtime_config

    def list_local_profile_names(self) -> list[str]:
        return list(self.local_profile_names)

    def read_thread_summary(self, thread_id: str) -> ThreadSummary:
        if thread_id in self.read_thread_errors:
            raise self.read_thread_errors[thread_id]
        return self.thread_summaries[thread_id]

    def clear_thread_binding(self, sender_id: str, chat_id: str, message_id: str) -> None:
        self.cleared_thread_bindings.append((sender_id, chat_id, message_id))
        self.runtime.current_thread_id = ""

    @staticmethod
    def is_thread_not_found_error(exc: Exception) -> bool:
        return isinstance(exc, FileNotFoundError)


def _make_domain(stub: _SettingsPortsStub) -> CodexSettingsDomain:
    return CodexSettingsDomain(
        ports=SettingsDomainPorts(
            get_message_context=stub.get_message_context,
            get_sender_display_name=stub.get_sender_display_name,
            debug_sender_name_resolution=stub.debug_sender_name_resolution,
            get_bot_identity_snapshot=stub.get_bot_identity_snapshot,
            add_admin_open_id=stub.add_admin_open_id,
            set_configured_bot_open_id=stub.set_configured_bot_open_id,
            load_codex_config=stub.load_codex_config,
            save_codex_config=stub.save_codex_config,
            reset_current_instance_backend=stub.reset_current_instance_backend,
            get_runtime_view=stub.get_runtime_view,
            update_runtime_settings=stub.update_runtime_settings,
            safe_read_runtime_config=stub.safe_read_runtime_config,
            list_local_profile_names=stub.list_local_profile_names,
            read_thread_summary=stub.read_thread_summary,
            clear_thread_binding=stub.clear_thread_binding,
            is_thread_not_found_error=stub.is_thread_not_found_error,
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

    def test_profile_command_sets_managed_startup_profile_and_returns_card(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(stub.codex_config["managed_startup_profile"], "work")
        self.assertEqual(stub.runtime_view_calls, [])
        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex Backend Startup Profile")
        content = result.card["elements"][0]["content"]
        self.assertIn("已设置当前实例的 startup profile：`work`", content)
        self.assertIn("该设置会在下次 managed backend 启动时生效。", content)
        self.assertIn("当前实例 startup profile：`work`", content)

    def test_profile_command_without_arg_shows_startup_profile_summary(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex Backend Startup Profile")
        content = result.card["elements"][0]["content"]
        self.assertIn("当前实例 startup profile：`auto`", content)
        self.assertIn("作用范围：managed backend 的启动基线。", content)
        self.assertIn("如需让当前实例马上切到这套基线，请重置 backend。", content)

    def test_profile_command_falls_back_to_local_profile_names_when_runtime_config_unreadable(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime_config = None
        stub.local_profile_names = ["work", "zai"]
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前未能读取 live runtime config", content)
        profile_buttons = result.card["elements"][2]["actions"]
        self.assertEqual(
            [action["text"]["content"] for action in profile_buttons],
            ["work", "zai"],
        )

    def test_profile_command_short_circuits_when_target_already_current(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(stub.codex_config["managed_startup_profile"], "work")
        self.assertIsNotNone(result.card)
        self.assertIn("当前实例的 startup profile 已是：`work`", result.card["elements"][0]["content"])

    def test_profile_command_can_switch_to_profile_named_clear(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime_config = RuntimeConfigSummary(
            profiles=[
                RuntimeProfileSummary(name="clear", model_provider="clear-provider"),
                RuntimeProfileSummary(name="work", model_provider="anthropic"),
            ],
        )
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "clear", message_id="msg-1")

        self.assertEqual(stub.codex_config["managed_startup_profile"], "clear")
        self.assertIsNotNone(result.card)
        self.assertIn("已设置当前实例的 startup profile：`clear`", result.card["elements"][0]["content"])

    def test_profile_command_allows_unbound_runtime(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime.current_thread_id = ""
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(stub.codex_config["managed_startup_profile"], "work")
        self.assertIsNotNone(result.card)

    def test_profile_command_can_still_switch_when_runtime_config_unreadable(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime_config = None
        stub.local_profile_names = ["work"]
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(stub.codex_config["managed_startup_profile"], "work")
        self.assertIsNotNone(result.card)
        self.assertIn("已设置当前实例的 startup profile：`work`", result.card["elements"][0]["content"])

    def test_profile_command_rejects_unknown_profile_name(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "missing", message_id="msg-1")

        self.assertIn("未找到 profile：`missing`", result.text)
        self.assertNotIn("managed_startup_profile", stub.codex_config)

    def test_profile_command_fail_open_summary_still_allows_clear_when_no_local_profiles(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime_config = None
        stub.local_profile_names = []
        stub.codex_config["managed_startup_profile"] = "broken"
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前实例 startup profile：`broken`", content)
        self.assertIn("仍可直接执行 `/profile-clear`", content)

    def test_profile_command_rejects_in_remote_mode(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["app_server_mode"] = "remote"
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertIn("当前实例使用的是 remote app-server", result.text)
        self.assertNotIn("managed_startup_profile", stub.codex_config)

    def test_apply_profile_with_backend_reset_saves_profile_after_reset(self) -> None:
        stub = _SettingsPortsStub()

        def _reset_backend(force: bool) -> dict[str, Any]:
            stub.reset_backend_calls.append(bool(force))
            return {
                "force": bool(force),
                "detached_binding_ids": ["p2p:ou_user:chat-a"],
                "interrupted_binding_ids": [],
                "fail_closed_request_count": 0,
                "purged_thread_ids": ["thread-1"],
                "app_server_url": "ws://127.0.0.1:8765",
            }

        stub.reset_current_instance_backend = _reset_backend
        domain = _make_domain(stub)

        response = domain.handle_apply_profile_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"profile": "work", "force": False},
        )

        self.assertEqual(stub.codex_config["managed_startup_profile"], "work")
        self.assertEqual(stub.reset_backend_calls, [False])
        self.assertEqual(response.toast.type, "success")
        self.assertIn("已应用 `work` 并重置 backend", response.toast.content)
        self.assertIn("已重置当前实例 backend。", response.card.data["elements"][0]["content"])
        attach_actions = response.card.data["elements"][-1]["actions"]
        self.assertEqual(
            [action["text"]["content"] for action in attach_actions],
            ["附着当前线程", "附着当前实例", "保持 detached"],
        )

    def test_apply_profile_with_backend_reset_can_reapply_same_current_profile(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"
        domain = _make_domain(stub)

        response = domain.handle_apply_profile_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"profile": "work", "force": False},
        )

        self.assertEqual(stub.reset_backend_calls, [False])
        self.assertEqual(response.toast.type, "success")
        self.assertIn("已应用 `work` 并重置 backend", response.toast.content)

    def test_apply_profile_with_backend_reset_clears_provisional_binding(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"
        with tempfile.TemporaryDirectory() as tmpdir:
            provisional_path = Path(tmpdir) / "missing-rollout"
            stub.thread_summaries["thread-1"] = ThreadSummary(
                thread_id="thread-1",
                cwd=str(Path(tmpdir)),
                name="demo",
                preview="",
                created_at=0,
                updated_at=0,
                source="appServer",
                status="idle",
                path=str(provisional_path),
            )
            domain = _make_domain(stub)

            response = domain.handle_apply_profile_with_backend_reset(
                "ou_user",
                "chat-a",
                "msg-1",
                {"profile": "work", "force": False},
            )

        self.assertEqual(stub.cleared_thread_bindings, [("ou_user", "chat-a", "msg-1")])
        self.assertIn("provisional shell", response.card.data["elements"][0]["content"])
        attach_actions = response.card.data["elements"][-1]["actions"]
        self.assertEqual(
            [action["text"]["content"] for action in attach_actions],
            ["附着当前实例", "保持 detached"],
        )

    def test_profile_clear_direct_write_clears_current_profile(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"
        domain = _make_domain(stub)

        result = domain.handle_profile_clear_command("ou_user", "chat-a", message_id="msg-1")

        self.assertNotIn("managed_startup_profile", stub.codex_config)
        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("已清空当前实例的 startup profile override。", content)
        self.assertIn("当前将回落到 `CODEX_HOME/config.toml` 顶层配置。", content)

    def test_profile_clear_works_when_runtime_config_unreadable(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime_config = None
        stub.local_profile_names = []
        stub.codex_config["managed_startup_profile"] = "broken"
        domain = _make_domain(stub)

        result = domain.handle_profile_clear_command("ou_user", "chat-a", message_id="msg-1")

        self.assertNotIn("managed_startup_profile", stub.codex_config)
        self.assertIsNotNone(result.card)
        self.assertIn("已清空当前实例的 startup profile override。", result.card["elements"][0]["content"])

    def test_profile_clear_without_existing_profile_is_noop(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_profile_clear_command("ou_user", "chat-a", message_id="msg-1")

        self.assertIsNotNone(result.card)
        self.assertIn("当前实例未设置 startup profile。", result.card["elements"][0]["content"])

    def test_profile_clear_command_rejects_extra_args(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_profile_clear_command("ou_user", "chat-a", "extra", message_id="msg-1")

        self.assertIn("用法：`/profile-clear`", result.text)
        self.assertIn("不接受额外参数", result.text)

    def test_profile_clear_rejects_in_remote_mode(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["app_server_mode"] = "remote"
        stub.codex_config["managed_startup_profile"] = "work"
        domain = _make_domain(stub)

        result = domain.handle_profile_clear_command("ou_user", "chat-a", message_id="msg-1")

        self.assertIn("当前实例使用的是 remote app-server", result.text)
        self.assertEqual(stub.codex_config["managed_startup_profile"], "work")

    def test_clear_profile_with_backend_reset_clears_profile_after_reset(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"

        def _reset_backend(force: bool) -> dict[str, Any]:
            stub.reset_backend_calls.append(bool(force))
            return {
                "force": bool(force),
                "detached_binding_ids": ["p2p:ou_user:chat-a"],
                "interrupted_binding_ids": [],
                "fail_closed_request_count": 0,
                "purged_thread_ids": ["thread-1"],
                "app_server_url": "ws://127.0.0.1:8765",
            }

        stub.reset_current_instance_backend = _reset_backend
        domain = _make_domain(stub)

        response = domain.handle_clear_profile_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"force": False},
        )

        self.assertEqual(stub.reset_backend_calls, [False])
        self.assertNotIn("managed_startup_profile", stub.codex_config)
        self.assertEqual(response.toast.type, "success")
        self.assertIn("已清空当前实例的 startup profile 并重置 backend", response.toast.content)
        content = response.card.data["elements"][0]["content"]
        self.assertIn("已清空当前实例的 startup profile override。", content)
        self.assertIn("已重置当前实例 backend。", content)
        attach_actions = response.card.data["elements"][-1]["actions"]
        self.assertEqual(
            [action["text"]["content"] for action in attach_actions],
            ["附着当前线程", "附着当前实例", "保持 detached"],
        )

    def test_profile_summary_card_uses_profile_specific_reset_actions(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        action_rows = [
            element["actions"]
            for element in result.card["elements"]
            if isinstance(element, dict) and element.get("tag") == "action"
        ]
        reset_actions = action_rows[1]
        self.assertEqual(reset_actions[0]["value"]["action"], "apply_profile_with_backend_reset")
        self.assertEqual(reset_actions[1]["value"]["action"], "apply_profile_with_backend_reset")
        followup_actions = action_rows[2]
        self.assertEqual(followup_actions[0]["value"]["action"], "clear_profile")
        self.assertEqual(followup_actions[1]["value"]["action"], "clear_profile_with_backend_reset")

    def test_model_command_without_arg_shows_model_summary_card(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"
        domain = _make_domain(stub)

        result = domain.handle_model_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex 模型 / Effort")
        content = result.card["elements"][0]["content"]
        self.assertIn("当前会话 model override：`auto`", content)
        self.assertIn("当前会话 effort override：`auto`", content)
        self.assertIn("当前实例 startup profile：`work`", content)
        self.assertIn("当前 effective effort 来源：backend default / model default", content)
        action_buttons = next(
            element["actions"]
            for element in result.card["elements"]
            if isinstance(element, dict) and element.get("tag") == "action"
        )
        self.assertEqual(action_buttons[0]["text"]["content"], "✓ auto")

    def test_model_command_updates_only_runtime_model_override(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_model_command("ou_user", "chat-a", "gpt-5.4", message_id="msg-1")

        self.assertIn("已切换当前会话的 model override：`gpt-5.4`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "model": "gpt-5.4"})],
        )

    def test_model_command_auto_clears_runtime_override(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime.model = "gpt-5.5"
        domain = _make_domain(stub)

        result = domain.handle_model_command("ou_user", "chat-a", "auto", message_id="msg-1")

        self.assertIn("已切换当前会话的 model override：`auto`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "model": ""})],
        )

    def test_model_command_accepts_arbitrary_non_empty_model_name(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_model_command("ou_user", "chat-a", "glm-4.5", message_id="msg-1")

        self.assertIn("已切换当前会话的 model override：`glm-4.5`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "model": "glm-4.5"})],
        )

    def test_resolve_runtime_settings_form_submit_payload_recognizes_model_form(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        payload = domain.resolve_runtime_settings_form_submit_payload(
            {"_form_value": {"model_override": "glm-4.5"}}
        )

        self.assertEqual(payload, {"action": "submit_model_override"})

    def test_effort_command_without_arg_shows_combined_card(self) -> None:
        stub = _SettingsPortsStub()
        stub.codex_config["managed_startup_profile"] = "work"
        domain = _make_domain(stub)

        result = domain.handle_effort_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex 模型 / Effort")
        self.assertIn("当前会话 effort override：`auto`", result.card["elements"][0]["content"])
        self.assertIn("当前实例 startup profile：`work`", result.card["elements"][0]["content"])
        self.assertIn("当前 effective effort 来源：backend default / model default", result.card["elements"][0]["content"])

    def test_effort_command_updates_runtime_override(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_effort_command("ou_user", "chat-a", "high", message_id="msg-1")

        self.assertIn("已切换当前会话的 effort override：`high`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "reasoning_effort": "high"})],
        )

    def test_effort_command_auto_clears_runtime_override(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime.reasoning_effort = "medium"
        domain = _make_domain(stub)

        result = domain.handle_effort_command("ou_user", "chat-a", "auto", message_id="msg-1")

        self.assertIn("已切换当前会话的 effort override：`auto`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "reasoning_effort": ""})],
        )

    def test_effort_command_rejects_unknown_value(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_effort_command("ou_user", "chat-a", "extreme", message_id="msg-1")

        self.assertIn("非法 reasoning effort：`extreme`", result.text)
        self.assertEqual(stub.update_calls, [])

    def test_approval_command_updates_only_approval_policy(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_approval_command("ou_user", "chat-a", "never", message_id="msg-1")

        self.assertIn("已切换审批策略：`never`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "approval_policy": "never"})],
        )

    def test_permissions_command_updates_permissions_profile_only(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_permissions_command(
            "ou_user",
            "chat-a",
            "danger-full-access",
            message_id="msg-1",
        )

        self.assertIn("已切换权限基线：`Danger Full Access`", result.text)
        self.assertEqual(
            stub.update_calls,
            [
                (
                    "ou_user",
                    "chat-a",
                    {
                        "message_id": "msg-1",
                        "permissions_profile_id": ":danger-full-access",
                    },
                )
            ],
        )

    def test_collab_mode_command_updates_only_collaboration_mode(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_collab_mode_command("ou_user", "chat-a", "plan", message_id="msg-1")

        self.assertIn("已切换协作模式：`plan`", result.text)
        self.assertEqual(
            stub.update_calls,
            [("ou_user", "chat-a", {"message_id": "msg-1", "collaboration_mode": "plan"})],
        )


if __name__ == "__main__":
    unittest.main()
