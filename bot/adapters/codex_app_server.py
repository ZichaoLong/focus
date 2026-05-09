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
    PluginCatalog,
    PluginDetailSummary,
    PluginLoadError,
    PluginMarketplaceSummary,
    PluginSummary,
    RuntimeConfigSummary,
    RuntimeProfileSummary,
    SkillLoadError,
    SkillSummary,
    SkillsSnapshot,
    ThreadSnapshot,
    ThreadSummary,
    TurnInputItem,
)
from bot.codex_protocol.client import CodexRpcClient
from bot.constants import DEFAULT_APP_SERVER_MODE, DEFAULT_APP_SERVER_URL, DEFAULT_SOURCE_KINDS
from bot.stores.app_server_runtime_store import AppServerRuntimeStore
from bot.thread_memory_mode import deep_merge_config_overrides

logger = logging.getLogger(__name__)

_SUPPORTED_SANDBOX_MODES = {
    "read-only",
    "workspace-write",
    "danger-full-access",
}


@dataclass(slots=True)
class CodexAppServerConfig:
    codex_command: str = "codex"
    app_server_mode: str = DEFAULT_APP_SERVER_MODE
    app_server_url: str = DEFAULT_APP_SERVER_URL
    connect_timeout_seconds: float = 15.0
    request_timeout_seconds: float = 30.0
    service_name: str = "feishu-codex"
    sandbox: str = "danger-full-access"
    approval_policy: str = "never"
    approvals_reviewer: str = "user"
    personality: str = "pragmatic"
    model: str = ""
    model_provider: str = ""
    service_tier: str = ""
    reasoning_effort: str = ""
    collaboration_mode: str = "default"
    source_kinds: list[str] = field(default_factory=lambda: DEFAULT_SOURCE_KINDS.copy())

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "CodexAppServerConfig":
        source_kinds = config.get("source_kinds") or DEFAULT_SOURCE_KINDS
        collaboration_mode = str(config.get("collaboration_mode", "default")).strip().lower() or "default"
        app_server_mode = str(config.get("app_server_mode", DEFAULT_APP_SERVER_MODE)).strip().lower() or DEFAULT_APP_SERVER_MODE
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
            sandbox=str(config.get("sandbox", "danger-full-access")),
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
        # Workaround: collaborationMode.settings.model 会覆盖线程级 profile
        # 解析出的 model（上游 turn/start 协议没有 config 字段，无法传递
        # profile；而 collaborationMode.settings.model 是必填字段）。
        # 缓存 thread/start 和 thread/resume 响应里后端解析好的 model，
        # 作为 collaborationMode.settings.model 的 fallback，避免用
        # model/list 的全局默认值覆盖 profile 指定的 model。
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
        )

    def start(self) -> None:
        self._rpc.start()

    def stop(self) -> None:
        self._rpc.stop()

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
        approval_policy: str | None = None,
        sandbox: str | None = None,
    ) -> ThreadSnapshot:
        params = self._thread_params(
            cwd=cwd,
            include_service_name=True,
            profile=profile,
            config_overrides=config_overrides,
            approval_policy=approval_policy,
            sandbox=sandbox,
        )
        result = self._rpc.request("thread/start", params)
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
    ) -> ThreadSnapshot:
        params: dict[str, Any] = {"threadId": thread_id}
        if model:
            params["model"] = model
        if model_provider:
            params["modelProvider"] = model_provider
        merged_config = self._merge_request_config(profile=profile, config_overrides=config_overrides)
        if merged_config:
            params["config"] = merged_config
        result = self._rpc.request("thread/resume", params)
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

    def read_runtime_config(self, *, cwd: str | None = None) -> RuntimeConfigSummary:
        result = self._rpc.request("config/read", _compact({"includeLayers": False, "cwd": cwd}))
        return self._runtime_config_from_result(result)

    def list_loaded_thread_ids(self) -> list[str]:
        result = self._rpc.request("thread/loaded/list", {})
        data = result.get("data") or []
        return [str(item).strip() for item in data if str(item).strip()]

    def set_active_profile(self, profile: str) -> RuntimeConfigSummary:
        self._rpc.request(
            "config/batchWrite",
            {
                "edits": [
                    {
                        "keyPath": "profile",
                        "value": profile,
                        "mergeStrategy": "replace",
                    }
                ],
                "reloadUserConfig": True,
            },
        )
        return self.read_runtime_config()

    def set_thread_memory_mode(self, thread_id: str, *, mode: str) -> None:
        self._rpc.request(
            "thread/memoryMode/set",
            {
                "threadId": thread_id,
                "mode": mode,
            },
        )

    def compact_thread(self, thread_id: str) -> None:
        self._rpc.request(
            "thread/compact/start",
            {
                "threadId": thread_id,
            },
        )

    def list_skills(self, *, cwd: str, force_reload: bool = False) -> SkillsSnapshot:
        result = self._rpc.request(
            "skills/list",
            _compact(
                {
                    "cwds": [cwd] if cwd else None,
                    "forceReload": True if force_reload else None,
                }
            ),
        )
        return self._skills_snapshot_from_result(cwd=cwd, result=result)

    def set_skill_enabled(self, *, skill_path: str = "", skill_name: str = "", enabled: bool) -> None:
        normalized_path = str(skill_path or "").strip()
        normalized_name = str(skill_name or "").strip()
        if bool(normalized_path) == bool(normalized_name):
            raise ValueError("set_skill_enabled 必须且只能指定 skill_path 或 skill_name。")
        self._rpc.request(
            "skills/config/write",
            _compact(
                {
                    "path": normalized_path or None,
                    "name": normalized_name or None,
                    "enabled": bool(enabled),
                }
            ),
        )

    def list_plugins(self, *, cwd: str | None = None) -> PluginCatalog:
        result = self._rpc.request(
            "plugin/list",
            _compact(
                {
                    "cwds": [cwd] if cwd else None,
                }
            ),
        )
        return self._plugin_catalog_from_result(result)

    def read_plugin(
        self,
        plugin_name: str,
        *,
        marketplace_name: str = "",
        marketplace_path: str | None = None,
    ) -> PluginDetailSummary:
        normalized_plugin_name = str(plugin_name or "").strip()
        normalized_marketplace_name = str(marketplace_name or "").strip()
        normalized_marketplace_path = str(marketplace_path or "").strip() or None
        if not normalized_plugin_name:
            raise ValueError("plugin_name 不能为空。")
        if bool(normalized_marketplace_name) == bool(normalized_marketplace_path):
            raise ValueError("read_plugin 必须且只能指定 marketplace_name 或 marketplace_path。")
        result = self._rpc.request(
            "plugin/read",
            _compact(
                {
                    "pluginName": normalized_plugin_name,
                    "remoteMarketplaceName": normalized_marketplace_name or None,
                    "marketplacePath": normalized_marketplace_path,
                }
            ),
        )
        return self._plugin_detail_from_result(result)

    def set_plugin_enabled(self, plugin_id: str, *, enabled: bool) -> None:
        normalized_plugin_id = str(plugin_id or "").strip()
        if not normalized_plugin_id:
            raise ValueError("plugin_id 不能为空。")
        self._rpc.request(
            "config/value/write",
            {
                "keyPath": f"plugins.{normalized_plugin_id}",
                "value": {"enabled": bool(enabled)},
                "mergeStrategy": "upsert",
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
            "modelProvider": model_provider or None,
            "approvalPolicy": approval_policy or self._config.approval_policy or None,
            "approvalsReviewer": self._config.approvals_reviewer or None,
            "sandboxPolicy": self._sandbox_policy_payload(sandbox or self._config.sandbox),
            "effort": effective_reasoning,
            "personality": self._config.personality or None,
            "serviceTier": self._config.service_tier or None,
        }
        if profile:
            params["config"] = {"profile": profile}
        params["collaborationMode"] = self._collaboration_mode_payload(
            effective_collaboration_mode,
            model=effective_model,
            thread_id=thread_id,
            reasoning_effort=effective_reasoning,
        )
        return self._rpc.request("turn/start", _compact(params))

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
        approval_policy: str | None = None,
        sandbox: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "cwd": cwd,
            "sandbox": self._normalize_sandbox_mode(sandbox or self._config.sandbox),
            "approvalPolicy": approval_policy or self._config.approval_policy or None,
            "approvalsReviewer": self._config.approvals_reviewer or None,
            "personality": self._config.personality or None,
            "model": self._config.model or None,
            "modelProvider": self._config.model_provider or None,
            "serviceTier": self._config.service_tier or None,
        }
        merged_config = self._merge_request_config(profile=profile, config_overrides=config_overrides)
        if merged_config:
            params["config"] = merged_config
        if include_service_name:
            params["serviceName"] = self._config.service_name or None
        return _compact(params)

    @staticmethod
    def _merge_request_config(
        *,
        profile: str | None = None,
        config_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_profile = str(profile or "").strip()
        profile_override = {"profile": normalized_profile} if normalized_profile else None
        return deep_merge_config_overrides(profile_override, config_overrides)

    @staticmethod
    def _normalize_sandbox_mode(mode: str | None) -> str | None:
        if mode is None:
            return None
        value = str(mode).strip().lower()
        if not value:
            return None
        if value not in _SUPPORTED_SANDBOX_MODES:
            raise ValueError("sandbox 仅支持 read-only、workspace-write、danger-full-access")
        return value

    @classmethod
    def _sandbox_policy_payload(cls, mode: str | None) -> dict[str, Any] | None:
        normalized = cls._normalize_sandbox_mode(mode)
        if normalized is None:
            return None
        if normalized == "danger-full-access":
            return {"type": "dangerFullAccess"}
        if normalized == "read-only":
            return {
                "type": "readOnly",
                "access": {"type": "fullAccess"},
                "networkAccess": False,
            }
        return {
            "type": "workspaceWrite",
            "writableRoots": [],
            "readOnlyAccess": {"type": "fullAccess"},
            "networkAccess": False,
            "excludeTmpdirEnvVar": False,
            "excludeSlashTmp": False,
        }

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
        profiles_raw = config.get("profiles") or {}
        profiles: list[RuntimeProfileSummary] = []
        if isinstance(profiles_raw, dict):
            for name in sorted(profiles_raw):
                if not str(name).strip():
                    continue
                item = profiles_raw.get(name)
                item_dict = item if isinstance(item, dict) else {}
                profiles.append(
                    RuntimeProfileSummary(
                        name=str(name),
                        model_provider=_read_string(item_dict, "modelProvider", "model_provider"),
                    )
                )
        return RuntimeConfigSummary(
            current_profile=_read_string(config, "profile", "activeProfile", "active_profile"),
            current_model_provider=_read_string(config, "modelProvider", "model_provider"),
            profiles=profiles,
        )

    @staticmethod
    def _skills_snapshot_from_result(*, cwd: str, result: dict[str, Any]) -> SkillsSnapshot:
        data = result.get("data") or []
        matched = None
        normalized_cwd = str(cwd or "").strip()
        for item in data:
            entry_cwd = str((item or {}).get("cwd", "") or "").strip()
            if entry_cwd == normalized_cwd:
                matched = item or {}
                break
        if matched is None and len(data) == 1:
            matched = data[0] or {}
        matched = matched or {}
        skills = [
            SkillSummary(
                name=str(item.get("name", "") or ""),
                description=str(item.get("description", "") or ""),
                short_description=_read_string(item, "shortDescription", "short_description"),
                path=str(item.get("path", "") or ""),
                scope=str(item.get("scope", "") or ""),
                enabled=bool(item.get("enabled")),
            )
            for item in (matched.get("skills") or [])
            if str((item or {}).get("name", "") or "").strip()
        ]
        errors = [
            SkillLoadError(
                path=str(item.get("path", "") or ""),
                message=str(item.get("message", "") or ""),
            )
            for item in (matched.get("errors") or [])
            if str((item or {}).get("message", "") or "").strip()
        ]
        return SkillsSnapshot(
            cwd=str(matched.get("cwd", "") or normalized_cwd),
            skills=skills,
            errors=errors,
        )

    @classmethod
    def _plugin_catalog_from_result(cls, result: dict[str, Any]) -> PluginCatalog:
        marketplaces = [
            PluginMarketplaceSummary(
                name=str(item.get("name", "") or ""),
                path=_read_string(item, "path"),
                plugins=[
                    cls._plugin_summary_from_marketplace_item(
                        plugin,
                        marketplace_name=str(item.get("name", "") or ""),
                        marketplace_path=_read_string(item, "path"),
                    )
                    for plugin in (item.get("plugins") or [])
                    if str((plugin or {}).get("id", "") or "").strip()
                ],
            )
            for item in (result.get("marketplaces") or [])
            if str((item or {}).get("name", "") or "").strip()
        ]
        marketplace_load_errors = [
            PluginLoadError(
                marketplace_path=str(item.get("marketplacePath", "") or ""),
                message=str(item.get("message", "") or ""),
            )
            for item in (result.get("marketplaceLoadErrors") or [])
            if str((item or {}).get("message", "") or "").strip()
        ]
        featured_plugin_ids = [
            str(item).strip()
            for item in (result.get("featuredPluginIds") or [])
            if str(item).strip()
        ]
        return PluginCatalog(
            marketplaces=marketplaces,
            marketplace_load_errors=marketplace_load_errors,
            featured_plugin_ids=featured_plugin_ids,
        )

    @classmethod
    def _plugin_detail_from_result(cls, result: dict[str, Any]) -> PluginDetailSummary:
        plugin = result.get("plugin") or {}
        marketplace_name = str(plugin.get("marketplaceName", "") or "")
        marketplace_path = _read_string(plugin, "marketplacePath")
        summary = cls._plugin_summary_from_marketplace_item(
            plugin.get("summary") or {},
            marketplace_name=marketplace_name,
            marketplace_path=marketplace_path,
        )
        return PluginDetailSummary(
            plugin=summary,
            description=str(plugin.get("description", "") or ""),
            skill_names=[
                str(item.get("name", "") or "").strip()
                for item in (plugin.get("skills") or [])
                if str((item or {}).get("name", "") or "").strip()
            ],
            hook_keys=[
                str(item.get("key", "") or "").strip()
                for item in (plugin.get("hooks") or [])
                if str((item or {}).get("key", "") or "").strip()
            ],
            app_names=[
                str(item.get("name", "") or "").strip()
                for item in (plugin.get("apps") or [])
                if str((item or {}).get("name", "") or "").strip()
            ],
            mcp_servers=[
                str(item).strip()
                for item in (plugin.get("mcpServers") or [])
                if str(item).strip()
            ],
        )

    @staticmethod
    def _plugin_summary_from_marketplace_item(
        item: dict[str, Any],
        *,
        marketplace_name: str,
        marketplace_path: str | None,
    ) -> PluginSummary:
        source = item.get("source") or {}
        source_type = str((source or {}).get("type", "") or "")
        return PluginSummary(
            plugin_id=str(item.get("id", "") or ""),
            name=str(item.get("name", "") or ""),
            marketplace_name=marketplace_name,
            marketplace_path=marketplace_path,
            installed=bool(item.get("installed")),
            enabled=bool(item.get("enabled")),
            source_type=source_type or "unknown",
            availability=str(item.get("availability", "") or ""),
            install_policy=str(item.get("installPolicy", "") or ""),
            auth_policy=str(item.get("authPolicy", "") or ""),
            keywords=[
                str(keyword).strip()
                for keyword in (item.get("keywords") or [])
                if str(keyword).strip()
            ],
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
