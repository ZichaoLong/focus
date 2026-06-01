import json
import os
import queue
import tempfile
import threading
import time
import unittest
from typing import get_type_hints
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedOK, InvalidStatus
from websockets.http11 import Response
from websockets.sync.client import connect
from websockets.sync.server import serve
from unittest.mock import ANY, Mock, patch
from io import StringIO
from pathlib import Path

from bot import process_utils
from bot.adapters.base import (
    RuntimeConfigSummary,
    RuntimeModelSummary,
    RuntimeProfileSummary,
    ThreadGoalSummary,
    ThreadSummary,
)
from bot.adapters.codex_app_server import CodexAppServerAdapter, CodexAppServerConfig
from bot.codex_config_reader import ResolvedProfileConfig
from bot.codex_command_resolver import DEFAULT_CODEX_COMMAND
from bot.codex_protocol.client import CodexRpcClient, CodexRpcError
from bot.fcodex import (
    _default_data_dir,
    _launch_local_cwd_proxy,
    _resolve_thread_target_via_remote_backend,
    main as fcodex_main,
)
from bot.fcodex_proxy import (
    _DEFAULT_IDLE_TIMEOUT_SECONDS,
    _ProxyInteractionGate,
    _ProxyRuntimeLeaseKeeper,
    _ProxyThreadSeedState,
    _relay_messages,
    _rewrite_thread_start_cwd,
    main as fcodex_proxy_main,
    run_proxy,
)
from bot.instance_resolution import (
    CliInstanceTarget,
    CliRuntimeTarget,
    resolve_cli_runtime_target,
    resolve_running_instance_app_server_url,
)
from bot.local_websocket_auth import (
    AppServerWebsocketAuthTokenStore,
    FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
    FCODEX_SERVICE_TOKEN_ENV_VAR,
    MissingAppServerWebsocketAuthTokenError,
)
from bot.service_control_plane import ServiceControlError
from bot.stores.instance_registry_store import InstanceRegistryEntry
from bot.stores.app_server_runtime_store import AppServerRuntimeStore, resolve_effective_app_server_url
from bot.stores.interaction_lease_store import InteractionLeaseStore, make_fcodex_interaction_holder
from bot.stores.thread_memory_mode_store import ThreadMemoryModeStore
from bot.stores.thread_resume_profile_store import ThreadResumeProfileRecord, ThreadResumeProfileStore
from bot.stores.thread_runtime_lease_store import ThreadRuntimeLease, ThreadRuntimeLeaseStore
from bot.thread_resolution import (
    format_thread_match,
    looks_like_thread_id,
    resolve_resume_target_by_name,
)
from bot.thread_resume_profile_setting import ThreadResumeProfileSetting
from bot.version import __version__


class _FakeRpc:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.default_model = "gpt-5.3-codex"
        self.stopped = False

    def request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        payload = params or {}
        self.calls.append((method, payload))
        if method == "model/list":
            return {
                "data": [
                    {"model": self.default_model, "isDefault": True, "hidden": False},
                    {"model": "gpt-5.4", "isDefault": False, "hidden": False},
                ]
            }
        if method == "config/read":
            return {
                "config": {
                    "modelProvider": "provider1_api",
                    "memories": {
                        "use_memories": True,
                        "generate_memories": False,
                    },
                },
                "layers": [
                    {
                        "name": {
                            "type": "user",
                            "file": "/tmp/.codex/work.config.toml",
                            "profile": "provider1",
                        },
                        "version": "v1",
                        "config": {},
                    }
                ],
            }
        if method in {"thread/start", "thread/resume"}:
            return {
                "thread": {
                    "id": "thread-1",
                    "cwd": "/tmp/project",
                    "name": "demo",
                    "preview": "hello",
                    "createdAt": 0,
                    "updatedAt": 0,
                    "source": "cli",
                    "status": {"type": "idle", "activeFlags": []},
                }
            }
        if method in {"thread/goal/get", "thread/goal/set"}:
            return {
                "goal": {
                    "threadId": "thread-1",
                    "objective": "ship goal support",
                    "status": "active",
                    "tokenBudget": 123,
                    "tokensUsed": 45,
                    "timeUsedSeconds": 67,
                    "createdAt": 1712476800,
                    "updatedAt": 1712476801,
                }
            }
        if method == "thread/goal/clear":
            return {"cleared": True}
        return {"ok": True}

    def stop(self) -> None:
        self.stopped = True


class _PermissionsUnsupportedRpc(_FakeRpc):
    def request(self, method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
        payload = params or {}
        if method in {"thread/start", "thread/resume", "thread/settings/update", "turn/start"} and "permissions" in payload:
            self.calls.append((method, payload))
            raise CodexRpcError(method, {"code": -32602, "message": "unknown field permissions"})
        return super().request(method, params, timeout=timeout)


class CodexAppServerAdapterTests(unittest.TestCase):
    def test_from_dict_normalizes_deprecated_approval_policy(self) -> None:
        config = CodexAppServerConfig.from_dict({"approval_policy": "on-failure"})

        self.assertEqual(config.approval_policy, "on-request")

    def test_from_dict_normalizes_new_thread_memory_mode_seed(self) -> None:
        config = CodexAppServerConfig.from_dict({"new_thread_memory_mode_seed": " read_write "})

        self.assertEqual(config.new_thread_memory_mode_seed, "read_write")

    def test_from_dict_rejects_removed_default_thread_memory_mode(self) -> None:
        with self.assertRaisesRegex(ValueError, "default_thread_memory_mode"):
            CodexAppServerConfig.from_dict({"default_thread_memory_mode": "read"})

    def test_create_thread_can_attach_profile_override(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        with patch(
            "bot.adapters.codex_app_server.resolve_profile_from_codex_config",
            return_value=ResolvedProfileConfig(model="provider2-model", model_provider="provider2_api"),
        ):
            adapter.create_thread(cwd="/tmp/project", profile="provider2")

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/start",
                {
                    "cwd": "/tmp/project",
                    "permissions": ":danger-full-access",
                    "approvalPolicy": "never",
                    "approvalsReviewer": "user",
                    "personality": "pragmatic",
                    "serviceName": "feishu-codex",
                    "model": "provider2-model",
                    "modelProvider": "provider2_api",
                },
            ),
        )

    def test_create_thread_merges_profile_with_memory_config_overrides(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        with patch(
            "bot.adapters.codex_app_server.resolve_profile_from_codex_config",
            return_value=ResolvedProfileConfig(model="provider2-model", model_provider="provider2_api"),
        ):
            adapter.create_thread(
                cwd="/tmp/project",
                profile="provider2",
                config_overrides={
                    "memories": {
                        "use_memories": True,
                        "generate_memories": False,
                    }
                }
            )

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/start",
                {
                    "cwd": "/tmp/project",
                    "permissions": ":danger-full-access",
                    "approvalPolicy": "never",
                    "approvalsReviewer": "user",
                    "personality": "pragmatic",
                    "serviceName": "feishu-codex",
                    "model": "provider2-model",
                    "modelProvider": "provider2_api",
                    "config": {
                        "memories": {
                            "use_memories": True,
                            "generate_memories": False,
                        },
                    },
                },
            ),
        )

    def test_create_thread_can_attach_model_and_provider_hints(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.create_thread(
            cwd="/tmp/project",
            profile="provider2",
            model="gpt-5.4",
            model_provider="provider2_api",
        )

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/start",
                {
                    "cwd": "/tmp/project",
                    "permissions": ":danger-full-access",
                    "approvalPolicy": "never",
                    "approvalsReviewer": "user",
                    "personality": "pragmatic",
                    "serviceName": "feishu-codex",
                    "model": "gpt-5.4",
                    "modelProvider": "provider2_api",
                },
            ),
        )

    def test_create_thread_allows_permission_overrides(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.create_thread(
            cwd="/tmp/project",
            approval_policy="never",
            sandbox="danger-full-access",
        )

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/start",
                {
                    "cwd": "/tmp/project",
                    "permissions": ":danger-full-access",
                    "approvalPolicy": "never",
                    "approvalsReviewer": "user",
                    "personality": "pragmatic",
                    "serviceName": "feishu-codex",
                },
            ),
        )

    def test_create_thread_falls_back_to_legacy_sandbox_when_permissions_unsupported(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _PermissionsUnsupportedRpc()
        adapter._rpc = fake_rpc

        adapter.create_thread(cwd="/tmp/project")

        self.assertEqual(fake_rpc.calls[0][0], "thread/start")
        self.assertEqual(fake_rpc.calls[0][1]["permissions"], ":danger-full-access")
        self.assertEqual(fake_rpc.calls[1][0], "thread/start")
        self.assertNotIn("permissions", fake_rpc.calls[1][1])
        self.assertEqual(fake_rpc.calls[1][1]["sandbox"], "danger-full-access")

    def test_resume_thread_can_attach_profile_override(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        with patch(
            "bot.adapters.codex_app_server.resolve_profile_from_codex_config",
            return_value=ResolvedProfileConfig(model="provider2-model", model_provider="provider2_api"),
        ):
            adapter.resume_thread("thread-1", profile="provider2")

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/resume",
                {
                    "threadId": "thread-1",
                    "model": "provider2-model",
                    "modelProvider": "provider2_api",
                },
            ),
        )

    def test_resume_thread_can_attach_model_and_provider_hints(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.resume_thread(
            "thread-1",
            model="gpt-5.4",
            model_provider="provider2_api",
        )

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/resume",
                {
                    "threadId": "thread-1",
                    "model": "gpt-5.4",
                    "modelProvider": "provider2_api",
                },
            ),
        )

    def test_resume_thread_merges_profile_with_memory_config_overrides(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        with patch(
            "bot.adapters.codex_app_server.resolve_profile_from_codex_config",
            return_value=ResolvedProfileConfig(model="provider2-model", model_provider="provider2_api"),
        ):
            adapter.resume_thread(
                "thread-1",
                profile="provider2",
                config_overrides={
                    "memories": {
                        "use_memories": True,
                        "generate_memories": True,
                    }
                }
            )

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/resume",
                {
                    "threadId": "thread-1",
                    "model": "provider2-model",
                    "modelProvider": "provider2_api",
                    "config": {
                        "memories": {
                            "use_memories": True,
                            "generate_memories": True,
                        },
                    },
                },
            ),
        )

    def test_resume_thread_can_attach_runtime_permission_overrides(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.resume_thread(
            "thread-1",
            approval_policy="on-request",
            permissions_profile_id=":workspace",
        )

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/resume",
                {
                    "threadId": "thread-1",
                    "approvalPolicy": "on-request",
                    "permissions": ":workspace",
                },
            ),
        )

    def test_resume_thread_falls_back_to_legacy_sandbox_when_permissions_unsupported(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _PermissionsUnsupportedRpc()
        adapter._rpc = fake_rpc

        adapter.resume_thread(
            "thread-1",
            approval_policy="on-request",
            permissions_profile_id=":workspace",
        )

        self.assertEqual(fake_rpc.calls[0][0], "thread/resume")
        self.assertEqual(fake_rpc.calls[0][1]["permissions"], ":workspace")
        self.assertEqual(fake_rpc.calls[1][0], "thread/resume")
        self.assertNotIn("permissions", fake_rpc.calls[1][1])
        self.assertEqual(fake_rpc.calls[1][1]["sandbox"], "workspace-write")

    def test_update_thread_settings_uses_canonical_runtime_fields(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.update_thread_settings(
            "thread-1",
            approval_policy="on-request",
            permissions_profile_id=":workspace",
            model="gpt-5.4",
            reasoning_effort="high",
            collaboration_mode="plan",
        )

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/settings/update",
                {
                    "threadId": "thread-1",
                    "approvalPolicy": "on-request",
                    "permissions": ":workspace",
                    "model": "gpt-5.4",
                    "effort": "high",
                    "collaborationMode": {
                        "mode": "plan",
                        "settings": {
                            "model": "gpt-5.4",
                            "reasoning_effort": "high",
                            "developer_instructions": None,
                        },
                    },
                },
            ),
        )

    def test_update_thread_settings_falls_back_to_legacy_sandbox_policy_when_permissions_unsupported(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _PermissionsUnsupportedRpc()
        adapter._rpc = fake_rpc

        adapter.update_thread_settings("thread-1", permissions_profile_id=":workspace")

        self.assertEqual(fake_rpc.calls[0][0], "thread/settings/update")
        self.assertEqual(fake_rpc.calls[0][1]["permissions"], ":workspace")
        self.assertEqual(fake_rpc.calls[1][0], "thread/settings/update")
        self.assertNotIn("permissions", fake_rpc.calls[1][1])
        self.assertEqual(
            fake_rpc.calls[1][1]["sandboxPolicy"],
            {
                "type": "workspaceWrite",
                "writableRoots": [],
                "readOnlyAccess": {"type": "fullAccess"},
                "networkAccess": False,
                "excludeTmpdirEnvVar": False,
                "excludeSlashTmp": False,
            },
        )

    def test_compact_thread_calls_upstream_endpoint(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.compact_thread("thread-1")

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/compact/start",
                {
                    "threadId": "thread-1",
                },
            ),
        )

    def test_get_thread_goal_reads_current_goal(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        goal = adapter.get_thread_goal("thread-1")

        self.assertEqual(fake_rpc.calls[0], ("thread/goal/get", {"threadId": "thread-1"}))
        self.assertEqual(
            goal,
            ThreadGoalSummary(
                thread_id="thread-1",
                objective="ship goal support",
                status="active",
                token_budget=123,
                tokens_used=45,
                time_used_seconds=67,
                created_at=1712476800,
                updated_at=1712476801,
            ),
        )

    def test_set_thread_goal_supports_status_only_update(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        goal = adapter.set_thread_goal("thread-1", status="paused")

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/goal/set",
                {
                    "threadId": "thread-1",
                    "status": "paused",
                },
            ),
        )
        self.assertEqual(goal.objective, "ship goal support")

    def test_clear_thread_goal_returns_backend_result(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        cleared = adapter.clear_thread_goal("thread-1")

        self.assertEqual(fake_rpc.calls[0], ("thread/goal/clear", {"threadId": "thread-1"}))
        self.assertTrue(cleared)

    def test_start_turn_default_mode_sends_explicit_collaboration_mode(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
        )

        self.assertEqual(
            fake_rpc.calls,
            [
                ("model/list", {}),
                (
                    "turn/start",
                    {
                        "threadId": "thread-1",
                        "input": [{"type": "text", "text": "hello"}],
                        "cwd": "/tmp",
                        "approvalPolicy": "never",
                        "approvalsReviewer": "user",
                        "permissions": ":danger-full-access",
                        "personality": "pragmatic",
                        "collaborationMode": {
                            "mode": "default",
                            "settings": {
                                "model": "gpt-5.3-codex",
                                "reasoning_effort": None,
                                "developer_instructions": None,
                            },
                        },
                    },
                )
            ],
        )

    def test_start_turn_plan_mode_uses_configured_model(self) -> None:
        adapter = CodexAppServerAdapter(
            CodexAppServerConfig(model="gpt-5.4", reasoning_effort="high", collaboration_mode="plan")
        )
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
        )

        self.assertEqual(len(fake_rpc.calls), 1)
        method, params = fake_rpc.calls[0]
        self.assertEqual(method, "turn/start")
        self.assertEqual(params["collaborationMode"]["mode"], "plan")
        self.assertEqual(params["collaborationMode"]["settings"]["model"], "gpt-5.4")
        self.assertEqual(params["collaborationMode"]["settings"]["reasoning_effort"], "high")

    def test_start_turn_plan_mode_resolves_default_model_once(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig(collaboration_mode="plan"))
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
        )
        adapter.start_turn(
            thread_id="thread-2",
            input_items=[{"type": "text", "text": "again"}],
            cwd="/tmp",
        )

        self.assertEqual(fake_rpc.calls[0][0], "model/list")
        self.assertEqual(fake_rpc.calls[1][0], "turn/start")
        self.assertEqual(fake_rpc.calls[2][0], "turn/start")
        self.assertEqual(
            fake_rpc.calls[1][1]["collaborationMode"]["settings"]["model"],
            "gpt-5.3-codex",
        )
        self.assertEqual(
            fake_rpc.calls[2][1]["collaborationMode"]["settings"]["model"],
            "gpt-5.3-codex",
        )

    def test_start_turn_allows_per_turn_collaboration_mode_override(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig(collaboration_mode="plan"))
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
            collaboration_mode="default",
        )

        self.assertEqual(len(fake_rpc.calls), 2)
        self.assertEqual(fake_rpc.calls[0], ("model/list", {}))
        method, params = fake_rpc.calls[1]
        self.assertEqual(method, "turn/start")
        self.assertEqual(params["collaborationMode"]["mode"], "default")
        self.assertEqual(params["collaborationMode"]["settings"]["model"], "gpt-5.3-codex")

    def test_start_turn_drops_unsupported_profile_override(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
            profile="provider2",
        )

        self.assertEqual(fake_rpc.calls[0], ("model/list", {}))
        self.assertEqual(fake_rpc.calls[1][0], "turn/start")
        self.assertNotIn("config", fake_rpc.calls[1][1])
        self.assertNotIn("modelProvider", fake_rpc.calls[1][1])

    def test_start_turn_uses_model_but_drops_profile_and_provider_overrides(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
            model="provider2-model",
            model_provider="provider2_api",
            profile="provider2",
        )

        self.assertEqual(fake_rpc.calls[0][0], "turn/start")
        params = fake_rpc.calls[0][1]
        self.assertEqual(params["model"], "provider2-model")
        self.assertNotIn("modelProvider", params)
        self.assertNotIn("config", params)
        self.assertEqual(params["collaborationMode"]["settings"]["model"], "provider2-model")

    def test_start_turn_uses_cached_thread_model_for_collaboration_mode(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc
        adapter._thread_resolved_model["thread-1"] = "provider2-model"

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
        )

        self.assertEqual(len(fake_rpc.calls), 1)
        method, params = fake_rpc.calls[0]
        self.assertEqual(method, "turn/start")
        self.assertNotIn("model", params)
        self.assertEqual(params["collaborationMode"]["settings"]["model"], "provider2-model")

    def test_start_turn_can_override_sandbox_policy(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
            sandbox="danger-full-access",
        )

        self.assertEqual(fake_rpc.calls[0], ("model/list", {}))
        self.assertEqual(fake_rpc.calls[1][0], "turn/start")
        self.assertEqual(fake_rpc.calls[1][1]["permissions"], ":danger-full-access")

    def test_start_turn_falls_back_to_legacy_sandbox_policy_when_permissions_unsupported(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _PermissionsUnsupportedRpc()
        adapter._rpc = fake_rpc

        adapter.start_turn(
            thread_id="thread-1",
            input_items=[{"type": "text", "text": "hello"}],
            cwd="/tmp",
        )

        self.assertEqual(fake_rpc.calls[0], ("model/list", {}))
        self.assertEqual(fake_rpc.calls[1][0], "turn/start")
        self.assertEqual(fake_rpc.calls[1][1]["permissions"], ":danger-full-access")
        self.assertEqual(fake_rpc.calls[2][0], "turn/start")
        self.assertNotIn("permissions", fake_rpc.calls[2][1])
        self.assertEqual(fake_rpc.calls[2][1]["sandboxPolicy"], {"type": "dangerFullAccess"})

    def test_list_threads_can_explicitly_disable_provider_filter(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.list_threads(cwd="/tmp/project", limit=5, model_providers=[])

        self.assertEqual(
            fake_rpc.calls[0],
            (
                "thread/list",
                {
                    "cwd": "/tmp/project",
                    "limit": 5,
                    "sourceKinds": ["cli", "vscode", "exec", "appServer"],
                    "modelProviders": [],
                },
            ),
        )

    def test_read_runtime_config_parses_profiles_and_memory_mode(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        with patch(
            "bot.adapters.codex_app_server.list_profile_v2_names",
            return_value=["provider1", "provider2"],
        ), patch(
            "bot.adapters.codex_app_server.profile_v2_is_usable",
            side_effect=[True, True],
        ), patch(
            "bot.adapters.codex_app_server.resolve_profile_from_codex_config",
            side_effect=[
                ResolvedProfileConfig(model="provider1-model", model_provider="provider1_api"),
                ResolvedProfileConfig(model="provider2-model", model_provider="provider2_api"),
            ],
        ):
            runtime = adapter.read_runtime_config()

        self.assertEqual(runtime.current_profile, "provider1")
        self.assertEqual(runtime.current_model_provider, "provider1_api")
        self.assertEqual(runtime.current_memory_mode, "read")
        self.assertEqual(
            [(item.name, item.model_provider) for item in runtime.profiles],
            [("provider1", "provider1_api"), ("provider2", "provider2_api")],
        )

    def test_read_runtime_config_skips_non_concrete_profile_candidates(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        with patch(
            "bot.adapters.codex_app_server.list_profile_v2_names",
            return_value=["provider1", "broken"],
        ), patch(
            "bot.adapters.codex_app_server.profile_v2_is_usable",
            side_effect=[True, False],
        ), patch(
            "bot.adapters.codex_app_server.resolve_profile_from_codex_config",
            side_effect=[
                ResolvedProfileConfig(model="provider1-model", model_provider="provider1_api"),
                ResolvedProfileConfig(model="broken-model", model_provider=""),
            ],
        ):
            runtime = adapter.read_runtime_config()

        self.assertEqual(
            [(item.name, item.model_provider) for item in runtime.profiles],
            [("provider1", "provider1_api")],
        )

    def test_list_models_reads_visible_models(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        models = adapter.list_models()

        self.assertEqual(fake_rpc.calls[0], ("model/list", {}))
        self.assertEqual(
            models,
            [
                RuntimeModelSummary(model="gpt-5.3-codex", display_name=None, is_default=True, hidden=False),
                RuntimeModelSummary(model="gpt-5.4", display_name=None, is_default=False, hidden=False),
            ],
        )

    def test_set_active_profile_is_unsupported(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        with self.assertRaisesRegex(RuntimeError, "active profile"):
            adapter.set_active_profile("provider2")
        self.assertEqual(fake_rpc.calls, [])

    def test_stop_clears_cached_models(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc
        adapter._collaboration_mode_model = "gpt-stale"
        adapter._thread_resolved_model["thread-1"] = "thread-model"

        adapter.stop()

        self.assertTrue(fake_rpc.stopped)
        self.assertIsNone(adapter._collaboration_mode_model)
        self.assertEqual(adapter._thread_resolved_model, {})

    def test_archive_thread_calls_public_archive_api(self) -> None:
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        fake_rpc = _FakeRpc()
        adapter._rpc = fake_rpc

        adapter.archive_thread("thread-1")

        self.assertEqual(fake_rpc.calls[0], ("thread/archive", {"threadId": "thread-1"}))

    def test_config_rejects_invalid_collaboration_mode(self) -> None:
        with self.assertRaises(ValueError):
            CodexAppServerConfig.from_dict({"collaboration_mode": "broken"})

    def test_config_rejects_invalid_app_server_mode(self) -> None:
        with self.assertRaises(ValueError):
            CodexAppServerConfig.from_dict({"app_server_mode": "broken"})


class AppServerRuntimeStoreTests(unittest.TestCase):
    def test_resolve_effective_app_server_url_uses_runtime_state_for_default_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = AppServerRuntimeStore(data_dir)
            store.save_managed_runtime(
                configured_url="ws://127.0.0.1:8765",
                active_url="ws://127.0.0.1:43210",
                owner_pid=os.getpid(),
                app_server_pid=os.getpid(),
            )

            self.assertEqual(
                resolve_effective_app_server_url("ws://127.0.0.1:8765", data_dir=data_dir),
                "ws://127.0.0.1:43210",
            )

    def test_resolve_effective_app_server_url_ignores_stale_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = AppServerRuntimeStore(data_dir)
            store.save_managed_runtime(
                configured_url="ws://127.0.0.1:8765",
                active_url="ws://127.0.0.1:43210",
                owner_pid=999999,
                app_server_pid=999999,
            )

            with patch("bot.stores.app_server_runtime_store.process_exists", return_value=False):
                self.assertEqual(
                    resolve_effective_app_server_url("ws://127.0.0.1:8765", data_dir=data_dir),
                    "ws://127.0.0.1:8765",
                )
            self.assertFalse((data_dir / "app_server_runtime.json").exists())

    def test_load_managed_runtime_clears_file_when_app_server_pid_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = AppServerRuntimeStore(data_dir)
            store.save_managed_runtime(
                configured_url="ws://127.0.0.1:8765",
                active_url="ws://127.0.0.1:43210",
                owner_pid=1234,
                app_server_pid=5678,
            )

            with patch(
                "bot.stores.app_server_runtime_store.process_exists",
                side_effect=[True, False],
            ) as mock_process_exists:
                self.assertIsNone(store.load_managed_runtime())

            self.assertEqual(mock_process_exists.call_args_list[0].args, (1234,))
            self.assertEqual(mock_process_exists.call_args_list[1].args, (5678,))
            self.assertFalse((data_dir / "app_server_runtime.json").exists())

    def test_resolve_running_instance_app_server_url_prefers_runtime_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = AppServerRuntimeStore(data_dir)
            store.save_managed_runtime(
                configured_url="ws://127.0.0.1:8765",
                active_url="ws://127.0.0.1:43210",
                owner_pid=os.getpid(),
                app_server_pid=os.getpid(),
            )
            entry = InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=os.getpid(),
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9393",
                app_server_url="ws://127.0.0.1:8765",
                config_dir="/tmp/config-explorer",
                data_dir=str(data_dir),
                started_at=1.0,
                updated_at=1.0,
            )

            self.assertEqual(
                resolve_running_instance_app_server_url(
                    entry,
                    configured_app_server_url="ws://127.0.0.1:8765",
                ),
                "ws://127.0.0.1:43210",
            )

    def test_resolve_running_instance_app_server_url_prefers_control_plane_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            entry = InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=os.getpid(),
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9393",
                app_server_url="ws://127.0.0.1:8765",
                config_dir="/tmp/config-explorer",
                data_dir=str(data_dir),
                started_at=1.0,
                updated_at=1.0,
            )

            with patch(
                "bot.instance_resolution.control_request",
                return_value={"app_server_url": "ws://127.0.0.1:45555"},
            ) as mock_control_request:
                self.assertEqual(
                    resolve_running_instance_app_server_url(
                        entry,
                        configured_app_server_url="ws://127.0.0.1:8765",
                    ),
                    "ws://127.0.0.1:45555",
                )

            self.assertEqual(mock_control_request.call_args.args[1], "service/status")

    def test_resolve_running_instance_app_server_url_fails_closed_without_live_default_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            entry = InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=os.getpid(),
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9393",
                app_server_url="ws://127.0.0.1:8765",
                config_dir="/tmp/config-explorer",
                data_dir=str(data_dir),
                started_at=1.0,
                updated_at=1.0,
            )

            self.assertEqual(
                resolve_running_instance_app_server_url(
                    entry,
                    configured_app_server_url="ws://127.0.0.1:8765",
                ),
                "",
            )

    def test_resolve_running_instance_app_server_url_falls_back_after_control_plane_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = AppServerRuntimeStore(data_dir)
            store.save_managed_runtime(
                configured_url="ws://127.0.0.1:8765",
                active_url="ws://127.0.0.1:43210",
                owner_pid=os.getpid(),
                app_server_pid=os.getpid(),
            )
            entry = InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=os.getpid(),
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9393",
                app_server_url="ws://127.0.0.1:8765",
                config_dir="/tmp/config-explorer",
                data_dir=str(data_dir),
                started_at=1.0,
                updated_at=1.0,
            )

            with patch(
                "bot.instance_resolution.control_request",
                side_effect=ServiceControlError("boom"),
            ):
                self.assertEqual(
                    resolve_running_instance_app_server_url(
                        entry,
                        configured_app_server_url="ws://127.0.0.1:8765",
                    ),
                    "ws://127.0.0.1:43210",
                )


class ProcessUtilsTests(unittest.TestCase):
    def test_process_exists_treats_linux_zombie_as_not_running(self) -> None:
        with patch("bot.process_utils.os.kill", return_value=None):
            with patch("bot.process_utils._linux_process_state", return_value="Z"):
                self.assertFalse(process_utils.process_exists(1234))


class InteractionLeaseStoreTests(unittest.TestCase):
    def test_interaction_lease_store_acquire_and_release_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = InteractionLeaseStore(data_dir)
            holder = make_fcodex_interaction_holder("fcodex:primary", owner_pid=os.getpid())

            acquired = store.acquire("thread-1", holder)

            self.assertTrue(acquired.granted)
            self.assertTrue(acquired.acquired)
            self.assertEqual(store.load("thread-1").holder, holder)

            reacquired = store.acquire("thread-1", holder)

            self.assertTrue(reacquired.granted)
            self.assertFalse(reacquired.acquired)
            self.assertEqual(reacquired.lease.holder, holder)
            self.assertTrue(store.release("thread-1", holder))
            self.assertIsNone(store.load("thread-1"))

    def test_interaction_lease_store_prunes_stale_owner_before_acquire(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = InteractionLeaseStore(data_dir)
            stale_holder = make_fcodex_interaction_holder("fcodex:stale", owner_pid=999999)
            current_holder = make_fcodex_interaction_holder("fcodex:current", owner_pid=os.getpid())
            store.force_acquire("thread-1", stale_holder)

            with patch(
                "bot.stores.interaction_lease_store.process_exists",
                side_effect=lambda pid: pid == os.getpid(),
            ):
                acquired = store.acquire("thread-1", current_holder)

            self.assertTrue(acquired.granted)
            self.assertTrue(acquired.acquired)
            self.assertEqual(acquired.lease.holder, current_holder)
            self.assertEqual(store.load("thread-1").holder, current_holder)


class CodexRpcClientTests(unittest.TestCase):
    def test_start_initializes_with_experimental_api(self) -> None:
        client = CodexRpcClient()
        captured: list[tuple[str, dict, float | None]] = []

        def fake_start_locked() -> None:
            client._ws = object()
            client._process = object()

        def fake_request(method: str, params: dict | None = None, *, timeout: float | None = None) -> dict:
            captured.append((method, params or {}, timeout))
            return {}

        with patch.object(client, "_start_locked", fake_start_locked):
            with patch.object(client, "request", fake_request):
                client.start()

        self.assertEqual(
            captured,
            [
                (
                    "initialize",
                    {
                        "clientInfo": {"name": "feishu-codex", "version": __version__},
                        "capabilities": {"experimentalApi": True},
                    },
                    client._connect_timeout_seconds,
                )
            ],
        )

    def test_connect_ws_disables_default_frame_limit(self) -> None:
        client = CodexRpcClient(connect_timeout_seconds=0.1)
        client._app_server_url = "ws://127.0.0.1:12345"

        class _Proc:
            def poll(self):
                return None

        client._process = _Proc()

        with patch("bot.codex_protocol.client.connect", return_value="ws-obj") as mock_connect:
            client._connect_ws_locked()

        self.assertEqual(client._ws, "ws-obj")
        _, kwargs = mock_connect.call_args
        self.assertEqual(kwargs["open_timeout"], client._connect_timeout_seconds)
        self.assertIsNone(kwargs["max_size"])

    def test_connect_ws_uses_bearer_auth_for_remote_backend_when_token_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            token = AppServerWebsocketAuthTokenStore(data_dir).ensure()
            client = CodexRpcClient(
                app_server_mode="remote",
                app_server_data_dir=data_dir,
                connect_timeout_seconds=0.1,
            )
            client._app_server_url = "ws://127.0.0.1:12345"

            with patch("bot.codex_protocol.client.connect", return_value="ws-obj") as mock_connect:
                client._connect_ws_locked()

        self.assertEqual(client._ws, "ws-obj")
        _, kwargs = mock_connect.call_args
        self.assertEqual(kwargs["additional_headers"], {"Authorization": f"Bearer {token}"})

    def test_connect_ws_fails_immediately_for_remote_backend_when_token_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            client = CodexRpcClient(
                app_server_mode="remote",
                app_server_data_dir=data_dir,
                connect_timeout_seconds=5.0,
            )
            client._app_server_url = "ws://127.0.0.1:12345"

            with patch("bot.codex_protocol.client.time.sleep") as mock_sleep:
                with patch("bot.codex_protocol.client.connect", return_value="ws-obj") as mock_connect:
                    with self.assertRaisesRegex(
                        MissingAppServerWebsocketAuthTokenError,
                        "backend websocket auth token 不存在",
                    ):
                        client._connect_ws_locked()

        mock_connect.assert_not_called()
        mock_sleep.assert_not_called()

    def test_launch_managed_process_uses_resolved_stable_codex_command_when_default_missing(self) -> None:
        stable_command = (
            "/home/bot/.nvm/versions/node/v24.15.0/bin/node "
            "/home/bot/.nvm/versions/node/v24.15.0/lib/node_modules/@openai/codex/bin/codex.js"
        )

        class _Proc:
            stdout = StringIO("")
            stderr = StringIO("")

            def poll(self):
                return None

        class _ThreadStub:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def start(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            client = CodexRpcClient(
                codex_command=DEFAULT_CODEX_COMMAND,
                app_server_data_dir=data_dir,
            )

            with patch(
                "bot.codex_protocol.client.resolve_managed_codex_command",
                return_value=stable_command,
            ):
                with patch("bot.codex_protocol.client.subprocess.Popen", return_value=_Proc()) as mock_popen:
                    with patch("bot.codex_protocol.client.threading.Thread", _ThreadStub):
                        client._launch_managed_process_locked("ws://127.0.0.1:8765")

            launched = mock_popen.call_args.args[0]
            self.assertEqual(
                launched,
                [
                    "/home/bot/.nvm/versions/node/v24.15.0/bin/node",
                    "/home/bot/.nvm/versions/node/v24.15.0/lib/node_modules/@openai/codex/bin/codex.js",
                    "app-server",
                    "--listen",
                    "ws://127.0.0.1:8765",
                    "--ws-auth",
                    "capability-token",
                    "--ws-token-file",
                    str(AppServerWebsocketAuthTokenStore(data_dir).path),
                ],
            )
            self.assertTrue(AppServerWebsocketAuthTokenStore(data_dir).path.exists())

    def test_start_locked_reuses_existing_managed_process(self) -> None:
        client = CodexRpcClient()

        class _Proc:
            def poll(self):
                return None

        class _ThreadStub:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def start(self) -> None:
                return None

        client._process = _Proc()

        with patch.object(client, "_connect_ws_locked", lambda: setattr(client, "_ws", object())):
            with patch("bot.codex_protocol.client.subprocess.Popen") as mock_popen:
                with patch("bot.codex_protocol.client.threading.Thread", _ThreadStub):
                    client._start_locked()

        mock_popen.assert_not_called()
        self.assertIsNotNone(client._ws)

    def test_start_locked_falls_back_to_free_port_when_default_is_busy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback_url = "ws://127.0.0.1:43210"
            store = AppServerRuntimeStore(Path(tmpdir))
            client = CodexRpcClient(
                app_server_runtime_store=store,
                managed_startup_lock_path=Path(tmpdir) / "startup.lock",
                app_server_data_dir=Path(tmpdir),
            )

            class _Proc:
                pid = os.getpid()
                stdout = StringIO("")
                stderr = StringIO("")

                def poll(self):
                    return None

            class _ThreadStub:
                def __init__(self, *args, **kwargs) -> None:
                    pass

                def start(self) -> None:
                    return None

            with patch.object(client, "_can_bind_listen_url", return_value=False):
                with patch.object(client, "_allocate_free_listen_url", return_value=fallback_url):
                    with patch.object(client, "_connect_ws_locked", lambda: setattr(client, "_ws", object())):
                        with patch("bot.codex_protocol.client.subprocess.Popen", return_value=_Proc()) as mock_popen:
                            with patch("bot.codex_protocol.client.threading.Thread", _ThreadStub):
                                client._start_locked()

            self.assertEqual(client.current_app_server_url(), fallback_url)
            launched = mock_popen.call_args.args[0]
            self.assertEqual(launched[launched.index("--listen") + 1], fallback_url)
            self.assertEqual(
                resolve_effective_app_server_url("ws://127.0.0.1:8765", data_dir=Path(tmpdir)),
                fallback_url,
            )

    def test_start_locked_retries_default_url_when_child_exits_after_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            default_url = "ws://127.0.0.1:8765"
            fallback_url = "ws://127.0.0.1:43210"
            store = AppServerRuntimeStore(Path(tmpdir))
            client = CodexRpcClient(
                app_server_runtime_store=store,
                managed_startup_lock_path=Path(tmpdir) / "startup.lock",
                app_server_data_dir=Path(tmpdir),
            )

            class _ProcDead:
                pid = 111
                stdout = StringIO("")
                stderr = StringIO("")

                def poll(self):
                    return 1

            class _ProcLive:
                pid = os.getpid()
                stdout = StringIO("")
                stderr = StringIO("")

                def poll(self):
                    return None

            class _ThreadStub:
                def __init__(self, *args, **kwargs) -> None:
                    pass

                def start(self) -> None:
                    return None

            def _fake_connect() -> None:
                client._ws = Mock()

            with patch.object(client, "_select_managed_listen_url", return_value=default_url):
                with patch.object(client, "_allocate_free_listen_url", return_value=fallback_url):
                    with patch.object(client, "_connect_ws_locked", _fake_connect):
                        with patch("bot.codex_protocol.client._MANAGED_APP_SERVER_VERIFY_GRACE_SECONDS", 0.0):
                            with patch(
                                "bot.codex_protocol.client.subprocess.Popen",
                                side_effect=[_ProcDead(), _ProcLive()],
                            ) as mock_popen:
                                with patch("bot.codex_protocol.client.threading.Thread", _ThreadStub):
                                    client._start_locked()

            first_launch = mock_popen.call_args_list[0].args[0]
            second_launch = mock_popen.call_args_list[1].args[0]
            self.assertEqual(first_launch[first_launch.index("--listen") + 1], default_url)
            self.assertEqual(second_launch[second_launch.index("--listen") + 1], fallback_url)
            self.assertEqual(client.current_app_server_url(), fallback_url)
            self.assertEqual(
                resolve_effective_app_server_url("ws://127.0.0.1:8765", data_dir=Path(tmpdir)),
                fallback_url,
            )

    def test_reader_loop_notifies_disconnect_once_for_unexpected_close(self) -> None:
        disconnects: list[str] = []
        client = CodexRpcClient(on_disconnect=lambda: disconnects.append("disconnected"))

        class _Ws:
            def recv(self):
                raise ConnectionClosedOK(None, None)

        client._ws = _Ws()

        client._reader_loop()

        self.assertEqual(disconnects, ["disconnected"])
        self.assertIsNone(client._ws)


class FCodexTests(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        env_patcher = patch.dict(
            os.environ,
            {
                "FC_INSTANCE": "",
                "FC_DATA_DIR": "",
                "FC_GLOBAL_DATA_DIR": "",
            },
            clear=False,
        )
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        patchers = [
            patch(
                "bot.instance_resolution.resolve_effective_app_server_url",
                side_effect=lambda configured_url, *, data_dir: configured_url,
            ),
            patch("bot.instance_resolution.list_running_instances", return_value=[]),
            patch("bot.instance_resolution.load_running_instance", return_value=None),
            patch("bot.instance_resolution.current_cli_instance_name", return_value="default"),
            patch("bot.fcodex.current_cli_instance_name", return_value="default"),
            patch("bot.fcodex.list_running_instances", return_value=[]),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_default_data_dir_falls_back_to_install_path_when_not_in_dev_layout(self) -> None:
        with patch.dict("bot.fcodex.os.environ", {}, clear=True):
            with patch("bot.fcodex.default_data_root", return_value=Path("/home/tester/.local/share/feishu-codex")):
                self.assertEqual(
                    _default_data_dir(),
                    Path("/home/tester/.local/share/feishu-codex"),
                )

    def test_fcodex_injects_remote_url(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())) as mock_proxy:
                with patch("bot.fcodex.os.execvpe") as mock_exec:
                    with patch("sys.argv", ["fcodex", "resume", "019d2e94-a475-7bc1-b2f7-a3ce37628ede"]):
                        fcodex_main()

        mock_proxy.assert_called_once_with(
            "ws://127.0.0.1:8765",
            os.getcwd(),
            _default_data_dir(),
            new_thread_profile_seed="",
            new_thread_profile_model_seed="",
            new_thread_profile_model_provider_seed="",
            new_thread_profile_reasoning_effort_seed="",
            new_thread_memory_mode_seed="",
            resume_profile_hint="",
            proxy_auth_token=ANY,
        )
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "resume",
                "019d2e94-a475-7bc1-b2f7-a3ce37628ede",
            ],
        )
        self.assertEqual(
            mock_exec.call_args.args[2][FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR],
            mock_proxy.call_args.kwargs["proxy_auth_token"],
        )

    def test_fcodex_uses_runtime_resolved_backend_url(self) -> None:
        fallback_url = "ws://127.0.0.1:43210"
        with patch("bot.instance_resolution.resolve_effective_app_server_url", return_value=fallback_url):
            with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
                with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())) as mock_proxy:
                    with patch("bot.fcodex.os.execvpe") as mock_exec:
                        with patch("sys.argv", ["fcodex", "resume", "019d2e94-a475-7bc1-b2f7-a3ce37628ede"]):
                            fcodex_main()

        mock_proxy.assert_called_once_with(
            fallback_url,
            os.getcwd(),
            _default_data_dir(),
            new_thread_profile_seed="",
            new_thread_profile_model_seed="",
            new_thread_profile_model_provider_seed="",
            new_thread_profile_reasoning_effort_seed="",
            new_thread_memory_mode_seed="",
            resume_profile_hint="",
            proxy_auth_token=ANY,
        )
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "resume",
                "019d2e94-a475-7bc1-b2f7-a3ce37628ede",
            ],
        )

    def test_fcodex_does_not_inject_instance_default_profile_for_new_thread(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())):
                with patch("bot.fcodex.os.execvpe") as mock_exec:
                    with patch("sys.argv", ["fcodex"]):
                        fcodex_main()

        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
            ],
        )

    def test_fcodex_explicit_profile_seeds_first_new_thread(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch(
                "bot.fcodex._resolve_thread_resume_profile_setting_for_resume",
                return_value=ThreadResumeProfileSetting(
                    profile="provider1",
                    model="gpt-5.4",
                    model_provider="provider1_api",
                    reasoning_effort="high",
                ),
            ):
                with patch("bot.fcodex.ThreadResumeProfileStore.save") as mock_save:
                    with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())) as mock_proxy:
                        with patch("bot.fcodex.os.execvpe") as mock_exec:
                            with patch("sys.argv", ["fcodex", "-p", "provider1"]):
                                fcodex_main()

        mock_save.assert_not_called()
        mock_proxy.assert_called_once_with(
            "ws://127.0.0.1:8765",
            os.getcwd(),
            _default_data_dir(),
            new_thread_profile_seed="",
            new_thread_profile_model_seed="",
            new_thread_profile_model_provider_seed="",
            new_thread_profile_reasoning_effort_seed="",
            new_thread_memory_mode_seed="",
            resume_profile_hint="provider1",
            proxy_auth_token=ANY,
        )
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "-p",
                "provider1",
            ],
        )

    def test_fcodex_explicit_remote_skips_shared_resolution(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex._resolve_thread_target_via_remote_backend") as mock_resolve:
                with patch("bot.fcodex.os.execvpe") as mock_exec:
                    with patch("sys.argv", ["fcodex", "--remote", "ws://127.0.0.1:9900", "resume", "demo"]):
                        fcodex_main()

        mock_resolve.assert_not_called()
        self.assertEqual(
            mock_exec.call_args[0][1],
            ["codex", "--cd", os.getcwd(), "--remote", "ws://127.0.0.1:9900", "resume", "demo"],
        )

    def test_fcodex_respects_explicit_remote_arg(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.os.execvpe") as mock_exec:
                with patch("sys.argv", ["fcodex", "--remote", "ws://127.0.0.1:9900", "resume"]):
                    fcodex_main()

        self.assertEqual(
            mock_exec.call_args[0][1],
            ["codex", "--cd", os.getcwd(), "--remote", "ws://127.0.0.1:9900", "resume"],
        )

    def test_fcodex_rejects_instance_with_explicit_remote(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "--instance", "corp-b", "--remote", "ws://127.0.0.1:9900"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("不能与显式 `--remote` 同时使用", stderr.getvalue())

    def test_fcodex_rejects_remote_auth_token_env_without_explicit_remote(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "--remote-auth-token-env", "USER_TOKEN_ENV"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("wrapper 自建 proxy 路径不接受显式 `--remote-auth-token-env`", stderr.getvalue())

    def test_fcodex_routes_resume_to_owner_instance(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        lease = ThreadRuntimeLease(
            thread_id=thread_id,
            owner_instance="corp-b",
            owner_service_token="token-b",
            control_endpoint="tcp://127.0.0.1:9102",
            backend_url="ws://127.0.0.1:9102",
            attached_at=1.0,
            holders=(),
        )
        resolved_target = CliRuntimeTarget(
            instance_name="corp-b",
            data_dir=Path("/tmp/data-b"),
            app_server_url="ws://127.0.0.1:9102",
            service_token="token-b",
            running_entry=InstanceRegistryEntry(
                instance_name="corp-b",
                owner_pid=222,
                service_token="token-b",
                control_endpoint="tcp://127.0.0.1:9102",
                app_server_url="ws://127.0.0.1:9102",
                config_dir="/tmp/config-b",
                data_dir="/tmp/data-b",
                started_at=1.0,
                updated_at=1.0,
            ),
        )
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.ThreadRuntimeLeaseStore.load", return_value=lease):
                with patch("bot.fcodex.resolve_cli_runtime_target", return_value=resolved_target) as mock_resolve_target:
                        with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9200", Mock())) as mock_proxy:
                            with patch("bot.fcodex.os.execvpe") as mock_exec:
                                with patch("sys.argv", ["fcodex", "resume", thread_id]):
                                    fcodex_main()

        self.assertEqual(mock_resolve_target.call_args.kwargs["preferred_running_instance"], "corp-b")
        self.assertFalse(mock_resolve_target.call_args.kwargs["allow_default_running_fallback"])
        mock_proxy.assert_called_once_with(
            "ws://127.0.0.1:9102",
            os.getcwd(),
            Path("/tmp/data-b"),
            instance_name="corp-b",
            service_token="token-b",
            new_thread_profile_seed="",
            new_thread_profile_model_seed="",
            new_thread_profile_model_provider_seed="",
            new_thread_profile_reasoning_effort_seed="",
            new_thread_memory_mode_seed="",
            resume_profile_hint="",
            proxy_auth_token=ANY,
        )
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9200",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "resume",
                thread_id,
            ],
        )

    def test_runtime_target_prefers_instance_runtime_store_over_stale_registry_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            AppServerRuntimeStore(data_dir).save_managed_runtime(
                configured_url="ws://127.0.0.1:8765",
                active_url="ws://127.0.0.1:43210",
                owner_pid=os.getpid(),
                app_server_pid=os.getpid(),
            )
            running_entry = InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=os.getpid(),
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9393",
                app_server_url="ws://127.0.0.1:8765",
                config_dir="/tmp/config-explorer",
                data_dir=str(data_dir),
                started_at=1.0,
                updated_at=1.0,
            )

            with patch(
                "bot.instance_resolution.resolve_cli_instance_target",
                return_value=CliInstanceTarget(
                    instance_name="explorer",
                    data_dir=data_dir,
                    running_entry=running_entry,
                ),
            ):
                resolved = resolve_cli_runtime_target(
                    configured_app_server_url="ws://127.0.0.1:8765",
                    explicit_instance="explorer",
                )

        self.assertEqual(resolved.instance_name, "explorer")
        self.assertEqual(resolved.data_dir, data_dir)
        self.assertEqual(resolved.app_server_url, "ws://127.0.0.1:43210")
        self.assertEqual(resolved.service_token, "token-explorer")

    def test_runtime_target_rejects_running_instance_without_live_default_runtime(self) -> None:
        data_dir = Path("/tmp/data-explorer")
        running_entry = InstanceRegistryEntry(
            instance_name="explorer",
            owner_pid=os.getpid(),
            service_token="token-explorer",
            control_endpoint="tcp://127.0.0.1:9393",
            app_server_url="ws://127.0.0.1:8765",
            config_dir="/tmp/config-explorer",
            data_dir=str(data_dir),
            started_at=1.0,
            updated_at=1.0,
        )

        with patch(
            "bot.instance_resolution.resolve_cli_instance_target",
            return_value=CliInstanceTarget(
                instance_name="explorer",
                data_dir=data_dir,
                running_entry=running_entry,
            ),
        ):
            with self.assertRaises(ValueError) as exc:
                resolve_cli_runtime_target(
                    configured_app_server_url="ws://127.0.0.1:8765",
                    explicit_instance="explorer",
                )

        self.assertIn("未发布可用的 app-server 地址", str(exc.exception))

    def test_runtime_target_without_default_fallback_rejects_multiple_running_instances(self) -> None:
        with patch(
            "bot.instance_resolution.list_running_instances",
            return_value=[
                InstanceRegistryEntry(
                    instance_name="default",
                    owner_pid=os.getpid(),
                    service_token="token-default",
                    control_endpoint="tcp://127.0.0.1:9101",
                    app_server_url="ws://127.0.0.1:9101",
                    config_dir="/tmp/config-default",
                    data_dir="/tmp/data-default",
                    started_at=1.0,
                    updated_at=1.0,
                ),
                InstanceRegistryEntry(
                    instance_name="explorer",
                    owner_pid=os.getpid(),
                    service_token="token-explorer",
                    control_endpoint="tcp://127.0.0.1:9102",
                    app_server_url="ws://127.0.0.1:9102",
                    config_dir="/tmp/config-explorer",
                    data_dir="/tmp/data-explorer",
                    started_at=1.0,
                    updated_at=1.0,
                ),
            ],
        ):
            with patch("bot.instance_resolution.load_running_instance", return_value=None):
                with patch("bot.instance_resolution.current_cli_instance_name", return_value="default"):
                    with self.assertRaises(ValueError) as exc:
                        resolve_cli_runtime_target(
                            configured_app_server_url="ws://127.0.0.1:8765",
                            allow_default_running_fallback=False,
                        )

        self.assertIn("请显式传 `--instance <name>`", str(exc.exception))

    def test_fcodex_requires_explicit_instance_when_multiple_instances_are_running(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch(
                "bot.fcodex.resolve_cli_runtime_target",
                side_effect=ValueError("检测到多个运行中的实例，请显式传 `--instance <name>`。"),
            ):
                with patch("bot.fcodex.ThreadRuntimeLeaseStore.load", return_value=None):
                    with patch("bot.fcodex.sys.stderr", stderr):
                        with patch("sys.argv", ["fcodex", "resume", thread_id]):
                            with self.assertRaises(SystemExit) as exc:
                                fcodex_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("请显式传 `--instance <name>`", stderr.getvalue())
        self.assertIn("当前是 `fcodex resume <thread>` 路径", stderr.getvalue())

    def test_fcodex_rejects_slash_threads_command(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "/threads"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("不再支持 slash 自命令", stderr.getvalue())
        self.assertIn("feishu-codexctl thread list --scope cwd", stderr.getvalue())

    def test_fcodex_rejects_slash_help_command(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "/help"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("feishu-codexctl", stderr.getvalue())
        self.assertIn("进入 TUI 后再使用 upstream `/help`", stderr.getvalue())

    def test_fcodex_rejects_slash_profile_command(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "/profile", "provider2"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("fcodex -p <profile>", stderr.getvalue())

    def test_fcodex_rejects_slash_archive_command(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "/archive", "thread-1"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("feishu-codexctl thread archive", stderr.getvalue())

    def test_fcodex_rejects_slash_resume_command(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "/resume", "demo"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("fcodex resume <thread_id|thread_name>", stderr.getvalue())

    def test_fcodex_rejects_removed_dry_run_wrapper_entry(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "--dry-run", "/threads"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("不再提供 `--dry-run` wrapper 入口", stderr.getvalue())
        self.assertIn("feishu-codexctl thread list", stderr.getvalue())

    def test_fcodex_non_slash_text_is_passthrough_prompt(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())):
                with patch("bot.fcodex.os.execvpe") as mock_exec:
                    with patch("sys.argv", ["fcodex", "session"]):
                        fcodex_main()

        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "session",
            ],
        )

    def test_fcodex_rejects_wrapper_command_mixed_with_prefix_flags(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "--cd", "/tmp/project", "/threads"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("不再支持 slash 自命令", stderr.getvalue())
        self.assertIn("feishu-codexctl thread list --scope cwd", stderr.getvalue())

    def test_fcodex_rejects_unknown_slash_command_in_shell_wrapper(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.sys.stderr", stderr):
                with patch("sys.argv", ["fcodex", "/cd", "/tmp/project"]):
                    with self.assertRaises(SystemExit) as exc:
                        fcodex_main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("不再支持 slash 自命令：`/cd`", stderr.getvalue())
        self.assertIn("其他 `/...` 命令请先进入 Codex TUI 再执行", stderr.getvalue())

    def test_fcodex_resume_resolves_name(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch(
                "bot.fcodex._resolve_resume_lookup_runtime_target",
                return_value=CliRuntimeTarget(
                    instance_name="default",
                    data_dir=_default_data_dir(),
                    app_server_url="ws://127.0.0.1:8765",
                ),
            ):
                with patch("bot.fcodex._resolve_thread_target_via_remote_backend") as mock_resolve:
                    mock_resolve.return_value = (
                        ThreadSummary(
                            thread_id="019d2e94-a475-7bc1-b2f7-a3ce37628ede",
                            cwd="/tmp/project",
                            name="demo",
                            preview="hello",
                            created_at=0,
                            updated_at=0,
                            source="cli",
                            status="notLoaded",
                        ),
                        None,
                    )
                    with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())):
                        with patch("bot.fcodex.os.execvpe") as mock_exec:
                            with patch("sys.argv", ["fcodex", "resume", "demo"]):
                                fcodex_main()

        self.assertEqual(mock_resolve.call_args.args[3], "demo")
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "resume",
                "019d2e94-a475-7bc1-b2f7-a3ce37628ede",
            ],
        )

    def test_fcodex_resume_name_routes_to_unique_running_instance_without_live_owner(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        running_instances = [
            InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=222,
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9102",
                app_server_url="ws://127.0.0.1:9102",
                config_dir="/tmp/config-explorer",
                data_dir="/tmp/data-explorer",
                started_at=1.0,
                updated_at=1.0,
            ),
        ]
        resolved_target = CliRuntimeTarget(
            instance_name="explorer",
            data_dir=Path("/tmp/data-explorer"),
            app_server_url="ws://127.0.0.1:9102",
            service_token="token-explorer",
            running_entry=running_instances[0],
        )
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.list_running_instances", return_value=running_instances):
                with patch(
                    "bot.fcodex._resolve_resume_lookup_runtime_target",
                    return_value=CliRuntimeTarget(
                        instance_name="explorer",
                        data_dir=Path("/tmp/data-explorer"),
                        app_server_url="ws://127.0.0.1:9102",
                    ),
                ):
                    with patch(
                        "bot.fcodex._resolve_thread_target_via_remote_backend",
                        return_value=(
                            ThreadSummary(
                                thread_id=thread_id,
                                cwd="/tmp/project",
                                name="demo",
                                preview="hello",
                                created_at=0,
                                updated_at=0,
                                source="cli",
                                status="notLoaded",
                            ),
                            None,
                        ),
                    ):
                        with patch("bot.fcodex.resolve_cli_runtime_target", return_value=resolved_target) as mock_resolve_target:
                            with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9200", Mock())):
                                with patch("bot.fcodex.os.execvpe") as mock_exec:
                                    with patch("sys.argv", ["fcodex", "resume", "demo"]):
                                        fcodex_main()

        self.assertEqual(mock_resolve_target.call_args.kwargs["preferred_running_instance"], "explorer")
        self.assertFalse(mock_resolve_target.call_args.kwargs["allow_default_running_fallback"])
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9200",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "resume",
                thread_id,
            ],
        )

    def test_fcodex_resume_name_requires_explicit_instance_when_running_instance_is_ambiguous(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        running_instances = [
            InstanceRegistryEntry(
                instance_name="default",
                owner_pid=111,
                service_token="token-default",
                control_endpoint="tcp://127.0.0.1:9101",
                app_server_url="ws://127.0.0.1:9101",
                config_dir="/tmp/config-default",
                data_dir="/tmp/data-default",
                started_at=1.0,
                updated_at=1.0,
            ),
            InstanceRegistryEntry(
                instance_name="explorer",
                owner_pid=222,
                service_token="token-explorer",
                control_endpoint="tcp://127.0.0.1:9102",
                app_server_url="ws://127.0.0.1:9102",
                config_dir="/tmp/config-explorer",
                data_dir="/tmp/data-explorer",
                started_at=1.0,
                updated_at=1.0,
            ),
        ]
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.list_running_instances", return_value=running_instances):
                with patch("bot.instance_resolution.list_running_instances", return_value=running_instances):
                    with patch(
                        "bot.fcodex._resolve_resume_lookup_runtime_target",
                        return_value=CliRuntimeTarget(
                            instance_name="default",
                            data_dir=Path("/tmp/data-default"),
                            app_server_url="ws://127.0.0.1:9101",
                        ),
                    ):
                        with patch(
                            "bot.fcodex._resolve_thread_target_via_remote_backend",
                            return_value=(
                                ThreadSummary(
                                    thread_id=thread_id,
                                    cwd="/tmp/project",
                                    name="demo",
                                    preview="hello",
                                    created_at=0,
                                    updated_at=0,
                                    source="cli",
                                    status="notLoaded",
                                ),
                                None,
                            ),
                        ):
                            with patch("bot.fcodex.sys.stderr", stderr):
                                with patch("sys.argv", ["fcodex", "resume", "demo"]):
                                    with self.assertRaises(SystemExit) as exc:
                                        fcodex_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("请显式传 `--instance <name>`", stderr.getvalue())
        self.assertIn("当前是 `fcodex resume <thread>` 路径", stderr.getvalue())

    def test_fcodex_resume_with_explicit_instance_rejects_conflicting_live_owner(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        lease = ThreadRuntimeLease(
            thread_id=thread_id,
            owner_instance="explorer",
            owner_service_token="token-explorer",
            control_endpoint="tcp://127.0.0.1:9102",
            backend_url="ws://127.0.0.1:9102",
            attached_at=1.0,
            holders=(),
        )
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.ThreadRuntimeLeaseStore.load", return_value=lease):
                with patch("bot.fcodex.sys.stderr", stderr):
                    with patch("sys.argv", ["fcodex", "--instance", "default", "resume", thread_id]):
                        with self.assertRaises(SystemExit) as exc:
                            fcodex_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("live runtime owner 是 `explorer`", stderr.getvalue())
        self.assertIn("不能显式传 `--instance default`", stderr.getvalue())

    def test_fcodex_resume_rejects_when_other_running_instance_still_reports_loaded(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch(
                "bot.fcodex.resolve_cli_runtime_target",
                return_value=CliRuntimeTarget(
                    instance_name="explorer",
                    data_dir=Path("/tmp/data-explorer"),
                    app_server_url="ws://127.0.0.1:9102",
                    service_token="token-explorer",
                ),
            ):
                with patch(
                    "bot.fcodex.preview_thread_global_loaded_gate",
                    return_value=Mock(
                        allowed=False,
                        reason_text=(
                            "当前 thread 仍由运行中的实例 `default` 保持为 loaded (`idle`)；"
                            "当前不支持跨实例 hot takeover。"
                        ),
                    ),
                ):
                    with patch("bot.fcodex.sys.stderr", stderr):
                        with patch("sys.argv", ["fcodex", "--instance", "explorer", "resume", thread_id]):
                            with self.assertRaises(SystemExit) as exc:
                                fcodex_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("不支持跨实例 hot takeover", stderr.getvalue())

    def test_fcodex_resume_name_with_explicit_instance_rejects_conflicting_live_owner(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        lease = ThreadRuntimeLease(
            thread_id=thread_id,
            owner_instance="explorer",
            owner_service_token="token-explorer",
            control_endpoint="tcp://127.0.0.1:9102",
            backend_url="ws://127.0.0.1:9102",
            attached_at=1.0,
            holders=(),
        )
        stderr = StringIO()
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch(
                "bot.fcodex._resolve_resume_lookup_runtime_target",
                return_value=CliRuntimeTarget(
                    instance_name="default",
                    data_dir=Path("/tmp/data-default"),
                    app_server_url="ws://127.0.0.1:9101",
                ),
            ):
                with patch(
                    "bot.fcodex._resolve_thread_target_via_remote_backend",
                    return_value=(
                        ThreadSummary(
                            thread_id=thread_id,
                            cwd="/tmp/project",
                            name="demo",
                            preview="hello",
                            created_at=0,
                            updated_at=0,
                            source="cli",
                            status="notLoaded",
                        ),
                        None,
                    ),
                ):
                    with patch("bot.fcodex.ThreadRuntimeLeaseStore.load", return_value=lease):
                        with patch("bot.fcodex.sys.stderr", stderr):
                            with patch("sys.argv", ["fcodex", "--instance", "default", "resume", "demo"]):
                                with self.assertRaises(SystemExit) as exc:
                                    fcodex_main()

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("live runtime owner 是 `explorer`", stderr.getvalue())
        self.assertIn("不能显式传 `--instance default`", stderr.getvalue())

    def test_fcodex_threadless_launch_keeps_default_running_fallback(self) -> None:
        resolved_target = CliRuntimeTarget(
            instance_name="default",
            data_dir=_default_data_dir(),
            app_server_url="ws://127.0.0.1:8765",
        )
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.resolve_cli_runtime_target", return_value=resolved_target) as mock_resolve_target:
                with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())):
                    with patch("bot.fcodex.os.execvpe") as mock_exec:
                        with patch("sys.argv", ["fcodex", "session"]):
                            fcodex_main()

        self.assertTrue(mock_resolve_target.call_args.kwargs["allow_default_running_fallback"])
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "session",
            ],
        )

    def test_fcodex_resume_ignores_legacy_saved_thread_profile(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        saved_record = ThreadResumeProfileRecord(
            thread_id=thread_id,
            profile="provider2",
            model="provider2-model",
            model_provider="provider2_api",
            updated_at=1.0,
        )
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.ThreadResumeProfileStore.load", return_value=saved_record):
                with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())) as mock_proxy:
                    with patch("bot.fcodex.os.execvpe") as mock_exec:
                        with patch("sys.argv", ["fcodex", "resume", thread_id]):
                            fcodex_main()

        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "resume",
                thread_id,
            ],
        )
        self.assertEqual(mock_proxy.call_args.kwargs["resume_profile_hint"], "")

    def test_fcodex_resume_ignores_incomplete_legacy_saved_thread_profile(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        saved_record = ThreadResumeProfileRecord(
            thread_id=thread_id,
            profile="provider2",
            model="",
            model_provider="provider2_api",
            updated_at=1.0,
        )
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.ThreadResumeProfileStore.load", return_value=saved_record):
                with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())):
                    with patch("bot.fcodex.os.execvpe") as mock_exec:
                        with patch("sys.argv", ["fcodex", "resume", thread_id]):
                            fcodex_main()

        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "resume",
                thread_id,
            ],
        )

    def test_fcodex_resume_with_explicit_profile_only_sets_resume_hint(self) -> None:
        thread_id = "019d2e94-a475-7bc1-b2f7-a3ce37628ede"
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex.ThreadResumeProfileStore.save") as mock_save:
                with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9100", Mock())) as mock_proxy:
                    with patch("bot.fcodex.os.execvpe") as mock_exec:
                        with patch("sys.argv", ["fcodex", "-p", "provider2", "resume", thread_id]):
                            fcodex_main()

        mock_save.assert_not_called()
        self.assertEqual(mock_proxy.call_args.kwargs["resume_profile_hint"], "provider2")
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9100",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                os.getcwd(),
                "-p",
                "provider2",
                "resume",
                thread_id,
            ],
        )

    def test_fcodex_explicit_cd_is_forwarded_to_proxy(self) -> None:
        with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
            with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9101", Mock())) as mock_proxy:
                with patch("bot.fcodex.os.execvpe") as mock_exec:
                    with patch("sys.argv", ["fcodex", "--cd", "/home/tester/project"]):
                        fcodex_main()

        mock_proxy.assert_called_once_with(
            "ws://127.0.0.1:8765",
            "/home/tester/project",
            _default_data_dir(),
            new_thread_profile_seed="",
            new_thread_profile_model_seed="",
            new_thread_profile_model_provider_seed="",
            new_thread_profile_reasoning_effort_seed="",
            new_thread_memory_mode_seed="",
            resume_profile_hint="",
            proxy_auth_token=ANY,
        )
        self.assertEqual(
            mock_exec.call_args[0][1],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9101",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                "/home/tester/project",
            ],
        )

    def test_fcodex_uses_subprocess_on_windows_and_cleans_proxy(self) -> None:
        proxy_process = Mock()
        proxy_process.poll.return_value = None
        child_process = Mock()
        child_process.wait.return_value = 7
        child_process.poll.return_value = 7
        with patch("bot.fcodex.is_windows", return_value=True):
            with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
                with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9101", proxy_process)) as mock_proxy:
                    with patch("bot.fcodex.subprocess.Popen", return_value=child_process) as mock_popen:
                        with patch("sys.argv", ["fcodex", "--cd", "/home/tester/project"]):
                            with self.assertRaises(SystemExit) as exc:
                                fcodex_main()

        self.assertEqual(exc.exception.code, 7)
        self.assertEqual(
            mock_popen.call_args.args[0],
            [
                "codex",
                "--remote",
                "ws://127.0.0.1:9101",
                "--remote-auth-token-env",
                FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR,
                "--cd",
                "/home/tester/project",
            ],
        )
        self.assertEqual(mock_popen.call_args.kwargs["env"]["FC_INSTANCE"], "default")
        self.assertEqual(mock_popen.call_args.kwargs["env"]["FC_DATA_DIR"], str(_default_data_dir()))
        self.assertEqual(
            mock_popen.call_args.kwargs["env"][FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR],
            mock_proxy.call_args.kwargs["proxy_auth_token"],
        )
        proxy_process.terminate.assert_called_once_with()
        proxy_process.wait.assert_called_once_with(timeout=1.0)

    def test_fcodex_windows_interrupt_cleans_codex_and_proxy(self) -> None:
        proxy_process = Mock()
        proxy_process.poll.return_value = None
        child_process = Mock()
        child_process.wait.side_effect = [KeyboardInterrupt, None]
        child_process.poll.return_value = None
        with patch("bot.fcodex.is_windows", return_value=True):
            with patch("bot.fcodex.load_config_file", return_value={"codex_command": "codex", "app_server_url": "ws://127.0.0.1:8765"}):
                with patch("bot.fcodex._launch_local_cwd_proxy", return_value=("ws://127.0.0.1:9101", proxy_process)):
                    with patch("bot.fcodex.subprocess.Popen", return_value=child_process):
                        with patch("sys.argv", ["fcodex", "--cd", "/home/tester/project"]):
                            with self.assertRaises(KeyboardInterrupt):
                                fcodex_main()

        child_process.terminate.assert_called_once_with()
        self.assertEqual(child_process.wait.call_args_list[0].args, ())
        self.assertEqual(child_process.wait.call_args_list[1].kwargs, {"timeout": 1.0})
        proxy_process.terminate.assert_called_once_with()
        proxy_process.wait.assert_called_once_with(timeout=1.0)

    def test_launch_local_cwd_proxy_passes_parent_pid(self) -> None:
        process = Mock()
        process.stdout.readline.return_value = "ws://127.0.0.1:9100\n"
        process.poll.return_value = None
        with patch("bot.fcodex.os.getpid", return_value=4321):
            with patch("bot.fcodex.subprocess.Popen", return_value=process) as mock_popen:
                proxy_url, _ = _launch_local_cwd_proxy(
                    "ws://127.0.0.1:8765",
                    "/tmp/project",
                    Path("/tmp/fcodex-data"),
                    service_token="svc-token",
                    proxy_auth_token="proxy-auth-token",
                )

        self.assertEqual(proxy_url, "ws://127.0.0.1:9100")
        cmd = mock_popen.call_args.args[0]
        self.assertIn("--data-dir", cmd)
        self.assertIn("/tmp/fcodex-data", cmd)
        self.assertIn("--parent-pid", cmd)
        self.assertIn("4321", cmd)
        self.assertNotIn("--service-token", cmd)
        self.assertEqual(
            mock_popen.call_args.kwargs["env"][FCODEX_REMOTE_AUTH_TOKEN_ENV_VAR],
            "proxy-auth-token",
        )
        self.assertEqual(
            mock_popen.call_args.kwargs["env"][FCODEX_SERVICE_TOKEN_ENV_VAR],
            "svc-token",
        )

    def test_fcodex_proxy_rejects_service_token_cli_arg(self) -> None:
        stderr = StringIO()
        with patch("bot.fcodex_proxy.sys.stderr", stderr):
            with self.assertRaises(SystemExit) as exc:
                fcodex_proxy_main(
                    [
                        "--backend-url",
                        "ws://127.0.0.1:8765",
                        "--cwd",
                        "/tmp/project",
                        "--service-token",
                        "svc-token",
                    ]
                )

        self.assertEqual(exc.exception.code, 2)
        self.assertIn("unrecognized arguments: --service-token svc-token", stderr.getvalue())

    def test_thread_start_proxy_rewrites_only_missing_cwd(self) -> None:
        rewritten = _rewrite_thread_start_cwd(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "thread/start",
                    "params": {"approvalPolicy": "on-request"},
                }
            ),
            "/tmp/project",
        )

        self.assertEqual(
            json.loads(rewritten),
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "thread/start",
                "params": {"approvalPolicy": "on-request", "cwd": "/tmp/project"},
            },
        )

    def test_thread_start_proxy_keeps_existing_cwd_and_other_methods(self) -> None:
        original_start = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "thread/start",
                "params": {"cwd": "/srv/already-set"},
            }
        )
        original_resume = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "thread/resume",
                "params": {},
            }
        )

        self.assertEqual(
            _rewrite_thread_start_cwd(original_start, "/tmp/project"),
            original_start,
        )
        self.assertEqual(
            _rewrite_thread_start_cwd(original_resume, "/tmp/project"),
            original_resume,
        )

    def test_relay_messages_treats_normal_target_close_as_clean_exit(self) -> None:
        class _Source:
            def __iter__(self):
                return iter(["hello"])

        class _Target:
            def __init__(self) -> None:
                self.calls: list[str] = []

            def send(self, payload: str) -> None:
                self.calls.append(payload)
                raise ConnectionClosedOK(None, None)

        target = _Target()
        _relay_messages(_Source(), target)
        self.assertEqual(target.calls, ["hello"])

    def test_proxy_rejects_unauthorized_websocket_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "instance"
            AppServerWebsocketAuthTokenStore(data_dir).ensure()
            proxy_url_queue: queue.Queue[str] = queue.Queue()
            proxy_thread = threading.Thread(
                target=run_proxy,
                kwargs={
                    "backend_url": "ws://127.0.0.1:8765",
                    "cwd": "/tmp/project",
                    "proxy_auth_token": "proxy-auth-token",
                    "data_dir": data_dir,
                    "idle_timeout_seconds": 0.2,
                    "on_listen": proxy_url_queue.put,
                },
                daemon=True,
            )
            proxy_thread.start()
            proxy_url = proxy_url_queue.get(timeout=1)

            response: Response
            with self.assertRaises(InvalidStatus) as exc:
                connect(proxy_url, open_timeout=1, max_size=None)
            response = exc.exception.args[0]
            self.assertEqual(response.status_code, 401)

            proxy_thread.join(timeout=1)
            self.assertFalse(proxy_thread.is_alive())

    def test_proxy_fails_closed_when_backend_token_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "instance"

            with self.assertRaisesRegex(RuntimeError, "backend websocket auth token 不存在"):
                run_proxy(
                    backend_url="ws://127.0.0.1:8765",
                    cwd="/tmp/project",
                    proxy_auth_token="proxy-auth-token",
                    data_dir=data_dir,
                    idle_timeout_seconds=0.1,
                )

    def test_proxy_fails_closed_when_backend_auth_data_dir_is_missing(self) -> None:
        with patch.dict(os.environ, {"FC_DATA_DIR": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "requires instance data dir"):
                run_proxy(
                    backend_url="ws://127.0.0.1:8765",
                    cwd="/tmp/project",
                    proxy_auth_token="proxy-auth-token",
                    data_dir=None,
                    idle_timeout_seconds=0.1,
                )

    def test_proxy_forwards_backend_bearer_auth_from_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "instance"
            backend_token = AppServerWebsocketAuthTokenStore(data_dir).ensure()
            backend_url_queue: queue.Queue[str] = queue.Queue()
            backend_server_ref: dict[str, object] = {}
            backend_auth_headers: queue.Queue[str | None] = queue.Queue()

            def _backend_process_request(_connection, request) -> Response | None:
                header = request.headers.get("Authorization")
                backend_auth_headers.put(header)
                if header == f"Bearer {backend_token}":
                    return None
                return Response(
                    401,
                    "Unauthorized",
                    Headers([("Content-Type", "text/plain; charset=utf-8")]),
                    b"missing backend token\n",
                )

            def _backend_handler(ws) -> None:
                for message in ws:
                    ws.send(message)

            def _backend_main() -> None:
                with serve(
                    _backend_handler,
                    "127.0.0.1",
                    0,
                    max_size=None,
                    process_request=_backend_process_request,
                ) as server:
                    backend_server_ref["server"] = server
                    port = server.socket.getsockname()[1]
                    backend_url_queue.put(f"ws://127.0.0.1:{port}")
                    server.serve_forever()

            backend_thread = threading.Thread(target=_backend_main, daemon=True)
            backend_thread.start()
            backend_url = backend_url_queue.get(timeout=1)

            proxy_url_queue: queue.Queue[str] = queue.Queue()
            proxy_thread = threading.Thread(
                target=run_proxy,
                kwargs={
                    "backend_url": backend_url,
                    "cwd": "/tmp/project",
                    "data_dir": data_dir,
                    "proxy_auth_token": "proxy-auth-token",
                    "idle_timeout_seconds": 0.2,
                    "on_listen": proxy_url_queue.put,
                },
                daemon=True,
            )
            proxy_thread.start()
            proxy_url = proxy_url_queue.get(timeout=1)

            try:
                with connect(
                    proxy_url,
                    open_timeout=1,
                    max_size=None,
                    additional_headers={"Authorization": "Bearer proxy-auth-token"},
                ) as ws:
                    ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "thread/start",
                                "params": {},
                            }
                        )
                    )
                    echoed = json.loads(ws.recv())
                    self.assertEqual(echoed["params"]["cwd"], "/tmp/project")

                self.assertEqual(
                    backend_auth_headers.get(timeout=1),
                    f"Bearer {backend_token}",
                )
                proxy_thread.join(timeout=1)
                self.assertFalse(proxy_thread.is_alive())
            finally:
                backend_server = backend_server_ref.get("server")
                if backend_server is not None:
                    backend_server.shutdown()
                backend_thread.join(timeout=1)

    def test_proxy_stays_alive_across_resume_style_reconnect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            data_dir = root_dir / "instance"
            AppServerWebsocketAuthTokenStore(data_dir).ensure()
            global_data_dir = root_dir / "_global"
            backend_url_queue: queue.Queue[str] = queue.Queue()
            backend_server_ref: dict[str, object] = {}

            def _backend_handler(ws) -> None:
                for message in ws:
                    ws.send(message)

            def _backend_main() -> None:
                with serve(_backend_handler, "127.0.0.1", 0, max_size=None) as server:
                    backend_server_ref["server"] = server
                    port = server.socket.getsockname()[1]
                    backend_url_queue.put(f"ws://127.0.0.1:{port}")
                    server.serve_forever()

            backend_thread = threading.Thread(target=_backend_main, daemon=True)
            backend_thread.start()
            backend_url = backend_url_queue.get(timeout=1)

            proxy_url_queue: queue.Queue[str] = queue.Queue()
            proxy_thread = threading.Thread(
                target=run_proxy,
                kwargs={
                    "backend_url": backend_url,
                    "cwd": "/tmp/project",
                    "proxy_auth_token": "proxy-auth-token",
                    "data_dir": data_dir,
                    "global_data_dir": global_data_dir,
                    "idle_timeout_seconds": 0.3,
                    "on_listen": proxy_url_queue.put,
                },
                daemon=True,
            )
            proxy_thread.start()
            proxy_url = proxy_url_queue.get(timeout=1)

            try:
                with connect(
                    proxy_url,
                    open_timeout=1,
                    max_size=None,
                    additional_headers={"Authorization": "Bearer proxy-auth-token"},
                ) as ws:
                    ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "thread/start",
                                "params": {},
                            }
                        )
                    )
                    echoed = json.loads(ws.recv())
                    self.assertEqual(echoed["params"]["cwd"], "/tmp/project")

                time.sleep(0.1)

                with connect(
                    proxy_url,
                    open_timeout=1,
                    max_size=None,
                    additional_headers={"Authorization": "Bearer proxy-auth-token"},
                ) as ws:
                    ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 2,
                                "method": "thread/resume",
                                "params": {"threadId": "thread-1"},
                            }
                        )
                    )
                    echoed = json.loads(ws.recv())
                    self.assertEqual(echoed["method"], "thread/resume")
                    self.assertNotIn("cwd", echoed["params"])

                proxy_thread.join(timeout=1)
                self.assertFalse(proxy_thread.is_alive())
                self.assertTrue((global_data_dir / "thread_memory_modes.lock").exists())
            finally:
                backend_server = backend_server_ref.get("server")
                if backend_server is not None:
                    backend_server.shutdown()
                backend_thread.join(timeout=1)

    def test_resume_store_loads_without_explicit_global_dir_use_machine_global_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            current_dir = root_dir / "cwd"
            current_dir.mkdir()
            global_data_dir = root_dir / "_global"
            previous_cwd = Path.cwd()
            try:
                os.chdir(current_dir)
                with patch.dict(os.environ, {"FC_GLOBAL_DATA_DIR": str(global_data_dir)}, clear=False):
                    gate = _ProxyInteractionGate(
                        cwd="/tmp/project",
                        data_dir=root_dir / "data",
                        holder_pid=os.getpid(),
                    )
                    payload = {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/resume",
                        "params": {"threadId": "thread-1"},
                    }
                    payload = gate._apply_saved_thread_profile_for_resume(payload)
                    payload = gate._apply_saved_thread_memory_mode_for_resume(payload)
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(payload["params"]["threadId"], "thread-1")
            self.assertFalse((current_dir / "thread_resume_profiles.lock").exists())
            self.assertFalse((current_dir / "thread_memory_modes.lock").exists())
            self.assertTrue((global_data_dir / "thread_resume_profiles.lock").exists())
            self.assertTrue((global_data_dir / "thread_memory_modes.lock").exists())

    def test_proxy_fail_closes_new_thread_after_disconnect_with_unknown_seed_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "instance"
            AppServerWebsocketAuthTokenStore(data_dir).ensure()
            backend_url_queue: queue.Queue[str] = queue.Queue()
            backend_server_ref: dict[str, object] = {}
            backend_messages: queue.Queue[dict] = queue.Queue()
            backend_disconnects: queue.Queue[None] = queue.Queue()

            def _backend_handler(ws) -> None:
                try:
                    for message in ws:
                        backend_messages.put(json.loads(message))
                finally:
                    backend_disconnects.put(None)

            def _backend_main() -> None:
                with serve(_backend_handler, "127.0.0.1", 0, max_size=None) as server:
                    backend_server_ref["server"] = server
                    port = server.socket.getsockname()[1]
                    backend_url_queue.put(f"ws://127.0.0.1:{port}")
                    server.serve_forever()

            backend_thread = threading.Thread(target=_backend_main, daemon=True)
            backend_thread.start()
            backend_url = backend_url_queue.get(timeout=1)

            proxy_url_queue: queue.Queue[str] = queue.Queue()
            proxy_thread = threading.Thread(
                target=run_proxy,
                kwargs={
                    "backend_url": backend_url,
                    "cwd": "/tmp/project",
                    "proxy_auth_token": "proxy-auth-token",
                    "data_dir": data_dir,
                    "idle_timeout_seconds": 1.0,
                    "on_listen": proxy_url_queue.put,
                    "new_thread_profile_seed": "provider2",
                    "new_thread_profile_model_seed": "provider2-model",
                    "new_thread_profile_model_provider_seed": "provider2_api",
                    "new_thread_memory_mode_seed": "read",
                },
                daemon=True,
            )
            proxy_thread.start()
            proxy_url = proxy_url_queue.get(timeout=1)

            try:
                with connect(
                    proxy_url,
                    open_timeout=1,
                    max_size=None,
                    additional_headers={"Authorization": "Bearer proxy-auth-token"},
                ) as ws:
                    ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "thread/start",
                                "params": {},
                            }
                        )
                    )
                    forwarded = backend_messages.get(timeout=1)
                    self.assertEqual(forwarded["method"], "thread/start")
                    self.assertEqual(forwarded["params"]["cwd"], "/tmp/project")
                    self.assertEqual(
                        forwarded["params"]["config"]["memories"],
                        {
                            "use_memories": True,
                            "generate_memories": False,
                        },
                    )
                    self.assertNotIn("profile", forwarded["params"]["config"])
                    self.assertEqual(forwarded["params"]["model"], "provider2-model")
                    self.assertEqual(forwarded["params"]["modelProvider"], "provider2_api")

                backend_disconnects.get(timeout=1)
                time.sleep(0.1)

                with connect(
                    proxy_url,
                    open_timeout=1,
                    max_size=None,
                    additional_headers={"Authorization": "Bearer proxy-auth-token"},
                ) as ws:
                    ws.send(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 2,
                                "method": "thread/start",
                                "params": {},
                            }
                        )
                    )
                    self.assertEqual(
                        json.loads(ws.recv()),
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "error": {
                                "code": -32002,
                                "message": (
                                    "当前 fcodex 启动级 seed 的上一条新建 thread 请求在连接关闭时结果未知；"
                                    "当前按 fail-close 拒绝继续，请退出并重新启动 fcodex 后再试。"
                                ),
                            },
                        },
                    )

                with self.assertRaises(queue.Empty):
                    backend_messages.get_nowait()

                proxy_thread.join(timeout=2)
                self.assertFalse(proxy_thread.is_alive())
            finally:
                backend_server = backend_server_ref.get("server")
                if backend_server is not None:
                    backend_server.shutdown()
                backend_thread.join(timeout=1)

    def test_proxy_default_idle_timeout_keeps_startup_reconnect_window(self) -> None:
        self.assertGreaterEqual(_DEFAULT_IDLE_TIMEOUT_SECONDS, 30.0)

    def test_proxy_exits_when_parent_process_disappears(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "instance"
            AppServerWebsocketAuthTokenStore(data_dir).ensure()
            proxy_url_queue: queue.Queue[str] = queue.Queue()
            with patch("bot.fcodex_proxy.process_exists", return_value=False) as mock_process_exists:
                proxy_thread = threading.Thread(
                    target=run_proxy,
                    kwargs={
                        "backend_url": "ws://127.0.0.1:8765",
                        "cwd": "/tmp/project",
                        "proxy_auth_token": "proxy-auth-token",
                        "data_dir": data_dir,
                        "parent_pid": 4321,
                        "on_listen": proxy_url_queue.put,
                    },
                    daemon=True,
                )
                proxy_thread.start()
                proxy_url = proxy_url_queue.get(timeout=1)
                self.assertTrue(proxy_url.startswith("ws://127.0.0.1:"))
                proxy_thread.join(timeout=1)

            self.assertFalse(proxy_thread.is_alive())
            self.assertEqual(mock_process_exists.call_args_list[0].args, (4321,))

    def test_proxy_parent_pid_mode_still_honors_idle_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "instance"
            AppServerWebsocketAuthTokenStore(data_dir).ensure()
            proxy_url_queue: queue.Queue[str] = queue.Queue()
            with patch("bot.fcodex_proxy.process_exists", return_value=True):
                proxy_thread = threading.Thread(
                    target=run_proxy,
                    kwargs={
                        "backend_url": "ws://127.0.0.1:8765",
                        "cwd": "/tmp/project",
                        "proxy_auth_token": "proxy-auth-token",
                        "data_dir": data_dir,
                        "parent_pid": 4321,
                        "idle_timeout_seconds": 0.1,
                        "on_listen": proxy_url_queue.put,
                    },
                    daemon=True,
                )
                proxy_thread.start()
                proxy_url = proxy_url_queue.get(timeout=1)
                self.assertTrue(proxy_url.startswith("ws://127.0.0.1:"))
                proxy_thread.join(timeout=1)

            self.assertFalse(proxy_thread.is_alive())


class ProxyInteractionGateTests(unittest.TestCase):
    class _FakeWs:
        def __init__(self) -> None:
            self.sent: list[str | bytes] = []

        def send(self, payload: str | bytes) -> None:
            self.sent.append(payload)

    @staticmethod
    def _decode_payload(payload: str | bytes) -> dict:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return json.loads(payload)

    def test_non_owner_turn_start_gets_local_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = InteractionLeaseStore(data_dir)
            store.force_acquire(
                "thread-1",
                make_fcodex_interaction_holder("fcodex:other", owner_pid=os.getpid()),
            )
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                holder_pid=os.getpid(),
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "turn/start",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            self.assertEqual(backend_ws.sent, [])
            error = self._decode_payload(client_ws.sent[-1])
            self.assertEqual(error["id"], 1)
            self.assertIn("当前线程正由其他终端执行", error["error"]["message"])

    def test_turn_start_ignores_legacy_saved_thread_profile_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            ThreadResumeProfileStore(data_dir).save(
                "thread-1",
                profile="provider2",
                model="provider2-model",
                model_provider="provider2_api",
                reasoning_effort="high",
            )
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                global_data_dir=data_dir,
                holder_pid=os.getpid(),
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "turn/start",
                        "params": {
                            "threadId": "thread-1",
                            "input": [{"type": "text", "text": "hello"}],
                            "collaborationMode": {
                                "mode": "default",
                                "settings": {"model": "gpt-5.4"},
                            },
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            forwarded = self._decode_payload(backend_ws.sent[-1])
            self.assertNotIn("model", forwarded["params"])
            self.assertNotIn("config", forwarded["params"])
            self.assertNotIn("modelProvider", forwarded["params"])
        self.assertEqual(
            forwarded["params"]["collaborationMode"]["settings"]["model"],
            "gpt-5.4",
        )
        self.assertNotIn("effort", forwarded["params"])
        self.assertNotIn("reasoning_effort", forwarded["params"]["collaborationMode"]["settings"])

    def test_model_list_response_rewrites_existing_launch_profile_item_as_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                global_data_dir=data_dir,
                holder_pid=os.getpid(),
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            with patch(
                "bot.fcodex_proxy.resolve_profile_model_metadata",
                return_value={
                    "model": "provider2-model",
                    "displayName": "Provider Two",
                    "supports_reasoning_summaries": False,
                },
            ):
                gate.handle_client_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "model/list",
                            "params": {},
                        }
                    ),
                    client_ws=client_ws,
                    backend_ws=backend_ws,
                )
                gate.handle_backend_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {
                                "data": [
                                    {
                                        "id": "openai/gpt-5.4",
                                        "model": "gpt-5.4",
                                        "displayName": "GPT-5.4",
                                        "description": "OpenAI model",
                                        "hidden": False,
                                        "supportedReasoningEfforts": [],
                                        "defaultReasoningEffort": "medium",
                                        "inputModalities": ["text"],
                                        "serviceTiers": [],
                                        "isDefault": True,
                                    },
                                    {
                                        "id": "provider2/provider2-model",
                                        "model": "provider2-model",
                                        "displayName": "Old Provider Two",
                                        "description": "Provider Two model",
                                        "hidden": False,
                                        "supportedReasoningEfforts": [],
                                        "defaultReasoningEffort": "medium",
                                        "inputModalities": ["text"],
                                        "serviceTiers": [],
                                        "isDefault": False,
                                    },
                                ]
                            },
                        }
                    ),
                    client_ws=client_ws,
                    backend_ws=backend_ws,
                )

            forwarded = self._decode_payload(client_ws.sent[-1])
            self.assertEqual(forwarded["result"]["data"][0]["model"], "gpt-5.4")
            self.assertFalse(forwarded["result"]["data"][0]["isDefault"])
            self.assertEqual(forwarded["result"]["data"][1]["id"], "provider2/provider2-model")
            self.assertEqual(forwarded["result"]["data"][1]["model"], "provider2-model")
            self.assertEqual(forwarded["result"]["data"][1]["displayName"], "Provider Two")
            self.assertTrue(forwarded["result"]["data"][1]["isDefault"])

    def test_model_list_response_does_not_inject_incomplete_synthetic_launch_profile_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                global_data_dir=data_dir,
                holder_pid=os.getpid(),
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            with patch(
                "bot.fcodex_proxy.resolve_profile_model_metadata",
                return_value={
                    "model": "provider2-model",
                    "displayName": "Provider Two",
                    "supports_reasoning_summaries": False,
                },
            ):
                gate.handle_client_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "model/list",
                            "params": {},
                        }
                    ),
                    client_ws=client_ws,
                    backend_ws=backend_ws,
                )
                gate.handle_backend_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "result": {
                                "data": [
                                    {
                                        "id": "openai/gpt-5.4",
                                        "model": "gpt-5.4",
                                        "displayName": "GPT-5.4",
                                        "description": "OpenAI model",
                                        "hidden": False,
                                        "supportedReasoningEfforts": [],
                                        "defaultReasoningEffort": "medium",
                                        "inputModalities": ["text"],
                                        "serviceTiers": [],
                                        "isDefault": True,
                                    },
                                ]
                            },
                        }
                    ),
                    client_ws=client_ws,
                    backend_ws=backend_ws,
                )

            forwarded = self._decode_payload(client_ws.sent[-1])
            self.assertEqual(len(forwarded["result"]["data"]), 1)
            self.assertEqual(forwarded["result"]["data"][0]["id"], "openai/gpt-5.4")
            self.assertEqual(forwarded["result"]["data"][0]["model"], "gpt-5.4")
            self.assertTrue(forwarded["result"]["data"][0]["isDefault"])

    def test_thread_resume_gets_local_error_when_other_running_instance_still_reports_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                global_data_dir=data_dir,
                instance_name="explorer",
                service_token="svc-token",
                holder_pid=os.getpid(),
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            with patch(
                "bot.fcodex_proxy.preview_thread_global_loaded_gate",
                return_value=Mock(
                    allowed=False,
                    reason_text=(
                        "当前 thread 仍由运行中的实例 `default` 保持为 loaded (`idle`)；"
                        "当前不支持跨实例 hot takeover。"
                    ),
                ),
            ):
                gate.handle_client_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "thread/resume",
                            "params": {"threadId": "thread-1"},
                        }
                    ),
                    client_ws=client_ws,
                    backend_ws=backend_ws,
                )

            self.assertEqual(backend_ws.sent, [])
            error = self._decode_payload(client_ws.sent[-1])
            self.assertEqual(error["id"], 1)
            self.assertIn("不支持跨实例 hot takeover", error["error"]["message"])

    def test_local_error_response_requires_request_id(self) -> None:
        from bot.fcodex_proxy import _send_local_error_response

        with self.assertRaisesRegex(ValueError, "requires a request id"):
            _send_local_error_response(self._FakeWs(), "", "boom")

    def test_non_owner_does_not_receive_interactive_server_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            store = InteractionLeaseStore(data_dir)
            store.force_acquire(
                "thread-1",
                make_fcodex_interaction_holder("fcodex:other", owner_pid=os.getpid()),
            )
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                holder_pid=os.getpid(),
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "req-1",
                        "method": "item/commandExecution/requestApproval",
                        "params": {"threadId": "thread-1", "command": "ls"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            self.assertEqual(client_ws.sent, [])

    def test_owner_lease_is_released_when_turn_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                holder_pid=os.getpid(),
            )
            store = InteractionLeaseStore(data_dir)
            store.force_acquire("thread-1", gate._holder)
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/completed",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            self.assertIsNone(store.load("thread-1"))
            forwarded = self._decode_payload(client_ws.sent[-1])
            self.assertEqual(forwarded["method"], "turn/completed")

    def test_gate_close_releases_started_turn_lease_after_success_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                holder_pid=os.getpid(),
            )
            store = InteractionLeaseStore(data_dir)
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "turn/start",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNotNone(store.load("thread-1"))

            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"ok": True},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNotNone(store.load("thread-1"))

            gate.close()

            self.assertIsNone(store.load("thread-1"))

    def test_gate_close_releases_pending_turn_start_lease_without_backend_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                holder_pid=os.getpid(),
            )
            store = InteractionLeaseStore(data_dir)
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "turn/start",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNotNone(store.load("thread-1"))

            gate.close()

            self.assertIsNone(store.load("thread-1"))

    def test_gate_close_releases_existing_owner_lease_after_interactive_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=data_dir,
                holder_pid=os.getpid(),
            )
            store = InteractionLeaseStore(data_dir)
            store.force_acquire("thread-1", gate._holder)
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "req-1",
                        "method": "item/commandExecution/requestApproval",
                        "params": {"threadId": "thread-1", "command": "ls"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNotNone(store.load("thread-1"))

            gate.close()

            self.assertIsNone(store.load("thread-1"))

    def test_thread_start_request_injects_initial_thread_profile_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/start",
                        "params": {
                            "cwd": "/tmp/project",
                            "model": "stale-local-model",
                            "modelProvider": "stale-local-provider",
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            forwarded = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(forwarded["method"], "thread/start")
            self.assertEqual(forwarded["params"]["model"], "provider2-model")
            self.assertEqual(forwarded["params"]["modelProvider"], "provider2_api")
            self.assertNotIn("config", forwarded["params"])

    def test_sequential_second_thread_start_request_fails_closed_while_initial_seed_is_reserved(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
                new_thread_memory_mode_seed="read",
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            forwarded_first = self._decode_payload(backend_ws.sent[0])
            self.assertEqual(
                forwarded_first["params"]["config"]["memories"],
                {
                    "use_memories": True,
                    "generate_memories": False,
                },
            )
            self.assertNotIn("profile", forwarded_first["params"]["config"])
            self.assertEqual(forwarded_first["params"]["model"], "provider2-model")
            self.assertEqual(forwarded_first["params"]["modelProvider"], "provider2_api")

            self.assertEqual(len(backend_ws.sent), 1)
            self.assertEqual(
                self._decode_payload(client_ws.sent[-1]),
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "error": {
                        "code": -32002,
                        "message": (
                            "当前 fcodex 启动级 seed 正在等待另一条新建 thread 请求返回；"
                            "请等待上一条 `thread/start` 完成或失败后再试。"
                        ),
                    },
                },
            )

            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"thread": {"id": "thread-1"}},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "turn-1", "status": "completed"},
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            profile_first = ThreadResumeProfileStore(root_dir).load("thread-1")
            profile_second = ThreadResumeProfileStore(root_dir).load("thread-2")
            memory_first = ThreadMemoryModeStore(root_dir).load("thread-1")
            memory_second = ThreadMemoryModeStore(root_dir).load("thread-2")

            self.assertIsNone(profile_first)
            self.assertIsNone(profile_second)
            self.assertIsNotNone(memory_first)
            assert memory_first is not None
            self.assertEqual(memory_first.mode, "read")
            self.assertIsNone(memory_second)

    def test_concurrent_thread_start_requests_across_connections_fail_closed_while_seed_is_reserved(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            shared_seed_state = _ProxyThreadSeedState(
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
                new_thread_memory_mode_seed="read",
            )
            gate_first = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                thread_seed_state=shared_seed_state,
            )
            gate_second = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                thread_seed_state=shared_seed_state,
            )
            client_ws_first = self._FakeWs()
            backend_ws_first = self._FakeWs()
            client_ws_second = self._FakeWs()
            backend_ws_second = self._FakeWs()
            reserve_barrier = threading.Barrier(2)
            original_reserve = shared_seed_state.reserve_new_thread_seed_for_request

            def synchronized_reserve(*, owner_key: str, request_id: object) -> str:
                reserve_barrier.wait(timeout=1)
                return original_reserve(owner_key=owner_key, request_id=request_id)

            shared_seed_state.reserve_new_thread_seed_for_request = synchronized_reserve  # type: ignore[method-assign]

            def _start_thread(gate: _ProxyInteractionGate, client_ws, backend_ws, request_id: int) -> None:
                gate.handle_client_message(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "method": "thread/start",
                            "params": {"cwd": "/tmp/project"},
                        }
                    ),
                    client_ws=client_ws,
                    backend_ws=backend_ws,
                )

            first_thread = threading.Thread(
                target=_start_thread,
                args=(gate_first, client_ws_first, backend_ws_first, 1),
            )
            second_thread = threading.Thread(
                target=_start_thread,
                args=(gate_second, client_ws_second, backend_ws_second, 2),
            )
            first_thread.start()
            second_thread.start()
            first_thread.join(timeout=1)
            second_thread.join(timeout=1)

            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())

            backend_payloads = [
                self._decode_payload(payload)
                for ws in (backend_ws_first, backend_ws_second)
                for payload in ws.sent
            ]
            self.assertEqual(len(backend_payloads), 1)

            forwarded = backend_payloads[0]
            self.assertEqual(
                forwarded["params"]["config"]["memories"],
                {
                    "use_memories": True,
                    "generate_memories": False,
                },
            )
            self.assertNotIn("profile", forwarded["params"]["config"])
            self.assertEqual(forwarded["params"]["model"], "provider2-model")
            self.assertEqual(forwarded["params"]["modelProvider"], "provider2_api")

            client_payloads = [
                self._decode_payload(payload)
                for ws in (client_ws_first, client_ws_second)
                for payload in ws.sent
            ]
            self.assertEqual(len(client_payloads), 1)
            self.assertEqual(
                client_payloads[0],
                {
                    "jsonrpc": "2.0",
                    "id": 1 if backend_ws_second.sent else 2,
                    "error": {
                        "code": -32002,
                        "message": (
                            "当前 fcodex 启动级 seed 正在等待另一条新建 thread 请求返回；"
                            "请等待上一条 `thread/start` 完成或失败后再试。"
                        ),
                    },
                },
            )

    def test_gate_close_marks_shared_initial_seed_outcome_unknown_for_reconnect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            shared_seed_state = _ProxyThreadSeedState(
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
                new_thread_memory_mode_seed="read",
            )
            gate_first = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                thread_seed_state=shared_seed_state,
            )
            gate_second = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                thread_seed_state=shared_seed_state,
            )
            client_ws_first = self._FakeWs()
            backend_ws_first = self._FakeWs()
            client_ws_second = self._FakeWs()
            backend_ws_second = self._FakeWs()

            gate_first.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws_first,
                backend_ws=backend_ws_first,
            )
            gate_first.close()

            gate_second.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws_second,
                backend_ws=backend_ws_second,
            )

            self.assertEqual(backend_ws_second.sent, [])
            self.assertEqual(
                self._decode_payload(client_ws_second.sent[-1]),
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "error": {
                        "code": -32002,
                        "message": (
                            "当前 fcodex 启动级 seed 的上一条新建 thread 请求在连接关闭时结果未知；"
                            "当前按 fail-close 拒绝继续，请退出并重新启动 fcodex 后再试。"
                        ),
                    },
                },
            )

    def test_thread_start_error_releases_initial_seed_reservation_for_later_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
                new_thread_memory_mode_seed="read",
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "error": {"code": -32000, "message": "start failed"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            forwarded = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(
                forwarded["params"]["config"]["memories"],
                {
                    "use_memories": True,
                    "generate_memories": False,
                },
            )
            self.assertNotIn("profile", forwarded["params"]["config"])
            self.assertEqual(forwarded["params"]["model"], "provider2-model")
            self.assertEqual(forwarded["params"]["modelProvider"], "provider2_api")

    def test_thread_start_response_does_not_promote_new_thread_profile_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"thread": {"id": "thread-1"}},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNone(ThreadResumeProfileStore(root_dir).load("thread-1"))
            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            forwarded_second = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(forwarded_second["method"], "thread/start")
            self.assertNotIn("config", forwarded_second["params"])
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {"thread": {"id": "thread-2"}},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "turn-1", "status": "completed"},
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            first = ThreadResumeProfileStore(root_dir).load("thread-1")
            second = ThreadResumeProfileStore(root_dir).load("thread-2")

            self.assertIsNone(first)
            self.assertIsNone(second)

    def test_pending_new_thread_seed_survives_reconnect_until_first_completed_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            shared_seed_state = _ProxyThreadSeedState(
                new_thread_profile_seed="provider2",
                new_thread_profile_model_seed="provider2-model",
                new_thread_profile_model_provider_seed="provider2_api",
                new_thread_memory_mode_seed="read",
            )
            gate_first = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                thread_seed_state=shared_seed_state,
            )
            gate_second = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                thread_seed_state=shared_seed_state,
            )
            client_ws_first = self._FakeWs()
            backend_ws_first = self._FakeWs()
            client_ws_second = self._FakeWs()
            backend_ws_second = self._FakeWs()

            gate_first.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws_first,
                backend_ws=backend_ws_first,
            )
            gate_first.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"thread": {"id": "thread-1"}},
                    }
                ),
                client_ws=client_ws_first,
                backend_ws=backend_ws_first,
            )
            gate_first.close()

            gate_second.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/resume",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws_second,
                backend_ws=backend_ws_second,
            )

            resumed = self._decode_payload(backend_ws_second.sent[-1])
            self.assertEqual(resumed["params"]["threadId"], "thread-1")
            self.assertEqual(
                resumed["params"]["config"]["memories"],
                {
                    "use_memories": True,
                    "generate_memories": False,
                },
            )
            self.assertNotIn("profile", resumed["params"]["config"])
            self.assertNotIn("model", resumed["params"])
            self.assertNotIn("modelProvider", resumed["params"])

            gate_second.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "turn-1", "status": "completed"},
                        },
                    }
                ),
                client_ws=client_ws_second,
                backend_ws=backend_ws_second,
            )

            profile_record = ThreadResumeProfileStore(root_dir).load("thread-1")
            memory_record = ThreadMemoryModeStore(root_dir).load("thread-1")

            self.assertIsNone(profile_record)
            self.assertIsNotNone(memory_record)
            assert memory_record is not None
            self.assertEqual(memory_record.mode, "read")

    def test_thread_start_request_promotes_new_thread_memory_mode_seed_after_first_completed_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
                new_thread_memory_mode_seed="read",
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            forwarded = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(forwarded["method"], "thread/start")
            self.assertEqual(
                forwarded["params"]["config"]["memories"],
                {
                    "use_memories": True,
                    "generate_memories": False,
                },
            )

            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"thread": {"id": "thread-1"}},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNone(ThreadMemoryModeStore(root_dir).load("thread-1"))
            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/start",
                        "params": {"cwd": "/tmp/project"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            forwarded_second = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(forwarded_second["method"], "thread/start")
            self.assertNotIn("config", forwarded_second["params"])
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "result": {"thread": {"id": "thread-2"}},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/completed",
                        "params": {
                            "threadId": "thread-1",
                            "turn": {"id": "turn-1", "status": "completed"},
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            first = ThreadMemoryModeStore(root_dir).load("thread-1")
            second = ThreadMemoryModeStore(root_dir).load("thread-2")

            self.assertIsNotNone(first)
            assert first is not None
            self.assertEqual(first.mode, "read")
            self.assertIsNone(second)

    def test_thread_resume_request_injects_saved_thread_memory_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            ThreadMemoryModeStore(root_dir).save("thread-1", mode="read_write")
            ThreadResumeProfileStore(root_dir).save(
                "thread-1",
                profile="provider2",
                model="provider2-model",
                model_provider="provider2_api",
                reasoning_effort="high",
            )
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/resume",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            forwarded = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(forwarded["method"], "thread/resume")
            self.assertEqual(
                forwarded["params"]["config"]["memories"],
                {
                    "use_memories": True,
                    "generate_memories": True,
                },
            )
            self.assertNotIn("profiles", forwarded["params"]["config"])

    def test_thread_resume_request_ignores_saved_thread_profile_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            ThreadResumeProfileStore(root_dir).save(
                "thread-1",
                profile="provider2",
                model="provider2-model",
                model_provider="provider2_api",
                reasoning_effort="high",
            )
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/resume",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            forwarded = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(forwarded["method"], "thread/resume")
            self.assertNotIn("model", forwarded["params"])
            self.assertNotIn("modelProvider", forwarded["params"])
            self.assertNotIn("config", forwarded["params"])

    def test_thread_resume_request_ignores_incomplete_saved_profile_slice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            ThreadResumeProfileStore(root_dir).save(
                "thread-1",
                profile="provider2",
                model="",
                model_provider="",
            )
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                holder_pid=os.getpid(),
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/resume",
                        "params": {
                            "threadId": "thread-1",
                            "model": "stale-local-model",
                            "modelProvider": "stale-local-provider",
                            "config": {"profile": "provider2"},
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            forwarded = self._decode_payload(backend_ws.sent[-1])
            self.assertEqual(forwarded["params"]["model"], "stale-local-model")
            self.assertEqual(forwarded["params"]["modelProvider"], "stale-local-provider")

    def test_runtime_lease_survives_lookup_connection_close_until_proxy_shutdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            keeper = _ProxyRuntimeLeaseKeeper(
                global_data_dir=root_dir,
                instance_name="explorer",
                service_token="svc-token",
                holder_pid=os.getpid(),
            )
            first_gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                instance_name="explorer",
                service_token="svc-token",
                holder_pid=os.getpid(),
                runtime_lease_keeper=keeper,
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            first_gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/resume",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            first_gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "result": {"thread": {"id": "thread-1"}},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            first_gate.close()

            self.assertIsNotNone(ThreadRuntimeLeaseStore(root_dir).load("thread-1"))

            second_gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                instance_name="explorer",
                service_token="svc-token",
                holder_pid=os.getpid(),
                runtime_lease_keeper=keeper,
            )
            second_gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "thread/resume",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNotNone(ThreadRuntimeLeaseStore(root_dir).load("thread-1"))

            second_gate.close()
            keeper.close()
            self.assertIsNone(ThreadRuntimeLeaseStore(root_dir).load("thread-1"))

    def test_thread_status_not_loaded_releases_runtime_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root_dir = Path(tmpdir)
            keeper = _ProxyRuntimeLeaseKeeper(
                global_data_dir=root_dir,
                instance_name="explorer",
                service_token="svc-token",
                holder_pid=os.getpid(),
            )
            gate = _ProxyInteractionGate(
                cwd="/tmp/project",
                data_dir=root_dir,
                global_data_dir=root_dir,
                instance_name="explorer",
                service_token="svc-token",
                holder_pid=os.getpid(),
                runtime_lease_keeper=keeper,
            )
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "thread/resume",
                        "params": {"threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            self.assertIsNotNone(ThreadRuntimeLeaseStore(root_dir).load("thread-1"))

            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "thread/status/changed",
                        "params": {
                            "threadId": "thread-1",
                            "status": {"type": "notLoaded"},
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            self.assertIsNone(ThreadRuntimeLeaseStore(root_dir).load("thread-1"))


class SessionResolutionTests(unittest.TestCase):
    class _Adapter:
        def __init__(self, threads: list[ThreadSummary]) -> None:
            self.threads = threads

        def list_threads(
            self,
            *,
            cwd=None,
            limit=100,
            cursor=None,
            search_term=None,
            sort_key="updated_at",
            source_kinds=None,
            model_providers=None,
        ):
            del cwd
            del search_term
            del sort_key
            del source_kinds
            self.kwargs = {"limit": limit, "cursor": cursor, "model_providers": model_providers}
            start = int(cursor or 0)
            end = start + limit
            next_cursor = str(end) if end < len(self.threads) else None
            return list(self.threads[start:end]), next_cursor

        def list_threads_all(self, **kwargs):
            self.kwargs = kwargs
            return list(self.threads)

    def test_looks_like_thread_id(self) -> None:
        self.assertTrue(looks_like_thread_id("019d2e94-a475-7bc1-b2f7-a3ce37628ede"))
        self.assertFalse(looks_like_thread_id("demo"))

    def test_format_thread_match(self) -> None:
        thread = ThreadSummary(
            thread_id="019d2e94-a475-7bc1-b2f7-a3ce37628ede",
            cwd="/tmp/project",
            name="demo",
            preview="hello",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
            model_provider="provider2_api",
        )
        self.assertEqual(format_thread_match(thread), "`019d2e94…`@`provider2_api`")

    def test_resolve_resume_target_by_name_uses_cross_provider_listing(self) -> None:
        thread = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="hello",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
            model_provider="provider2_api",
        )
        adapter = self._Adapter([thread])

        resolved = resolve_resume_target_by_name(adapter, name="demo", limit=100)

        self.assertEqual(resolved.thread_id, "thread-1")
        self.assertEqual(adapter.kwargs["model_providers"], [])

    def test_resolve_resume_target_by_name_rejects_multiple_matches(self) -> None:
        thread_1 = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project-a",
            name="demo",
            preview="hello",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        thread_2 = ThreadSummary(
            thread_id="thread-2",
            cwd="/tmp/project-b",
            name="demo",
            preview="world",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        adapter = self._Adapter([thread_1, thread_2])

        with self.assertRaisesRegex(ValueError, "匹配到多个同名线程"):
            resolve_resume_target_by_name(adapter, name="demo", limit=100)

    def test_resolve_resume_target_by_name_scans_beyond_first_page_for_duplicate(self) -> None:
        threads = [
            ThreadSummary(
                thread_id=f"thread-{index}",
                cwd=f"/tmp/project-{index}",
                name="demo" if index in {1, 150} else f"name-{index}",
                preview="hello",
                created_at=0,
                updated_at=200 - index,
                source="cli",
                status="notLoaded",
            )
            for index in range(1, 151)
        ]
        adapter = self._Adapter(threads)

        with self.assertRaisesRegex(ValueError, "匹配到多个同名线程"):
            resolve_resume_target_by_name(adapter, name="demo", limit=100)

    def test_fcodex_remote_thread_target_type_hints_resolve(self) -> None:
        hints = get_type_hints(_resolve_thread_target_via_remote_backend)

        self.assertEqual(
            hints["return"],
            tuple[ThreadSummary | None, str | None],
        )


if __name__ == "__main__":
    unittest.main()
