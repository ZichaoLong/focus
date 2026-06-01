"""
基于 Codex app-server 的适配层。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from bot.approval_policy import normalize_approval_policy
from bot.adapters.base import (
    AgentAdapter,
    RuntimeConfigSummary,
    RuntimeModelSummary,
    RuntimeProfileSummary,
    ThreadGoalSummary,
    ThreadSnapshot,
    ThreadSummary,
    TurnInputItem,
)
from bot.codex_config_reader import (
    list_profile_v2_names,
    profile_v2_is_usable,
    resolve_profile_from_codex_config,
)
from bot.codex_protocol.client import CodexRpcClient
from bot.constants import DEFAULT_APP_SERVER_MODE, DEFAULT_APP_SERVER_URL, DEFAULT_SOURCE_KINDS
from bot.permissions_profile import (
    BUILTIN_PERMISSION_PROFILE_DANGER_FULL_ACCESS,
    PERMISSION_PROFILE_ID_TO_LEGACY_SANDBOX,
    normalize_permissions_profile_id,
)
from bot.stores.app_server_runtime_store import AppServerRuntimeStore
from bot.thread_memory_mode import (
    deep_merge_config_overrides,
    normalize_thread_memory_mode,
    thread_memory_mode_from_memories_config,
)
from bot.codex_protocol.client import CodexRpcError

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class CodexAppServerConfig:
    codex_command: str = "codex"
    app_server_mode: str = DEFAULT_APP_SERVER_MODE
    app_server_url: str = DEFAULT_APP_SERVER_URL
    connect_timeout_seconds: float = 15.0
    request_timeout_seconds: float = 30.0
    service_name: str = "feishu-codex"
    permissions_profile_id: str = BUILTIN_PERMISSION_PROFILE_DANGER_FULL_ACCESS
    approval_policy: str = "never"
    approvals_reviewer: str = "user"
    personality: str = "pragmatic"
    model: str = ""
    model_provider: str = ""
    service_tier: str = ""
    reasoning_effort: str = ""
    collaboration_mode: str = "default"
    new_thread_memory_mode_seed: str = ""
    managed_startup_profile: str = ""
    app_server_data_dir: str = ""
    source_kinds: list[str] = field(default_factory=lambda: DEFAULT_SOURCE_KINDS.copy())

    @property
    def sandbox(self) -> str:
        return PERMISSION_PROFILE_ID_TO_LEGACY_SANDBOX.get(self.permissions_profile_id, "danger-full-access")

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "CodexAppServerConfig":
        source_kinds = config.get("source_kinds") or DEFAULT_SOURCE_KINDS
        collaboration_mode = str(config.get("collaboration_mode", "default")).strip().lower() or "default"
        app_server_mode = str(config.get("app_server_mode", DEFAULT_APP_SERVER_MODE)).strip().lower() or DEFAULT_APP_SERVER_MODE
        if "default_thread_memory_mode" in config:
            raise ValueError("`default_thread_memory_mode` 已移除；请改用 `new_thread_memory_mode_seed`。")
        raw_new_thread_memory_mode_seed = str(config.get("new_thread_memory_mode_seed", "") or "").strip()
        if collaboration_mode not in {"default", "plan"}:
            raise ValueError("collaboration_mode 仅支持 default 或 plan")
        if app_server_mode not in {"managed", "remote"}:
            raise ValueError("app_server_mode 仅支持 managed 或 remote")
        return cls(
            codex_command=str(config.get("codex_command", "codex")),
            app_server_mode=app_server_mode,
            app_server_url=str(config.get("app_server_url", DEFAULT_APP_SERVER_URL)).strip() or DEFAULT_APP_SERVER_URL,
            connect_timeout_seconds=float(config.get("connect_timeout_seconds", 15)),
            request_timeout_seconds=float(config.get("request_timeout_seconds", 30)),
            service_name=str(config.get("service_name", "feishu-codex")),
            permissions_profile_id=normalize_permissions_profile_id(
                str(
                    config.get(
                        "permissions_profile_id",
                        config.get("permissions", config.get("sandbox", BUILTIN_PERMISSION_PROFILE_DANGER_FULL_ACCESS)),
                    )
                ),
                fallback=BUILTIN_PERMISSION_PROFILE_DANGER_FULL_ACCESS,
            ),
            approval_policy=normalize_approval_policy(
                str(config.get("approval_policy", "never")),
            ),
            approvals_reviewer=str(config.get("approvals_reviewer", "user")),
            personality=str(config.get("personality", "pragmatic")),
            model=str(config.get("model", "")),
            model_provider=str(config.get("model_provider", "")),
            service_tier=str(config.get("service_tier", "")),
            reasoning_effort=str(config.get("reasoning_effort", "")),
            collaboration_mode=collaboration_mode,
            new_thread_memory_mode_seed=(
                normalize_thread_memory_mode(raw_new_thread_memory_mode_seed)
                if raw_new_thread_memory_mode_seed
                else ""
            ),
            managed_startup_profile=str(config.get("managed_startup_profile", "") or "").strip(),
            source_kinds=[str(item) for item in source_kinds],
        )


class CodexAppServerAdapter(AgentAdapter):
    """通过 app-server 与 Codex 交互。"""

    def __init__(
        self,
        config: CodexAppServerConfig,
        *,
        on_notification: Callable[[str, dict[str, Any]], None] | None = None,
        on_request: Callable[[int | str, str, dict[str, Any]], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        app_server_runtime_store: AppServerRuntimeStore | None = None,
    ) -> None:
        self._config = config
        self._collaboration_mode_model: str | None = None
        # Workaround: turn/start 的稳定上游覆盖面里只有 model /
        # collaborationMode；startup baseline / create-resume model 只在
        # thread/start、thread/resume 这类线程边界请求上传递。
        # 因此缓存 thread/start 和 thread/resume 响应里后端解析好的
        # model，作为 collaborationMode.settings.model 的 fallback，
        # 避免后续 turn 退回到 model/list 的全局默认值。
        self._thread_resolved_model: dict[str, str] = {}
        self._rpc = CodexRpcClient(
            codex_command=config.codex_command,
            app_server_mode=config.app_server_mode,
            app_server_url=config.app_server_url,
            connect_timeout_seconds=config.connect_timeout_seconds,
            request_timeout_seconds=config.request_timeout_seconds,
            on_notification=on_notification,
            on_request=on_request,
            on_disconnect=on_disconnect,
            app_server_runtime_store=app_server_runtime_store,
            app_server_data_dir=config.app_server_data_dir or None,
            managed_startup_profile=config.managed_startup_profile or None,
        )

    def start(self) -> None:
        self._rpc.start()

    def stop(self) -> None:
        self._rpc.stop()
        self._clear_model_caches()

    def current_app_server_url(self) -> str:
        return self._rpc.current_app_server_url()

    def unsubscribe_thread(self, thread_id: str) -> None:
        """Unsubscribe from a thread so the app-server can unload it."""
        try:
            self._rpc.request("thread/unsubscribe", {"threadId": thread_id})
        except Exception:
            logger.debug("thread/unsubscribe failed for %s", thread_id[:12], exc_info=True)
        self._thread_resolved_model.pop(thread_id, None)

    def create_thread(
        self,
        *,
        cwd: str,
        profile: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        approval_policy: str | None = None,
        permissions_profile_id: str | None = None,
        sandbox: str | None = None,
    ) -> ThreadSnapshot:
        params = self._thread_params(
            cwd=cwd,
            include_service_name=True,
            profile=profile,
            config_overrides=config_overrides,
            model=model,
            model_provider=model_provider,
            approval_policy=approval_policy,
            permissions_profile_id=permissions_profile_id or sandbox,
        )
        result = self._request_with_permissions_fallback(
            "thread/start",
            params,
            legacy_field="sandbox",
            legacy_value=self._legacy_sandbox(permissions_profile_id or sandbox),
        )
        self._cache_thread_model(result)
        return self._snapshot_from_thread(result["thread"])

    def resume_thread(
        self,
        thread_id: str,
        *,
        profile: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        approval_policy: str | None = None,
        permissions_profile_id: str | None = None,
    ) -> ThreadSnapshot:
        effective_model, effective_model_provider = self._materialize_profile_slice(
            profile=profile,
            model=model,
            model_provider=model_provider,
        )
        params: dict[str, Any] = {"threadId": thread_id}
        if effective_model:
            params["model"] = effective_model
        if effective_model_provider:
            params["modelProvider"] = effective_model_provider
        if approval_policy:
            params["approvalPolicy"] = approval_policy
        if permissions_profile_id:
            params["permissions"] = normalize_permissions_profile_id(
                permissions_profile_id,
                fallback=self._config.permissions_profile_id,
            )
        merged_config = self._merge_request_config(profile=profile, config_overrides=config_overrides)
        if merged_config:
            params["config"] = merged_config
        result = self._request_with_permissions_fallback(
            "thread/resume",
            params,
            legacy_field="sandbox",
            legacy_value=self._legacy_sandbox(permissions_profile_id),
        )
        self._cache_thread_model(result)
        return self._snapshot_from_thread(result["thread"])

    def list_threads(
        self,
        *,
        cwd: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
        search_term: str | None = None,
        sort_key: str | None = None,
        source_kinds: list[str] | None = None,
        model_providers: list[str] | None = None,
    ) -> tuple[list[ThreadSummary], str | None]:
        params = _compact(
            {
                "cwd": cwd,
                "limit": limit,
                "cursor": cursor,
                "searchTerm": search_term,
                "sortKey": sort_key,
                "sourceKinds": source_kinds or self._config.source_kinds,
            }
        )
        if model_providers is not None:
            # app-server 将显式空列表解释为“不按 provider 过滤”。
            params["modelProviders"] = model_providers
        result = self._rpc.request("thread/list", params)
        data = [self._summary_from_thread(item) for item in result.get("data", [])]
        return data, result.get("nextCursor")

    def read_thread(self, thread_id: str, *, include_turns: bool = False) -> ThreadSnapshot:
        result = self._rpc.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": include_turns},
        )
        return self._snapshot_from_thread(result["thread"])

    def get_thread_goal(self, thread_id: str) -> ThreadGoalSummary | None:
        result = self._rpc.request("thread/goal/get", {"threadId": thread_id})
        goal = result.get("goal")
        if not isinstance(goal, dict):
            return None
        return self._goal_from_result(goal)

    def set_thread_goal(
        self,
        thread_id: str,
        *,
        objective: str | None = None,
        status: str | None = None,
        token_budget: int | None = None,
    ) -> ThreadGoalSummary:
        result = self._rpc.request(
            "thread/goal/set",
            _compact(
                {
                    "threadId": thread_id,
                    "objective": objective,
                    "status": status,
                    "tokenBudget": token_budget,
                }
            ),
        )
        return self._goal_from_result(result["goal"])

    def clear_thread_goal(self, thread_id: str) -> bool:
        result = self._rpc.request("thread/goal/clear", {"threadId": thread_id})
        return bool(result.get("cleared"))

    def read_runtime_config(self, *, cwd: str | None = None) -> RuntimeConfigSummary:
        result = self._rpc.request("config/read", _compact({"includeLayers": True, "cwd": cwd}))
        return self._runtime_config_from_result(result)

    def list_models(self, *, include_hidden: bool = False) -> list[RuntimeModelSummary]:
        result = self._rpc.request(
            "model/list",
            _compact(
                {
                    "includeHidden": True if include_hidden else None,
                }
            ),
        )
        return self._model_summaries_from_result(result)

    def list_loaded_thread_ids(self) -> list[str]:
        result = self._rpc.request("thread/loaded/list", {})
        data = result.get("data") or []
        return [str(item).strip() for item in data if str(item).strip()]

    def update_thread_settings(
        self,
        thread_id: str,
        *,
        approval_policy: str | None = None,
        permissions_profile_id: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        collaboration_mode: str | None = None,
    ) -> None:
        effective_model = model or None
        effective_reasoning = reasoning_effort or None
        effective_collaboration_mode = collaboration_mode or None
        params: dict[str, Any] = {
            "threadId": thread_id,
            "approvalPolicy": approval_policy or None,
            "model": effective_model,
            "effort": effective_reasoning,
        }
        if effective_collaboration_mode:
            params["collaborationMode"] = self._collaboration_mode_payload(
                effective_collaboration_mode,
                model=effective_model,
                thread_id=thread_id,
                reasoning_effort=effective_reasoning,
            )
        if permissions_profile_id:
            params["permissions"] = normalize_permissions_profile_id(
                permissions_profile_id,
                fallback=self._config.permissions_profile_id,
            )
        self._request_with_permissions_fallback(
            "thread/settings/update",
            _compact(params),
            legacy_field="sandboxPolicy",
            legacy_value=self._legacy_sandbox_policy(permissions_profile_id),
        )

    def set_active_profile(self, profile: str) -> RuntimeConfigSummary:
        del profile
        raise RuntimeError("上游已不支持运行时 active profile 切换；请改用实例级 startup `/profile`。")

    def compact_thread(self, thread_id: str) -> None:
        self._rpc.request(
            "thread/compact/start",
            {
                "threadId": thread_id,
            },
        )

    def rename_thread(self, thread_id: str, name: str) -> None:
        self._rpc.request("thread/name/set", {"threadId": thread_id, "name": name})

    def archive_thread(self, thread_id: str) -> None:
        self._rpc.request("thread/archive", {"threadId": thread_id})

    def start_turn(
        self,
        *,
        thread_id: str,
        input_items: list[TurnInputItem],
        cwd: str | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        profile: str | None = None,
        approval_policy: str | None = None,
        permissions_profile_id: str | None = None,
        sandbox: str | None = None,
        reasoning_effort: str | None = None,
        collaboration_mode: str | None = None,
    ) -> dict[str, Any]:
        effective_model = model or self._config.model or None
        effective_reasoning = reasoning_effort or self._config.reasoning_effort or None
        effective_collaboration_mode = collaboration_mode or self._config.collaboration_mode or "default"
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [dict(item) for item in input_items],
            "cwd": cwd,
            "model": effective_model,
            "approvalPolicy": approval_policy or self._config.approval_policy or None,
            "approvalsReviewer": self._config.approvals_reviewer or None,
            "effort": effective_reasoning,
            "personality": self._config.personality or None,
            "serviceTier": self._config.service_tier or None,
        }
        params["permissions"] = normalize_permissions_profile_id(
            permissions_profile_id or sandbox or self._config.permissions_profile_id,
            fallback=self._config.permissions_profile_id,
        )
        params["collaborationMode"] = self._collaboration_mode_payload(
            effective_collaboration_mode,
            model=effective_model,
            thread_id=thread_id,
            reasoning_effort=effective_reasoning,
        )
        return self._request_with_permissions_fallback(
            "turn/start",
            _compact(params),
            legacy_field="sandboxPolicy",
            legacy_value=self._legacy_sandbox_policy(permissions_profile_id or sandbox),
        )

    def interrupt_turn(self, *, thread_id: str, turn_id: str) -> None:
        self._rpc.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})

    def respond(self, request_id: int | str, *, result: dict | None = None, error: dict | None = None) -> None:
        self._rpc.respond(request_id, result=result, error=error)

    def list_threads_all(
        self,
        *,
        cwd: str | None = None,
        limit: int = 100,
        search_term: str | None = None,
        sort_key: str = "updated_at",
        source_kinds: list[str] | None = None,
        model_providers: list[str] | None = None,
    ) -> list[ThreadSummary]:
        items: list[ThreadSummary] = []
        cursor: str | None = None
        while len(items) < limit:
            page_size = min(50, limit - len(items))
            page, cursor = self.list_threads(
                cwd=cwd,
                limit=page_size,
                cursor=cursor,
                search_term=search_term,
                sort_key=sort_key,
                source_kinds=source_kinds,
                model_providers=model_providers,
            )
            items.extend(page)
            if not cursor:
                break
        return items

    def _thread_params(
        self,
        *,
        cwd: str,
        include_service_name: bool,
        profile: str | None = None,
        config_overrides: dict[str, Any] | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        approval_policy: str | None = None,
        permissions_profile_id: str | None = None,
        sandbox: str | None = None,
    ) -> dict[str, Any]:
        resolved_model, resolved_model_provider = self._materialize_profile_slice(
            profile=profile,
            model=model,
            model_provider=model_provider,
        )
        params: dict[str, Any] = {
            "cwd": cwd,
            "approvalPolicy": approval_policy or self._config.approval_policy or None,
            "approvalsReviewer": self._config.approvals_reviewer or None,
            "personality": self._config.personality or None,
            "model": resolved_model or self._config.model or None,
            "modelProvider": resolved_model_provider or self._config.model_provider or None,
            "serviceTier": self._config.service_tier or None,
        }
        params["permissions"] = normalize_permissions_profile_id(
            permissions_profile_id or sandbox or self._config.permissions_profile_id,
            fallback=self._config.permissions_profile_id,
        )
        merged_config = self._merge_request_config(profile=profile, config_overrides=config_overrides)
        if merged_config:
            params["config"] = merged_config
        if include_service_name:
            params["serviceName"] = self._config.service_name or None
        return _compact(params)

    def _request_with_permissions_fallback(
        self,
        method: str,
        params: dict[str, Any],
        *,
        legacy_field: str,
        legacy_value: Any,
    ) -> dict[str, Any]:
        try:
            return self._rpc.request(method, params)
        except CodexRpcError as exc:
            if not self._should_retry_without_permissions(exc.error, params):
                raise
            retry_params = dict(params)
            retry_params.pop("permissions", None)
            if legacy_value is not None:
                retry_params[legacy_field] = legacy_value
            logger.info("rpc %s 不支持 permissions 字段，回退到 legacy %s", method, legacy_field)
            return self._rpc.request(method, retry_params)

    @staticmethod
    def _should_retry_without_permissions(error: dict[str, Any], params: dict[str, Any]) -> bool:
        if "permissions" not in params:
            return False
        code = error.get("code")
        message = str(error.get("message") or "").lower()
        if code == -32602 and "permissions" in message:
            return True
        return code == -32600 and "permissions" in message

    @staticmethod
    def _legacy_sandbox(value: str | None) -> str | None:
        normalized = normalize_permissions_profile_id(value or "")
        return PERMISSION_PROFILE_ID_TO_LEGACY_SANDBOX.get(normalized)

    @classmethod
    def _legacy_sandbox_policy(cls, value: str | None) -> dict[str, Any] | None:
        legacy = cls._legacy_sandbox(value)
        if legacy == "danger-full-access":
            return {"type": "dangerFullAccess"}
        if legacy == "read-only":
            return {
                "type": "readOnly",
                "access": {"type": "fullAccess"},
                "networkAccess": False,
            }
        if legacy == "workspace-write":
            return {
                "type": "workspaceWrite",
                "writableRoots": [],
                "readOnlyAccess": {"type": "fullAccess"},
                "networkAccess": False,
                "excludeTmpdirEnvVar": False,
                "excludeSlashTmp": False,
            }
        return None

    @staticmethod
    def _merge_request_config(
        *,
        profile: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del profile
        # profile-v2 is materialized locally to model/modelProvider instead of
        # being forwarded as legacy `config.profile`.
        return deep_merge_config_overrides(config_overrides)

    @staticmethod
    def _materialize_profile_slice(
        *,
        profile: str | None,
        model: str | None,
        model_provider: str | None,
    ) -> tuple[str | None, str | None]:
        effective_model = str(model or "").strip() or None
        effective_model_provider = str(model_provider or "").strip() or None
        normalized_profile = str(profile or "").strip()
        if not normalized_profile or (effective_model and effective_model_provider):
            return effective_model, effective_model_provider
        resolved = resolve_profile_from_codex_config(normalized_profile)
        if not effective_model:
            resolved_model = str(resolved.model or "").strip()
            effective_model = resolved_model or None
        if not effective_model_provider:
            resolved_provider = str(resolved.model_provider or "").strip()
            effective_model_provider = resolved_provider or None
        return effective_model, effective_model_provider

    def _collaboration_mode_payload(
        self,
        mode: str,
        *,
        model: str | None,
        thread_id: str = "",
        reasoning_effort: str | None,
    ) -> dict[str, Any]:
        normalized = str(mode).strip().lower()
        if normalized not in {"default", "plan"}:
            raise ValueError("collaboration_mode 仅支持 default 或 plan")
        return {
            "mode": normalized,
            "settings": {
                "model": self._resolve_collaboration_mode_model(model, thread_id=thread_id),
                "reasoning_effort": reasoning_effort,
                "developer_instructions": None,
            },
        }

    def _resolve_collaboration_mode_model(self, configured_model: str | None, *, thread_id: str = "") -> str:
        if configured_model:
            return configured_model
        # 优先使用线程创建/恢复时后端解析的 model（来自 profile），
        # 避免用 model/list 全局默认值覆盖 profile 指定的 model。
        thread_model = self._thread_resolved_model.get(thread_id) if thread_id else None
        if thread_model:
            return thread_model
        if self._collaboration_mode_model:
            return self._collaboration_mode_model

        result = self._rpc.request("model/list", {})
        models = result.get("data") or []
        for item in models:
            if item.get("isDefault") and item.get("model"):
                self._collaboration_mode_model = str(item["model"])
                return self._collaboration_mode_model
        for item in models:
            if not item.get("hidden") and item.get("model"):
                self._collaboration_mode_model = str(item["model"])
                return self._collaboration_mode_model
        raise RuntimeError("无法解析 Codex 默认模型，无法构造 collaboration mode 参数")

    def _clear_model_caches(self) -> None:
        self._collaboration_mode_model = None
        self._thread_resolved_model.clear()

    def _cache_thread_model(self, result: dict[str, Any]) -> None:
        thread = result.get("thread") or {}
        thread_id = str(thread.get("id", "")).strip()
        model = str(result.get("model", "")).strip()
        if thread_id and model:
            self._thread_resolved_model[thread_id] = model

    @staticmethod
    def _snapshot_from_thread(thread: dict[str, Any]) -> ThreadSnapshot:
        return ThreadSnapshot(
            summary=CodexAppServerAdapter._summary_from_thread(thread),
            turns=thread.get("turns") or [],
        )

    @staticmethod
    def _runtime_config_from_result(result: dict[str, Any]) -> RuntimeConfigSummary:
        config = result.get("config") or {}
        memories_raw = config.get("memories") or {}
        layers_raw = result.get("layers") or []
        profiles: list[RuntimeProfileSummary] = []
        for name in list_profile_v2_names():
            if not profile_v2_is_usable(name):
                logger.debug("skip unusable profile-v2 candidate %s", name)
                continue
            resolved = resolve_profile_from_codex_config(name)
            profiles.append(
                RuntimeProfileSummary(
                    name=name,
                    model_provider=str(resolved.model_provider or "").strip() or None,
                )
            )
        return RuntimeConfigSummary(
            current_profile=_read_current_profile_from_layers(layers_raw)
            or _read_string(config, "profile", "activeProfile", "active_profile"),
            current_model_provider=_read_string(config, "modelProvider", "model_provider"),
            current_memory_mode=thread_memory_mode_from_memories_config(
                memories_raw if isinstance(memories_raw, dict) else None
            ),
            profiles=profiles,
        )

    @staticmethod
    def _model_summaries_from_result(result: dict[str, Any]) -> list[RuntimeModelSummary]:
        data = result.get("data") or []
        models: list[RuntimeModelSummary] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            model = _read_string(item, "model")
            if not model:
                continue
            models.append(
                RuntimeModelSummary(
                    model=model,
                    display_name=_read_string(item, "displayName", "display_name") or None,
                    is_default=bool(item.get("isDefault")),
                    hidden=bool(item.get("hidden")),
                )
                )
        return models

    @staticmethod
    def _goal_from_result(goal: dict[str, Any]) -> ThreadGoalSummary:
        return ThreadGoalSummary(
            thread_id=str(goal.get("threadId", "") or "").strip(),
            objective=str(goal.get("objective", "") or "").strip(),
            status=str(goal.get("status", "") or "").strip(),
            token_budget=int(goal["tokenBudget"]) if goal.get("tokenBudget") is not None else None,
            tokens_used=int(goal.get("tokensUsed") or 0),
            time_used_seconds=int(goal.get("timeUsedSeconds") or 0),
            created_at=int(goal.get("createdAt") or 0),
            updated_at=int(goal.get("updatedAt") or 0),
        )

    @staticmethod
    def _summary_from_thread(thread: dict[str, Any]) -> ThreadSummary:
        status = thread.get("status") or {}
        return ThreadSummary(
            thread_id=thread.get("id", ""),
            cwd=thread.get("cwd", ""),
            name=thread.get("name") or "",
            preview=thread.get("preview") or "",
            created_at=int(thread.get("createdAt") or 0),
            updated_at=int(thread.get("updatedAt") or 0),
            source=thread.get("source") or "unknown",
            status=status.get("type", "unknown"),
            active_flags=list(status.get("activeFlags") or []),
            path=thread.get("path"),
            model_provider=thread.get("modelProvider"),
            service_name=thread.get("serviceName"),
        )


def _compact(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def _read_string(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _read_current_profile_from_layers(layers_raw: Any) -> str | None:
    if not isinstance(layers_raw, list):
        return None
    for layer in layers_raw:
        if not isinstance(layer, dict):
            continue
        name = layer.get("name")
        if not isinstance(name, dict):
            continue
        if str(name.get("type", "") or "").strip() != "user":
            continue
        profile = name.get("profile")
        if profile not in (None, ""):
            return str(profile)
    return None
