import unittest
from types import SimpleNamespace
from typing import Any

from bot.adapters.base import RuntimeConfigSummary, RuntimeProfileSummary
from bot.codex_config_reader import ResolvedProfileConfig
from bot.codex_settings_domain import (
    CodexSettingsDomain,
    ThreadResetReplacement,
    SettingsDomainPorts,
)
from bot.feishu_command_syntax import feishu_visible_command_syntax
from bot.stores.thread_memory_mode_store import ThreadMemoryModeRecord
from bot.stores.thread_resume_profile_store import ThreadResumeProfileRecord


_APPROVAL_POLICIES = {"untrusted", "on-request", "never"}
_SANDBOX_POLICIES = {"read-only", "workspace-write", "danger-full-access"}
_PERMISSIONS_PRESETS = {
    "read-only": {
        "label": "Read Only",
        "approval_policy": "on-request",
        "sandbox": "read-only",
    },
    "default": {
        "label": "Default",
        "approval_policy": "on-request",
        "sandbox": "workspace-write",
    },
    "full-access": {
        "label": "Full Access",
        "approval_policy": "never",
        "sandbox": "danger-full-access",
    },
}
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
            sandbox="workspace-write",
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
        self.new_thread_memory_mode_seed = "read"
        self.saved_thread_profiles: list[tuple[str, str, str, str]] = []
        self.current_thread_profile: ThreadResumeProfileRecord | None = None
        self.applied_thread_memory_modes: list[tuple[str, str]] = []
        self.current_thread_memory_mode: ThreadMemoryModeRecord | None = None
        self.thread_profile_mutable = (True, "")
        self.thread_memory_mode_mutable = (True, "")
        self.thread_reprofile_plan = SimpleNamespace(
            status="direct-write",
            reason_text="",
            diagnostics=(),
        )
        self.thread_memory_plan = SimpleNamespace(
            status="direct-write",
            reason_text="",
            diagnostics=(),
        )
        self.reset_backend_calls: list[bool] = []
        self.replacement_result: ThreadResetReplacement | None = None
        self.replacement_calls: list[tuple[str, str, str, str, str]] = []
        self.runtime_view_calls: list[tuple[str, str, str]] = []
        self.update_calls: list[tuple[str, str, dict[str, Any]]] = []
        self.resolution_calls: list[RuntimeConfigSummary | None] = []
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

    def load_thread_resume_profile(self, thread_id: str) -> ThreadResumeProfileRecord | None:
        if self.current_thread_profile is None:
            return None
        if self.current_thread_profile.thread_id != thread_id:
            return None
        return self.current_thread_profile

    def save_thread_resume_profile(
        self,
        thread_id: str,
        profile: str,
        model: str,
        model_provider: str,
    ) -> ThreadResumeProfileRecord:
        self.saved_thread_profiles.append((thread_id, profile, model, model_provider))
        self.current_thread_profile = ThreadResumeProfileRecord(
            thread_id=thread_id,
            profile=profile,
            model=model,
            model_provider=model_provider,
            updated_at=1.0,
        )
        return self.current_thread_profile

    def check_thread_resume_profile_mutable(self, thread_id: str) -> tuple[bool, str]:
        del thread_id
        return self.thread_profile_mutable

    def check_thread_memory_mode_mutable(self, thread_id: str) -> tuple[bool, str]:
        del thread_id
        return self.thread_memory_mode_mutable

    def load_thread_memory_mode(self, thread_id: str) -> ThreadMemoryModeRecord | None:
        if self.current_thread_memory_mode is None:
            return None
        if self.current_thread_memory_mode.thread_id != thread_id:
            return None
        return self.current_thread_memory_mode

    def apply_thread_memory_mode(self, thread_id: str, mode: str) -> ThreadMemoryModeRecord:
        self.applied_thread_memory_modes.append((thread_id, mode))
        self.current_thread_memory_mode = ThreadMemoryModeRecord(
            thread_id=thread_id,
            mode=mode,
            updated_at=1.0,
        )
        return self.current_thread_memory_mode

    def plan_thread_reprofile(self, thread_id: str):
        del thread_id
        return self.thread_reprofile_plan

    def plan_thread_memory_mode_update(self, thread_id: str):
        del thread_id
        return self.thread_memory_plan

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

    def replace_bound_provisional_thread_after_reset(
        self,
        sender_id: str,
        chat_id: str,
        target_profile: str,
        target_memory_mode: str,
        message_id: str,
    ) -> ThreadResetReplacement | None:
        self.replacement_calls.append((sender_id, chat_id, target_profile, target_memory_mode, message_id))
        if self.replacement_result is not None:
            self.runtime.current_thread_id = self.replacement_result.new_thread_id
        return self.replacement_result

    def resolve_profile_resume_config(self, profile: str) -> ResolvedProfileConfig:
        return ResolvedProfileConfig(
            model=f"{profile}-model",
            model_provider=f"{profile}-provider",
        )

    def get_runtime_view(self, sender_id: str, chat_id: str, message_id: str):
        self.runtime_view_calls.append((sender_id, chat_id, message_id))
        return self.runtime

    def update_runtime_settings(self, sender_id: str, chat_id: str, **kwargs: Any) -> None:
        self.update_calls.append((sender_id, chat_id, kwargs))

    def safe_read_runtime_config(self) -> RuntimeConfigSummary | None:
        return self.runtime_config

    def get_new_thread_memory_mode_seed(self) -> str:
        return self.new_thread_memory_mode_seed


def _make_domain(stub: _SettingsPortsStub) -> CodexSettingsDomain:
    return CodexSettingsDomain(
        ports=SettingsDomainPorts(
            get_message_context=stub.get_message_context,
            get_sender_display_name=stub.get_sender_display_name,
            debug_sender_name_resolution=stub.debug_sender_name_resolution,
            get_bot_identity_snapshot=stub.get_bot_identity_snapshot,
            add_admin_open_id=stub.add_admin_open_id,
            set_configured_bot_open_id=stub.set_configured_bot_open_id,
            load_thread_resume_profile=stub.load_thread_resume_profile,
            save_thread_resume_profile=stub.save_thread_resume_profile,
            load_thread_memory_mode=stub.load_thread_memory_mode,
            apply_thread_memory_mode=stub.apply_thread_memory_mode,
            check_thread_resume_profile_mutable=stub.check_thread_resume_profile_mutable,
            check_thread_memory_mode_mutable=stub.check_thread_memory_mode_mutable,
            plan_thread_reprofile=stub.plan_thread_reprofile,
            plan_thread_memory_mode_update=stub.plan_thread_memory_mode_update,
            reset_current_instance_backend=stub.reset_current_instance_backend,
            replace_bound_provisional_thread_after_reset=stub.replace_bound_provisional_thread_after_reset,
            resolve_profile_resume_config=stub.resolve_profile_resume_config,
            get_runtime_view=stub.get_runtime_view,
            update_runtime_settings=stub.update_runtime_settings,
            safe_read_runtime_config=stub.safe_read_runtime_config,
            get_new_thread_memory_mode_seed=stub.get_new_thread_memory_mode_seed,
        ),
        approval_policies=_APPROVAL_POLICIES,
        sandbox_policies=_SANDBOX_POLICIES,
        permissions_presets=_PERMISSIONS_PRESETS,
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

    def test_profile_command_saves_bound_thread_profile_via_port_and_returns_card(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(
            stub.saved_thread_profiles,
            [("thread-1", "work", "work-model", "work-provider")],
        )
        self.assertEqual(stub.runtime_view_calls, [("ou_user", "chat-a", "msg-1")])
        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex Thread Profile")
        content = result.card["elements"][0]["content"]
        self.assertIn("已切换当前 thread 的 profile：`work`", content)
        action_buttons = result.card["elements"][2]["actions"]
        buttons_by_profile = {button["text"]["content"]: button for button in action_buttons}
        self.assertEqual(buttons_by_profile["work"]["type"], "primary")

    def test_profile_command_offers_backend_reset_when_thread_not_globally_unloaded(self) -> None:
        stub = _SettingsPortsStub()
        stub.thread_reprofile_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 profile。",
            diagnostics=("当前实例：`default`",),
        )
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(stub.saved_thread_profiles, [])
        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前还不能直接切换到 `work`。", content)
        self.assertIn("可继续执行：应用该 profile，并重置当前实例 backend。", content)
        self.assertIn("当前不能直接写入：当前 thread 尚未满足 verifiably globally unloaded", content)
        reset_action = result.card["elements"][-1]["actions"]
        self.assertEqual(
            [button["text"]["content"] for button in reset_action],
            ["应用并重置 backend"],
        )

    def test_profile_command_short_circuits_when_target_already_persisted(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_profile = ThreadResumeProfileRecord(
            thread_id="thread-1",
            profile="work",
            model="work-model",
            model_provider="work-provider",
            updated_at=1.0,
        )
        stub.thread_reprofile_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 profile。",
            diagnostics=(),
        )
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(stub.saved_thread_profiles, [])
        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前 thread 的 profile 已是：`work`", content)
        self.assertIn("无需重置 backend", content)
        self.assertNotIn("应用并重置 backend", content)

    def test_profile_command_same_profile_name_but_changed_setting_direct_writes_when_unloaded(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_profile = ThreadResumeProfileRecord(
            thread_id="thread-1",
            profile="work",
            model="work-model",
            model_provider="old-provider",
            updated_at=1.0,
        )
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(
            stub.saved_thread_profiles,
            [("thread-1", "work", "work-model", "work-provider")],
        )
        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("已切换当前 thread 的 profile：`work`", content)

    def test_profile_command_same_profile_name_but_changed_setting_offers_reset_when_loaded(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_profile = ThreadResumeProfileRecord(
            thread_id="thread-1",
            profile="work",
            model="work-model",
            model_provider="old-provider",
            updated_at=1.0,
        )
        stub.thread_reprofile_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 profile。",
            diagnostics=(),
        )
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertEqual(stub.saved_thread_profiles, [])
        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前同名 profile 的 thread 级 next-load 设置已变化：", content)
        self.assertIn("provider：`old-provider` -> `work-provider`", content)
        self.assertIn("应用该 profile，并重置当前实例 backend", content)

    def test_apply_profile_with_backend_reset_saves_profile_after_reset(self) -> None:
        stub = _SettingsPortsStub()
        stub.thread_reprofile_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 profile。",
            diagnostics=(),
        )

        def _reset_backend(force: bool) -> dict[str, Any]:
            stub.reset_backend_calls.append(bool(force))
            stub.thread_reprofile_plan = SimpleNamespace(
                status="direct-write",
                reason_text="当前 thread 已 verifiably globally unloaded，可直接写入 profile。",
                diagnostics=(),
            )
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

        self.assertEqual(stub.reset_backend_calls, [False])
        self.assertEqual(
            stub.saved_thread_profiles,
            [("thread-1", "work", "work-model", "work-provider")],
        )
        self.assertEqual(response.toast.type, "success")
        self.assertIn("已应用 `work` 并重置 backend", response.toast.content)
        self.assertIsNotNone(response.card)
        self.assertEqual(stub.replacement_calls, [("ou_user", "chat-a", "work", "", "msg-1")])

    def test_apply_profile_with_backend_reset_recomputes_setting_from_refreshed_runtime_config(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime_config = RuntimeConfigSummary(
            profiles=[
                RuntimeProfileSummary(name="default", model_provider="openai"),
                RuntimeProfileSummary(name="work", model_provider="old-provider"),
            ],
        )
        stub.thread_reprofile_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 profile。",
            diagnostics=(),
        )

        def _resolve_profile(profile: str) -> ResolvedProfileConfig:
            return ResolvedProfileConfig(
                model=f"{profile}-model",
                model_provider="",
            )

        def _reset_backend(force: bool) -> dict[str, Any]:
            stub.reset_backend_calls.append(bool(force))
            stub.thread_reprofile_plan = SimpleNamespace(
                status="direct-write",
                reason_text="当前 thread 已 verifiably globally unloaded，可直接写入 profile。",
                diagnostics=(),
            )
            stub.runtime_config = RuntimeConfigSummary(
                profiles=[
                    RuntimeProfileSummary(name="default", model_provider="openai"),
                    RuntimeProfileSummary(name="work", model_provider="new-provider"),
                ],
            )
            return {
                "force": bool(force),
                "detached_binding_ids": ["p2p:ou_user:chat-a"],
                "interrupted_binding_ids": [],
                "fail_closed_request_count": 0,
                "purged_thread_ids": ["thread-1"],
                "app_server_url": "ws://127.0.0.1:8765",
            }

        stub.resolve_profile_resume_config = _resolve_profile
        stub.reset_current_instance_backend = _reset_backend
        domain = _make_domain(stub)

        response = domain.handle_apply_profile_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"profile": "work", "force": False},
        )

        self.assertEqual(stub.reset_backend_calls, [False])
        self.assertEqual(
            stub.saved_thread_profiles,
            [("thread-1", "work", "work-model", "new-provider")],
        )
        self.assertEqual(response.toast.type, "success")

    def test_apply_profile_with_backend_reset_short_circuits_when_target_already_persisted(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_profile = ThreadResumeProfileRecord(
            thread_id="thread-1",
            profile="work",
            model="work-model",
            model_provider="work-provider",
            updated_at=1.0,
        )
        stub.thread_reprofile_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 profile。",
            diagnostics=(),
        )
        domain = _make_domain(stub)

        response = domain.handle_apply_profile_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"profile": "work", "force": False},
        )

        self.assertEqual(stub.reset_backend_calls, [])
        self.assertEqual(response.toast.type, "success")
        self.assertIn("当前 thread 的 profile 已是：work", response.toast.content)

    def test_apply_profile_with_backend_reset_replaces_provisional_thread(self) -> None:
        stub = _SettingsPortsStub()
        stub.thread_reprofile_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 profile。",
            diagnostics=(),
        )

        def _replace(
            sender_id: str,
            chat_id: str,
            target_profile: str,
            target_memory_mode: str,
            message_id: str,
        ):
            stub.replacement_calls.append((sender_id, chat_id, target_profile, target_memory_mode, message_id))
            stub.runtime.current_thread_id = "thread-2"
            stub.current_thread_profile = ThreadResumeProfileRecord(
                thread_id="thread-2",
                profile="work",
                model="work-model",
                model_provider="work-provider",
                updated_at=2.0,
            )
            stub.thread_reprofile_plan = SimpleNamespace(
                status="direct-write",
                reason_text="当前 thread 已 verifiably globally unloaded，可直接写入 profile。",
                diagnostics=(),
            )
            return ThreadResetReplacement(
                old_thread_id="thread-1",
                new_thread_id="thread-2",
            )

        stub.replace_bound_provisional_thread_after_reset = _replace
        domain = _make_domain(stub)

        response = domain.handle_apply_profile_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"profile": "work", "force": False},
        )

        self.assertEqual(stub.saved_thread_profiles, [])
        self.assertEqual(stub.replacement_calls, [("ou_user", "chat-a", "work", "", "msg-1")])
        self.assertEqual(response.toast.type, "success")
        content = response.card.data["elements"][0]["content"]
        self.assertIn("已替换为新 thread：`thread-2", content)
        self.assertIn("当前会话已自动附着到新 thread", response.card.data["elements"][-2]["content"])
        actions = response.card.data["elements"][-1]["actions"]
        self.assertEqual([action["text"]["content"] for action in actions], ["附着当前实例", "保持当前状态"])

    def test_profile_command_rejects_when_unbound(self) -> None:
        stub = _SettingsPortsStub()
        stub.runtime.current_thread_id = ""
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertIn("当前还没有绑定 thread", result.text)
        self.assertEqual(stub.saved_thread_profiles, [])

    def test_profile_command_rejects_when_explicit_profile_cannot_resolve_concrete_slice(self) -> None:
        stub = _SettingsPortsStub()
        stub.resolve_profile_resume_config = lambda profile: ResolvedProfileConfig(
            model=f"{profile}-model",
            model_provider="",
        )
        stub.runtime_config = RuntimeConfigSummary(
            profiles=[RuntimeProfileSummary(name="work", model_provider="")]
        )
        domain = _make_domain(stub)

        result = domain.handle_profile_command("ou_user", "chat-a", "work", message_id="msg-1")

        self.assertIn("thread-wise profile slice 不完整", result.text)
        self.assertIn("`model_provider`", result.text)
        self.assertIn("`CODEX_HOME/config.toml`", result.text)
        self.assertEqual(stub.saved_thread_profiles, [])

    def test_memory_command_applies_direct_write_and_returns_summary_card(self) -> None:
        stub = _SettingsPortsStub()
        domain = _make_domain(stub)

        result = domain.handle_memory_command("ou_user", "chat-a", "read", message_id="msg-1")

        self.assertEqual(stub.applied_thread_memory_modes, [("thread-1", "read")])
        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex Thread Memory Mode")
        content = result.card["elements"][0]["content"]
        self.assertIn("已切换当前 thread 的 memory mode：`read`", content)
        action_buttons = result.card["elements"][2]["actions"]
        buttons_by_mode = {button["text"]["content"]: button for button in action_buttons}
        self.assertEqual(buttons_by_mode["read"]["type"], "primary")

    def test_memory_command_offers_backend_reset_when_thread_not_globally_unloaded(self) -> None:
        stub = _SettingsPortsStub()
        stub.thread_memory_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            diagnostics=("当前实例：`default`",),
        )
        domain = _make_domain(stub)

        result = domain.handle_memory_command("ou_user", "chat-a", "read_write", message_id="msg-1")

        self.assertEqual(stub.applied_thread_memory_modes, [])
        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前还不能直接切换到 `read_write`。", content)
        self.assertIn("可继续执行：应用该 memory mode，并重置当前实例 backend。", content)
        reset_action = result.card["elements"][-1]["actions"]
        self.assertEqual(
            [button["text"]["content"] for button in reset_action],
            ["应用并重置 backend"],
        )

    def test_memory_command_short_circuits_when_target_already_persisted(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_memory_mode = ThreadMemoryModeRecord(
            thread_id="thread-1",
            mode="read",
            updated_at=1.0,
        )
        stub.thread_memory_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            diagnostics=(),
        )
        domain = _make_domain(stub)

        result = domain.handle_memory_command("ou_user", "chat-a", "read", message_id="msg-1")

        self.assertEqual(stub.applied_thread_memory_modes, [])
        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前 thread 的 memory mode 已是：`read`", content)
        self.assertIn("无需重置 backend", content)
        self.assertNotIn("应用并重置 backend", content)

    def test_memory_command_without_arg_shows_effective_codex_memory_mode_when_threadwise_unset(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_memory_mode = None
        stub.runtime_config = RuntimeConfigSummary(
            profiles=[
                RuntimeProfileSummary(name="default", model_provider="openai"),
                RuntimeProfileSummary(name="work", model_provider="anthropic"),
            ],
            current_memory_mode="read_write",
        )
        domain = _make_domain(stub)

        result = domain.handle_memory_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        content = result.card["elements"][0]["content"]
        self.assertIn("当前 thread-wise memory mode：`（未设置）`", content)
        self.assertIn("当前 thread 未设置时，沿用当前 Codex memory 配置：`read_write`。", content)
        self.assertIn("本实例 `new_thread_memory_mode_seed`：`read`（仅新建 thread 时注入）。", content)

    def test_model_command_without_arg_shows_model_summary_card(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_profile = ThreadResumeProfileRecord(
            thread_id="thread-1",
            profile="work",
            model="work-model",
            model_provider="work-provider",
            updated_at=1.0,
        )
        domain = _make_domain(stub)

        result = domain.handle_model_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex 模型 / Effort")
        content = result.card["elements"][0]["content"]
        self.assertIn("当前会话 model override：`auto`", content)
        self.assertIn("当前会话 effort override：`auto`", content)
        self.assertIn("当前 thread-wise profile：`work`", content)
        self.assertIn("当前 thread-wise provider：`work-provider`", content)
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
        self.assertEqual(stub.saved_thread_profiles, [])
        self.assertEqual(stub.applied_thread_memory_modes, [])

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
        domain = _make_domain(stub)

        result = domain.handle_effort_command("ou_user", "chat-a", "", message_id="msg-1")

        self.assertIsNotNone(result.card)
        self.assertEqual(result.card["header"]["title"]["content"], "Codex 模型 / Effort")
        self.assertIn("当前会话 effort override：`auto`", result.card["elements"][0]["content"])

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

    def test_apply_memory_mode_with_backend_reset_applies_after_reset(self) -> None:
        stub = _SettingsPortsStub()
        stub.thread_memory_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            diagnostics=(),
        )

        def _reset_backend(force: bool) -> dict[str, Any]:
            stub.reset_backend_calls.append(bool(force))
            stub.thread_memory_plan = SimpleNamespace(
                status="direct-write",
                reason_text="当前 thread 已 verifiably globally unloaded，可直接写入 memory mode。",
                diagnostics=(),
            )
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

        response = domain.handle_apply_memory_mode_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"mode": "read_write", "force": False},
        )

        self.assertEqual(stub.reset_backend_calls, [False])
        self.assertEqual(stub.applied_thread_memory_modes, [("thread-1", "read_write")])
        self.assertEqual(stub.replacement_calls, [("ou_user", "chat-a", "", "read_write", "msg-1")])
        self.assertEqual(response.toast.type, "success")
        self.assertIn("已应用 `read_write` 并重置 backend", response.toast.content)

    def test_apply_memory_mode_with_backend_reset_short_circuits_when_target_already_persisted(self) -> None:
        stub = _SettingsPortsStub()
        stub.current_thread_memory_mode = ThreadMemoryModeRecord(
            thread_id="thread-1",
            mode="read",
            updated_at=1.0,
        )
        stub.thread_memory_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            diagnostics=(),
        )
        domain = _make_domain(stub)

        response = domain.handle_apply_memory_mode_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"mode": "read", "force": False},
        )

        self.assertEqual(stub.reset_backend_calls, [])
        self.assertEqual(response.toast.type, "success")
        self.assertIn("当前 thread 的 memory mode 已是：read", response.toast.content)

    def test_apply_memory_mode_with_backend_reset_replaces_provisional_thread(self) -> None:
        stub = _SettingsPortsStub()
        stub.thread_memory_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            diagnostics=(),
        )

        def _replace(
            sender_id: str,
            chat_id: str,
            target_profile: str,
            target_memory_mode: str,
            message_id: str,
        ):
            stub.replacement_calls.append((sender_id, chat_id, target_profile, target_memory_mode, message_id))
            stub.runtime.current_thread_id = "thread-2"
            stub.current_thread_memory_mode = ThreadMemoryModeRecord(
                thread_id="thread-2",
                mode="read",
                updated_at=2.0,
            )
            stub.thread_memory_plan = SimpleNamespace(
                status="direct-write",
                reason_text="当前 thread 已 verifiably globally unloaded，可直接写入 memory mode。",
                diagnostics=(),
            )
            return ThreadResetReplacement(
                old_thread_id="thread-1",
                new_thread_id="thread-2",
            )

        stub.replace_bound_provisional_thread_after_reset = _replace
        domain = _make_domain(stub)

        response = domain.handle_apply_memory_mode_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"mode": "read", "force": False},
        )

        self.assertEqual(stub.applied_thread_memory_modes, [])
        self.assertEqual(stub.replacement_calls, [("ou_user", "chat-a", "", "read", "msg-1")])
        self.assertEqual(response.toast.type, "success")
        content = response.card.data["elements"][0]["content"]
        self.assertIn("已替换为新 thread：`thread-2", content)
        self.assertIn("当前会话已自动附着到新 thread", response.card.data["elements"][-2]["content"])
        actions = response.card.data["elements"][-1]["actions"]
        self.assertEqual([action["text"]["content"] for action in actions], ["附着当前实例", "保持当前状态"])

    def test_apply_memory_mode_with_backend_reset_uses_memory_specific_deny_reason(self) -> None:
        stub = _SettingsPortsStub()
        stub.thread_memory_plan = SimpleNamespace(
            status="reset-available",
            reason_text="当前 thread 尚未满足 verifiably globally unloaded；可通过 reset 当前实例 backend 后再写入 memory mode。",
            diagnostics=(),
        )
        stub.thread_memory_mode_mutable = (
            False,
            "当前 thread 仍处于 loaded 状态；当前不能直接改写该 thread 的 memory mode。请改用 `/memory <off|read|read_write>` 配合 reset-backend。",
        )
        domain = _make_domain(stub)

        response = domain.handle_apply_memory_mode_with_backend_reset(
            "ou_user",
            "chat-a",
            "msg-1",
            {"mode": "read", "force": False},
        )

        content = response.card.data["elements"][0]["content"]
        self.assertIn("backend 已重置，但当前仍不能写入目标 memory mode。", content)
        self.assertIn("/memory <off|read|read_write>", content)

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
