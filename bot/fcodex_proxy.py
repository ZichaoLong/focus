"""
fcodex 本地 websocket proxy。

Upstream Codex TUI 在 `--remote` 模式下不会给 `thread/start` 带 `cwd`，
shared app-server 会回退到服务进程自己的工作目录。这里补一个很薄的
本地代理，在需要时给 `thread/start` 补回调用方 cwd。

另外，upstream `codex --remote ... resume <id>` 启动时会先连一次 remote
app-server 做 session lookup，再断开后重连进入正式 TUI；因此这里不能在
首条 websocket 连接结束后立即自关，而要保留一段 idle 窗口给下一次连接。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect
from websockets.sync.server import serve

from bot.codex_config_reader import resolve_profile_model_metadata
from bot.instance_layout import global_data_dir as default_global_data_dir
from bot.process_utils import process_exists
from bot.stores.instance_registry_store import InstanceRegistryStore
from bot.stores.interaction_lease_store import (
    InteractionLeaseStore,
    make_fcodex_interaction_holder,
)
from bot.runtime_state import BACKEND_THREAD_STATUS_IDLE, BACKEND_THREAD_STATUS_NOT_LOADED
from bot.stores.thread_memory_mode_store import ThreadMemoryModeStore
from bot.stores.thread_resume_profile_store import ThreadResumeProfileStore
from bot.thread_pending_settings import PendingThreadwiseSeed
from bot.stores.thread_runtime_lease_store import ThreadRuntimeLeaseHolder, ThreadRuntimeLeaseStore
from bot.thread_memory_mode import (
    build_thread_memory_config_override,
    deep_merge_config_overrides,
    normalize_thread_memory_mode,
)
from bot.thread_resume_profile_setting import (
    build_thread_resume_profile_setting,
    format_thread_resume_profile_missing_fields,
    thread_resume_profile_setting_from_record,
    thread_resume_profile_setting_missing_fields,
)
from bot.thread_runtime_coordination import (
    acquire_thread_runtime_holder_or_raise,
    preview_thread_global_loaded_gate,
)

_CWD_PROXY_METHODS = {"thread/start"}
_DEFAULT_IDLE_TIMEOUT_SECONDS = 30.0
_INTERACTIVE_SERVER_REQUEST_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "item/tool/requestUserInput",
    "mcpServer/elicitation/request",
}
_OWNER_WRITE_METHODS = {
    "turn/start",
    "turn/interrupt",
}
_NON_ACTIVE_THREAD_STATUS_TYPES = {
    BACKEND_THREAD_STATUS_IDLE,
    "errored",
    "closed",
    "archived",
    BACKEND_THREAD_STATUS_NOT_LOADED,
}


def _rewrite_thread_start_cwd(message: str | bytes, cwd: str) -> str | bytes:
    raw: str
    if isinstance(message, bytes):
        try:
            raw = message.decode("utf-8")
        except UnicodeDecodeError:
            return message
    else:
        raw = message

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return message
    if not isinstance(payload, dict):
        return message
    if payload.get("method") not in _CWD_PROXY_METHODS:
        return message
    params = payload.get("params")
    if not isinstance(params, dict):
        return message
    if params.get("cwd") not in (None, ""):
        return message

    updated_payload = dict(payload)
    updated_params = dict(params)
    updated_params["cwd"] = cwd
    updated_payload["params"] = updated_params
    encoded = json.dumps(updated_payload, ensure_ascii=False, separators=(",", ":"))
    if isinstance(message, bytes):
        return encoded.encode("utf-8")
    return encoded


def _parse_jsonrpc_message(message: str | bytes) -> tuple[dict[str, Any], bool] | None:
    raw: str
    is_bytes = isinstance(message, bytes)
    if is_bytes:
        try:
            raw = message.decode("utf-8")
        except UnicodeDecodeError:
            return None
    else:
        raw = message

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload, is_bytes


def _encode_jsonrpc_payload(payload: dict[str, Any], *, as_bytes: bool) -> str | bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if as_bytes:
        return encoded.encode("utf-8")
    return encoded


def _payload_thread_id(payload: dict[str, Any]) -> str:
    params = payload.get("params")
    if not isinstance(params, dict):
        return ""
    return str(params.get("threadId", "") or "").strip()


def _effective_global_data_dir(path: str | pathlib.Path | None) -> pathlib.Path:
    normalized = pathlib.Path(path).expanduser() if path else None
    if normalized is not None and str(normalized).strip():
        return normalized
    return default_global_data_dir()


def _response_thread_id(payload: dict[str, Any]) -> str:
    result = payload.get("result")
    if not isinstance(result, dict):
        return ""
    thread = result.get("thread")
    if isinstance(thread, dict):
        return str(thread.get("id", "") or "").strip()
    return str(result.get("threadId", "") or "").strip()


def _jsonrpc_id_key(value: Any) -> str:
    return str(value)


def _send_local_error_response(client_ws: Any, request_id: Any, message: str) -> None:
    if request_id in (None, ""):
        raise ValueError("local JSON-RPC error response requires a request id")
    client_ws.send(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32002,
                    "message": message,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _thread_status_type(payload: dict[str, Any]) -> str:
    params = payload.get("params")
    if not isinstance(params, dict):
        return ""
    status = params.get("status")
    if not isinstance(status, dict):
        return ""
    return str(status.get("type", "") or "").strip()


def _thread_became_non_active(payload: dict[str, Any]) -> bool:
    return _thread_status_type(payload) in _NON_ACTIVE_THREAD_STATUS_TYPES


def _thread_became_not_loaded(payload: dict[str, Any]) -> bool:
    return _thread_status_type(payload) == BACKEND_THREAD_STATUS_NOT_LOADED


def _assert_thread_global_loaded_gate(
    *,
    thread_id: str,
    current_instance_name: str,
    registry_store: InstanceRegistryStore,
) -> None:
    preview = preview_thread_global_loaded_gate(
        thread_id=thread_id,
        current_instance_name=current_instance_name,
        registry_store=registry_store,
    )
    if preview.allowed:
        return
    raise RuntimeError(preview.reason_text)


class _ProxyRuntimeLeaseKeeper:
    def __init__(
        self,
        *,
        global_data_dir: pathlib.Path | None = None,
        instance_name: str = "",
        service_token: str = "",
        holder_pid: int,
    ) -> None:
        normalized_global_data_dir = _effective_global_data_dir(global_data_dir)
        self._runtime_lease_store = ThreadRuntimeLeaseStore(normalized_global_data_dir)
        self._instance_registry = InstanceRegistryStore(normalized_global_data_dir)
        self._instance_name = str(instance_name or "").strip().lower()
        self._service_token = str(service_token or "").strip()
        self._holder_id = f"fcodex:{holder_pid}"
        self._holder_pid = holder_pid
        self._lock = threading.Lock()
        self._owned_thread_ids: set[str] = set()

    def _runtime_holder(self) -> ThreadRuntimeLeaseHolder | None:
        if not self._instance_name or not self._service_token:
            return None
        return ThreadRuntimeLeaseHolder(
            holder_id=self._holder_id,
            holder_type="fcodex",
            instance_name=self._instance_name,
            owner_pid=self._holder_pid,
            owner_service_token=self._service_token,
            control_endpoint="",
            backend_url="",
            updated_at=time.time(),
        )

    def acquire(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        holder = self._runtime_holder()
        if holder is None:
            return
        _assert_thread_global_loaded_gate(
            thread_id=normalized_thread_id,
            current_instance_name=self._instance_name,
            registry_store=self._instance_registry,
        )
        acquire_thread_runtime_holder_or_raise(
            thread_id=normalized_thread_id,
            holder=holder,
            lease_store=self._runtime_lease_store,
            registry_store=self._instance_registry,
        )
        with self._lock:
            self._owned_thread_ids.add(normalized_thread_id)

    def release(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        with self._lock:
            self._owned_thread_ids.discard(normalized_thread_id)
        if not self._service_token:
            return
        self._runtime_lease_store.release(normalized_thread_id, self._holder_id)

    def close(self) -> None:
        if not self._service_token:
            return
        with self._lock:
            owned_thread_ids = tuple(sorted(self._owned_thread_ids))
            self._owned_thread_ids.clear()
        for thread_id in owned_thread_ids:
            self._runtime_lease_store.release(thread_id, self._holder_id)


class _ProxyThreadSeedState:
    def __init__(
        self,
        *,
        thread_profile_seed: str = "",
        thread_profile_model_seed: str = "",
        thread_profile_model_provider_seed: str = "",
        thread_memory_mode_seed: str = "",
    ) -> None:
        self._initial_thread_profile_seed = build_thread_resume_profile_setting(
            thread_profile_seed,
            model=thread_profile_model_seed,
            model_provider=thread_profile_model_provider_seed,
        )
        self._initial_thread_profile_seed_consumed = not self._initial_thread_profile_seed.profile
        self._initial_thread_memory_mode_seed = str(thread_memory_mode_seed or "").strip()
        self._initial_thread_memory_mode_seed_consumed = not self._initial_thread_memory_mode_seed
        self._pending_initial_thread_seed_reservation: tuple[str, str] | None = None
        self._initial_thread_seed_outcome_unknown = False
        self._pending_threadwise_seed_by_thread_id: dict[str, PendingThreadwiseSeed] = {}
        self._lock = threading.Lock()

    def pending_threadwise_seed(self, thread_id: str) -> PendingThreadwiseSeed | None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return None
        with self._lock:
            return self._pending_threadwise_seed_by_thread_id.get(normalized_thread_id)

    def clear_pending_threadwise_seed(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        with self._lock:
            self._pending_threadwise_seed_by_thread_id.pop(normalized_thread_id, None)

    def initial_thread_profile_seed(self):
        with self._lock:
            if self._initial_thread_profile_seed_consumed or not self._initial_thread_profile_seed.profile:
                return None
            return self._initial_thread_profile_seed

    def initial_thread_memory_mode_seed(self) -> str:
        with self._lock:
            if self._initial_thread_memory_mode_seed_consumed or not self._initial_thread_memory_mode_seed:
                return ""
            return self._initial_thread_memory_mode_seed

    def _initial_thread_seed_available_unlocked(self) -> bool:
        return (
            (
                not self._initial_thread_profile_seed_consumed
                and bool(self._initial_thread_profile_seed.profile)
            )
            or (
                not self._initial_thread_memory_mode_seed_consumed
                and bool(self._initial_thread_memory_mode_seed)
            )
        )

    def reserve_initial_thread_seed_for_request(self, *, owner_key: str, request_id: Any) -> str:
        request_key = _jsonrpc_id_key(request_id)
        if not owner_key or not request_key:
            return "invalid"
        with self._lock:
            if not self._initial_thread_seed_available_unlocked():
                return "exhausted"
            if self._initial_thread_seed_outcome_unknown:
                return "outcome_unknown"
            reservation = self._pending_initial_thread_seed_reservation
            if reservation is None:
                self._pending_initial_thread_seed_reservation = (owner_key, request_key)
                return "reserved"
            if reservation == (owner_key, request_key):
                return "owned"
            return "reserved_by_other"

    def release_initial_thread_seed_reservation(self, *, owner_key: str, request_key: str) -> None:
        if not owner_key or not request_key:
            return
        with self._lock:
            if self._pending_initial_thread_seed_reservation == (owner_key, request_key):
                self._pending_initial_thread_seed_reservation = None

    def release_initial_thread_seed_reservations_for_owner(self, owner_key: str) -> None:
        if not owner_key:
            return
        with self._lock:
            reservation = self._pending_initial_thread_seed_reservation
            if reservation is not None and reservation[0] == owner_key:
                self._pending_initial_thread_seed_reservation = None

    def mark_initial_thread_seed_outcome_unknown_for_owner(self, owner_key: str) -> None:
        if not owner_key:
            return
        with self._lock:
            reservation = self._pending_initial_thread_seed_reservation
            if reservation is None or reservation[0] != owner_key:
                return
            self._pending_initial_thread_seed_reservation = None
            if self._initial_thread_seed_available_unlocked():
                self._initial_thread_seed_outcome_unknown = True

    def bind_initial_thread_seed_once(
        self,
        thread_id: str,
        *,
        owner_key: str,
        request_key: str,
    ) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            self.release_initial_thread_seed_reservation(owner_key=owner_key, request_key=request_key)
            return
        with self._lock:
            if self._pending_initial_thread_seed_reservation != (owner_key, request_key):
                return
            profile_setting = (
                self._initial_thread_profile_seed
                if not self._initial_thread_profile_seed_consumed and self._initial_thread_profile_seed.profile
                else None
            )
            memory_mode = (
                self._initial_thread_memory_mode_seed
                if not self._initial_thread_memory_mode_seed_consumed and self._initial_thread_memory_mode_seed
                else ""
            )
            self._pending_initial_thread_seed_reservation = None
            if profile_setting is None and not memory_mode:
                return
            self._initial_thread_profile_seed_consumed = True
            self._initial_thread_memory_mode_seed_consumed = True
            self._initial_thread_seed_outcome_unknown = False
            normalized_memory_mode = str(memory_mode or "").strip()
            if normalized_memory_mode:
                normalized_memory_mode = normalize_thread_memory_mode(normalized_memory_mode)
            seed = PendingThreadwiseSeed(
                thread_id=normalized_thread_id,
                profile=profile_setting.profile if profile_setting is not None else "",
                model=profile_setting.model if profile_setting is not None else "",
                model_provider=profile_setting.model_provider if profile_setting is not None else "",
                memory_mode=normalized_memory_mode,
            )
            if seed.has_any:
                self._pending_threadwise_seed_by_thread_id[normalized_thread_id] = seed
            else:
                self._pending_threadwise_seed_by_thread_id.pop(normalized_thread_id, None)


class _ProxyInteractionGate:
    def __init__(
        self,
        *,
        cwd: str,
        data_dir: pathlib.Path,
        global_data_dir: pathlib.Path | None = None,
        instance_name: str = "",
        service_token: str = "",
        holder_pid: int,
        thread_profile_seed: str = "",
        thread_profile_model_seed: str = "",
        thread_profile_model_provider_seed: str = "",
        thread_memory_mode_seed: str = "",
        resume_profile_hint: str = "",
        runtime_lease_keeper: _ProxyRuntimeLeaseKeeper | None = None,
        thread_seed_state: _ProxyThreadSeedState | None = None,
    ) -> None:
        self._cwd = cwd
        self._holder = make_fcodex_interaction_holder(
            f"fcodex:{holder_pid}",
            owner_pid=holder_pid,
        )
        self._instance_name = str(instance_name or "").strip().lower()
        self._service_token = str(service_token or "").strip()
        self._lease_store = InteractionLeaseStore(data_dir)
        normalized_global_data_dir = _effective_global_data_dir(global_data_dir)
        self._global_data_dir = normalized_global_data_dir
        self._runtime_lease_store = ThreadRuntimeLeaseStore(normalized_global_data_dir)
        self._instance_registry = InstanceRegistryStore(normalized_global_data_dir)
        self._thread_seed_state = thread_seed_state or _ProxyThreadSeedState(
            thread_profile_seed=thread_profile_seed,
            thread_profile_model_seed=thread_profile_model_seed,
            thread_profile_model_provider_seed=thread_profile_model_provider_seed,
            thread_memory_mode_seed=thread_memory_mode_seed,
        )
        self._thread_seed_state_owner_key = f"gate:{id(self)}"
        self._resume_profile_hint = str(resume_profile_hint or "").strip()
        self._runtime_lease_keeper = runtime_lease_keeper
        self._lock = threading.Lock()
        self._pending_server_request_thread_by_id: dict[str, str] = {}
        self._pending_client_request_by_id: dict[str, tuple[str, str, bool]] = {}
        self._pending_model_list_request_ids: set[str] = set()
        self._pending_thread_request_by_id: dict[str, tuple[str, str, bool]] = {}
        self._owned_thread_ids: set[str] = set()

    def _remember_owned_thread(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        with self._lock:
            self._owned_thread_ids.add(normalized_thread_id)

    def _forget_owned_thread(self, thread_id: str) -> None:
        normalized_thread_id = str(thread_id or "").strip()
        if not normalized_thread_id:
            return
        with self._lock:
            self._owned_thread_ids.discard(normalized_thread_id)

    def close(self) -> None:
        with self._lock:
            owned_thread_ids = set(self._owned_thread_ids)
            owned_thread_ids.update(
                thread_id
                for thread_id in self._pending_server_request_thread_by_id.values()
                if thread_id
            )
            owned_thread_ids.update(
                thread_id
                for _, thread_id, _ in self._pending_client_request_by_id.values()
                if thread_id
            )
            self._owned_thread_ids.clear()
            self._pending_server_request_thread_by_id.clear()
            self._pending_client_request_by_id.clear()
            self._pending_model_list_request_ids.clear()
            pending_thread_requests = list(self._pending_thread_request_by_id.values())
            self._pending_thread_request_by_id.clear()
        reserved_thread_start_outcome_unknown = any(
            request_method == "thread/start" and reserved_initial_seed
            for request_method, _, reserved_initial_seed in pending_thread_requests
        )
        if reserved_thread_start_outcome_unknown:
            self._thread_seed_state.mark_initial_thread_seed_outcome_unknown_for_owner(
                self._thread_seed_state_owner_key
            )
        else:
            self._thread_seed_state.release_initial_thread_seed_reservations_for_owner(
                self._thread_seed_state_owner_key
            )
        for thread_id in owned_thread_ids:
            self._lease_store.release(thread_id, self._holder)
            if self._runtime_lease_keeper is None:
                self._release_runtime_lease(thread_id)

    def _runtime_holder(self) -> ThreadRuntimeLeaseHolder | None:
        if not self._instance_name or not self._service_token:
            return None
        return ThreadRuntimeLeaseHolder(
            holder_id=self._holder.holder_id,
            holder_type="fcodex",
            instance_name=self._instance_name,
            owner_pid=self._holder.owner_pid,
            owner_service_token=self._service_token,
            control_endpoint="",
            backend_url="",
            updated_at=time.time(),
        )

    def _acquire_runtime_lease(self, thread_id: str) -> None:
        if self._runtime_lease_keeper is not None:
            self._runtime_lease_keeper.acquire(thread_id)
            return
        holder = self._runtime_holder()
        if holder is None:
            return
        _assert_thread_global_loaded_gate(
            thread_id=thread_id,
            current_instance_name=self._instance_name,
            registry_store=self._instance_registry,
        )
        acquire_thread_runtime_holder_or_raise(
            thread_id=thread_id,
            holder=holder,
            lease_store=self._runtime_lease_store,
            registry_store=self._instance_registry,
        )
        self._remember_owned_thread(thread_id)

    def _release_runtime_lease(self, thread_id: str) -> None:
        if self._runtime_lease_keeper is not None:
            self._runtime_lease_keeper.release(thread_id)
            self._forget_owned_thread(thread_id)
            return
        if not self._service_token:
            return
        self._runtime_lease_store.release(thread_id, self._holder.holder_id)
        self._forget_owned_thread(thread_id)

    def _pending_threadwise_seed(self, thread_id: str) -> PendingThreadwiseSeed | None:
        return self._thread_seed_state.pending_threadwise_seed(thread_id)

    def _clear_pending_threadwise_seed(self, thread_id: str) -> None:
        self._thread_seed_state.clear_pending_threadwise_seed(thread_id)

    def _thread_profile_setting(self, thread_id: str):
        pending = self._pending_threadwise_seed(thread_id)
        if pending is not None and pending.has_profile_slice:
            return build_thread_resume_profile_setting(
                pending.profile,
                model=pending.model,
                model_provider=pending.model_provider,
            )
        profile_record = ThreadResumeProfileStore(self._global_data_dir).load(thread_id)
        return thread_resume_profile_setting_from_record(profile_record)

    def _launch_profile_name_hint(self) -> str:
        initial = self._thread_seed_state.initial_thread_profile_seed()
        if initial is not None and str(initial.profile or "").strip():
            return str(initial.profile or "").strip()
        return self._resume_profile_hint

    def _reserve_initial_thread_seed_for_request(self, request_id: Any) -> str:
        return self._thread_seed_state.reserve_initial_thread_seed_for_request(
            owner_key=self._thread_seed_state_owner_key,
            request_id=request_id,
        )

    def _release_initial_thread_seed_reservation(self, request_key: str) -> None:
        self._thread_seed_state.release_initial_thread_seed_reservation(
            owner_key=self._thread_seed_state_owner_key,
            request_key=request_key,
        )

    def _bind_initial_thread_seed_once(self, thread_id: str, *, request_key: str) -> None:
        self._thread_seed_state.bind_initial_thread_seed_once(
            thread_id,
            owner_key=self._thread_seed_state_owner_key,
            request_key=request_key,
        )

    def _promote_pending_threadwise_seed(self, thread_id: str) -> None:
        pending = self._pending_threadwise_seed(thread_id)
        if pending is None:
            return
        try:
            if pending.has_profile_slice:
                ThreadResumeProfileStore(self._global_data_dir).save(
                    pending.thread_id,
                    profile=pending.profile,
                    model=pending.model,
                    model_provider=pending.model_provider,
                )
            if pending.has_memory_mode:
                ThreadMemoryModeStore(self._global_data_dir).save(
                    pending.thread_id,
                    mode=pending.memory_mode,
                )
        except Exception as exc:
            print(
                f"warning: failed to promote pending thread seed for `{pending.thread_id}`: {exc}",
                file=sys.stderr,
            )
            return
        self._clear_pending_threadwise_seed(pending.thread_id)

    def _apply_initial_thread_profile_seed(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = payload.get("params")
        if not isinstance(params, dict):
            return payload
        setting = self._thread_seed_state.initial_thread_profile_seed()
        if setting is None:
            return payload
        existing_config = params.get("config")
        normalized_existing_config = existing_config if isinstance(existing_config, dict) else {}
        merged_config = deep_merge_config_overrides(
            normalized_existing_config,
            {"profile": setting.profile},
        )
        updated_payload = dict(payload)
        updated_params = dict(params)
        updated_params["config"] = merged_config
        if setting.model:
            updated_params["model"] = setting.model
        if setting.model_provider:
            updated_params["modelProvider"] = setting.model_provider
        updated_payload["params"] = updated_params
        return updated_payload

    def _initial_thread_memory_profile_hint(self, params: dict[str, Any]) -> str:
        existing_config = params.get("config")
        if isinstance(existing_config, dict):
            profile_name = str(existing_config.get("profile", "") or "").strip()
            if profile_name:
                return profile_name
        setting = self._thread_seed_state.initial_thread_profile_seed()
        return str(setting.profile or "").strip() if setting is not None else ""

    def _apply_initial_thread_memory_mode_seed(self, payload: dict[str, Any]) -> dict[str, Any]:
        params = payload.get("params")
        if not isinstance(params, dict):
            return payload
        memory_mode = self._thread_seed_state.initial_thread_memory_mode_seed()
        if not memory_mode:
            return payload
        existing_config = params.get("config")
        normalized_existing_config = existing_config if isinstance(existing_config, dict) else {}
        merged_config = deep_merge_config_overrides(
            normalized_existing_config,
            build_thread_memory_config_override(
                memory_mode,
                profile_name_hint=self._initial_thread_memory_profile_hint(params),
            ),
        )
        updated_payload = dict(payload)
        updated_params = dict(params)
        updated_params["config"] = merged_config
        updated_payload["params"] = updated_params
        return updated_payload

    def _apply_saved_thread_profile_for_resume(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Wrapper launch args are only hints. The persisted thread-wise
        # next-load profile slice is enforced here at the actual
        # `thread/resume` RPC boundary so unloaded resume reuses the stored
        # tuple instead of whatever the local CLI currently resolved.
        thread_id = _payload_thread_id(payload)
        if not thread_id:
            return payload
        pending = self._pending_threadwise_seed(thread_id)
        if pending is not None and pending.has_profile_slice:
            profile_setting = build_thread_resume_profile_setting(
                pending.profile,
                model=pending.model,
                model_provider=pending.model_provider,
            )
        else:
            profile_record = ThreadResumeProfileStore(self._global_data_dir).load(thread_id)
            profile_setting = thread_resume_profile_setting_from_record(profile_record)
        if profile_setting is None or not str(profile_setting.profile or "").strip():
            return payload
        missing_fields = thread_resume_profile_setting_missing_fields(profile_setting)
        if missing_fields:
            missing_text = format_thread_resume_profile_missing_fields(missing_fields)
            raise RuntimeError(
                "当前 thread 已持久化的 thread-wise profile slice 不完整："
                f"thread=`{thread_id}`，profile=`{profile_setting.profile}`，缺少：{missing_text}。"
                "当前按 fail-close 拒绝继续。"
                "请改用飞书 `/profile <name>` 或本地 "
                "`fcodex resume <thread> -p <profile>` 重新写入完整设置。"
            )
        params = payload.get("params")
        if not isinstance(params, dict):
            return payload
        existing_config = params.get("config")
        normalized_existing_config = existing_config if isinstance(existing_config, dict) else {}
        merged_config = deep_merge_config_overrides(
            normalized_existing_config,
            {"profile": profile_setting.profile},
        )
        updated_payload = dict(payload)
        updated_params = dict(params)
        model = profile_setting.model
        model_provider = profile_setting.model_provider
        if model:
            updated_params["model"] = model
        else:
            updated_params.pop("model", None)
        if model_provider:
            updated_params["modelProvider"] = model_provider
        else:
            updated_params.pop("modelProvider", None)
        updated_params["config"] = merged_config
        updated_payload["params"] = updated_params
        return updated_payload

    def _apply_saved_thread_memory_mode_for_resume(self, payload: dict[str, Any]) -> dict[str, Any]:
        thread_id = _payload_thread_id(payload)
        if not thread_id:
            return payload
        pending = self._pending_threadwise_seed(thread_id)
        memory_mode = ""
        if pending is not None and pending.has_memory_mode:
            memory_mode = pending.memory_mode
        else:
            memory_record = ThreadMemoryModeStore(self._global_data_dir).load(thread_id)
            if memory_record is not None:
                memory_mode = memory_record.mode
        if not memory_mode:
            return payload
        params = payload.get("params")
        if not isinstance(params, dict):
            return payload
        existing_config = params.get("config")
        normalized_existing_config = existing_config if isinstance(existing_config, dict) else {}
        profile_name_hint = str(normalized_existing_config.get("profile", "") or "").strip()
        if not profile_name_hint:
            if pending is not None and pending.has_profile_slice:
                profile_name_hint = pending.profile
            else:
                profile_record = ThreadResumeProfileStore(self._global_data_dir).load(thread_id)
                if profile_record is not None:
                    profile_name_hint = str(profile_record.profile or "").strip()
        if not profile_name_hint:
            profile_name_hint = self._resume_profile_hint
        merged_config = deep_merge_config_overrides(
            normalized_existing_config,
            build_thread_memory_config_override(
                memory_mode,
                profile_name_hint=profile_name_hint,
            ),
        )
        updated_payload = dict(payload)
        updated_params = dict(params)
        updated_params["config"] = merged_config
        updated_payload["params"] = updated_params
        return updated_payload

    def _apply_saved_thread_profile_for_turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        thread_id = _payload_thread_id(payload)
        if not thread_id:
            return payload
        profile_setting = self._thread_profile_setting(thread_id)
        if profile_setting is None or not str(profile_setting.profile or "").strip():
            return payload
        missing_fields = thread_resume_profile_setting_missing_fields(profile_setting)
        if missing_fields:
            missing_text = format_thread_resume_profile_missing_fields(missing_fields)
            raise RuntimeError(
                "当前 thread 已持久化的 thread-wise profile slice 不完整："
                f"thread=`{thread_id}`，profile=`{profile_setting.profile}`，缺少：{missing_text}。"
                "当前按 fail-close 拒绝继续。"
                "请改用飞书 `/profile <name>` 或本地 "
                "`fcodex resume <thread> -p <profile>` 重新写入完整设置。"
            )
        params = payload.get("params")
        if not isinstance(params, dict):
            return payload
        existing_config = params.get("config")
        normalized_existing_config = existing_config if isinstance(existing_config, dict) else {}
        updated_payload = dict(payload)
        updated_params = dict(params)
        if not str(normalized_existing_config.get("profile", "") or "").strip():
            updated_params["config"] = deep_merge_config_overrides(
                normalized_existing_config,
                {"profile": profile_setting.profile},
            )
        explicit_model = str(updated_params.get("model", "") or "").strip()
        explicit_provider = str(updated_params.get("modelProvider", "") or "").strip()
        effective_model = explicit_model
        if not explicit_model and profile_setting.model:
            updated_params["model"] = profile_setting.model
            effective_model = profile_setting.model
        if not explicit_model and not explicit_provider and profile_setting.model_provider:
            updated_params["modelProvider"] = profile_setting.model_provider
        collaboration = updated_params.get("collaborationMode")
        normalized_collaboration = collaboration if isinstance(collaboration, dict) else {}
        settings = normalized_collaboration.get("settings")
        normalized_settings = settings if isinstance(settings, dict) else {}
        if effective_model:
            updated_settings = dict(normalized_settings)
            updated_settings["model"] = effective_model
            updated_collaboration = dict(normalized_collaboration)
            updated_collaboration["settings"] = updated_settings
            updated_params["collaborationMode"] = updated_collaboration
        updated_payload["params"] = updated_params
        return updated_payload

    def _rewrite_model_list_response_for_launch_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile_name = self._launch_profile_name_hint()
        if not profile_name:
            return payload
        metadata = resolve_profile_model_metadata(profile_name)
        if not isinstance(metadata, dict):
            return payload
        model_name = str(metadata.get("model", "") or metadata.get("slug", "") or "").strip()
        if not model_name:
            return payload
        result = payload.get("result")
        if not isinstance(result, dict):
            return payload
        data = result.get("data")
        if not isinstance(data, list):
            return payload

        normalized_metadata = dict(metadata)
        normalized_metadata["model"] = model_name
        display_name = str(
            normalized_metadata.get("displayName", "") or normalized_metadata.get("display_name", "") or ""
        ).strip()
        if display_name:
            normalized_metadata["displayName"] = display_name
            normalized_metadata["display_name"] = display_name
        normalized_metadata["isDefault"] = True
        normalized_metadata.setdefault("hidden", False)

        updated_data: list[Any] = []
        found = False
        for item in data:
            if not isinstance(item, dict):
                updated_data.append(item)
                continue
            item_model = str(item.get("model", "") or item.get("slug", "") or "").strip()
            updated_item = dict(item)
            if updated_item.get("isDefault") and item_model != model_name:
                updated_item["isDefault"] = False
            if item_model == model_name and not found:
                updated_item.update(normalized_metadata)
                found = True
            updated_data.append(updated_item)
        if not found:
            updated_data.insert(0, normalized_metadata)

        updated_payload = dict(payload)
        updated_result = dict(result)
        updated_result["data"] = updated_data
        updated_payload["result"] = updated_result
        return updated_payload

    def handle_client_message(self, message: str | bytes, *, client_ws: Any, backend_ws: Any) -> None:
        rewritten = _rewrite_thread_start_cwd(message, self._cwd)
        parsed = _parse_jsonrpc_message(rewritten)
        if parsed is None:
            backend_ws.send(rewritten)
            return
        payload, is_bytes = parsed

        method = payload.get("method")
        if isinstance(method, str):
            request_id = payload.get("id")
            request_key = _jsonrpc_id_key(request_id)
            reserved_initial_seed = False
            if method == "thread/resume":
                payload = self._apply_saved_thread_profile_for_resume(payload)
                payload = self._apply_saved_thread_memory_mode_for_resume(payload)
            elif method == "thread/start":
                reservation_state = self._reserve_initial_thread_seed_for_request(request_id)
                if reservation_state == "reserved_by_other":
                    _send_local_error_response(
                        client_ws,
                        request_id,
                        "当前 fcodex 启动级 seed 正在等待另一条新建 thread 请求返回；"
                        "请等待上一条 `thread/start` 完成或失败后再试。",
                    )
                    return
                if reservation_state == "outcome_unknown":
                    _send_local_error_response(
                        client_ws,
                        request_id,
                        "当前 fcodex 启动级 seed 的上一条新建 thread 请求在连接关闭时结果未知；"
                        "当前按 fail-close 拒绝继续，请退出并重新启动 fcodex 后再试。",
                    )
                    return
                reserved_initial_seed = reservation_state in {"reserved", "owned"}
                if reserved_initial_seed:
                    payload = self._apply_initial_thread_profile_seed(payload)
                    payload = self._apply_initial_thread_memory_mode_seed(payload)
            elif method == "turn/start":
                payload = self._apply_saved_thread_profile_for_turn(payload)
            thread_id = _payload_thread_id(payload)
            if method == "thread/resume" and thread_id:
                try:
                    self._acquire_runtime_lease(thread_id)
                except Exception as exc:
                    _send_local_error_response(client_ws, request_id, str(exc))
                    return
                with self._lock:
                    self._pending_thread_request_by_id[_jsonrpc_id_key(request_id)] = (method, thread_id, False)
            elif method == "thread/start":
                with self._lock:
                    self._pending_thread_request_by_id[request_key] = (method, "", reserved_initial_seed)
            elif method == "thread/unsubscribe" and thread_id:
                with self._lock:
                    self._pending_thread_request_by_id[request_key] = (method, thread_id, False)
            elif method == "model/list":
                with self._lock:
                    self._pending_model_list_request_ids.add(request_key)
            if method in _OWNER_WRITE_METHODS and thread_id:
                if method == "turn/start":
                    lease = self._lease_store.acquire(thread_id, self._holder)
                    if not lease.granted:
                        _send_local_error_response(
                            client_ws,
                            request_id,
                            "当前线程正由其他终端执行；请等待当前 turn 结束后再试。",
                        )
                        return
                    self._remember_owned_thread(thread_id)
                    with self._lock:
                        self._pending_client_request_by_id[_jsonrpc_id_key(request_id)] = (
                            method,
                            thread_id,
                            lease.acquired,
                        )
                elif method == "turn/interrupt":
                    lease = self._lease_store.load(thread_id)
                    if lease is None or not lease.holder.same_holder(self._holder):
                        _send_local_error_response(
                            client_ws,
                            request_id,
                            "当前终端不是该线程的交互 owner，不能取消这次执行。",
                        )
                        return
                    self._remember_owned_thread(thread_id)
            backend_ws.send(_encode_jsonrpc_payload(payload, as_bytes=is_bytes))
            return

        response_id = payload.get("id")
        if response_id not in (None, ""):
            request_key = _jsonrpc_id_key(response_id)
            with self._lock:
                thread_id = self._pending_server_request_thread_by_id.pop(request_key, "")
            if thread_id:
                lease = self._lease_store.load(thread_id)
                if lease is not None and not lease.holder.same_holder(self._holder):
                    return
        backend_ws.send(_encode_jsonrpc_payload(payload, as_bytes=is_bytes))

    def handle_backend_message(self, message: str | bytes, *, client_ws: Any, backend_ws: Any) -> None:
        del backend_ws
        parsed = _parse_jsonrpc_message(message)
        if parsed is None:
            client_ws.send(message)
            return
        payload, is_bytes = parsed

        method = payload.get("method")
        if isinstance(method, str) and "id" in payload:
            thread_id = _payload_thread_id(payload)
            if method in _INTERACTIVE_SERVER_REQUEST_METHODS and thread_id:
                lease = self._lease_store.load(thread_id)
                if lease is not None and not lease.holder.same_holder(self._holder):
                    return
                self._remember_owned_thread(thread_id)
                with self._lock:
                    self._pending_server_request_thread_by_id[_jsonrpc_id_key(payload["id"])] = thread_id
            client_ws.send(_encode_jsonrpc_payload(payload, as_bytes=is_bytes))
            return

        if isinstance(method, str):
            params = payload.get("params")
            if method == "serverRequest/resolved" and isinstance(params, dict):
                request_id = params.get("requestId")
                with self._lock:
                    self._pending_server_request_thread_by_id.pop(_jsonrpc_id_key(request_id), None)
            thread_id = _payload_thread_id(payload)
            if thread_id:
                if method == "turn/completed":
                    turn = params if isinstance(params, dict) else {}
                    completed = turn.get("turn") if isinstance(turn.get("turn"), dict) else {}
                    turn_error = completed.get("error") if isinstance(completed, dict) else {}
                    turn_status = str(completed.get("status", "") or "").strip()
                    if turn_status == "completed" and not turn_error:
                        self._promote_pending_threadwise_seed(thread_id)
                    self._lease_store.release(thread_id, self._holder)
                    self._forget_owned_thread(thread_id)
                elif method == "thread/closed":
                    self._clear_pending_threadwise_seed(thread_id)
                    self._lease_store.release(thread_id, self._holder)
                    self._release_runtime_lease(thread_id)
                    self._forget_owned_thread(thread_id)
                elif method == "thread/status/changed":
                    if _thread_became_non_active(payload):
                        self._lease_store.release(thread_id, self._holder)
                        self._forget_owned_thread(thread_id)
                    if _thread_became_not_loaded(payload):
                        self._release_runtime_lease(thread_id)
            client_ws.send(_encode_jsonrpc_payload(payload, as_bytes=is_bytes))
            return

        response_id = payload.get("id")
        if response_id not in (None, ""):
            request_key = _jsonrpc_id_key(response_id)
            with self._lock:
                thread_request = self._pending_thread_request_by_id.pop(request_key, None)
                rewrite_model_list = request_key in self._pending_model_list_request_ids
                if rewrite_model_list:
                    self._pending_model_list_request_ids.discard(request_key)
            if thread_request is not None:
                request_method, thread_id, reserved_initial_seed = thread_request
                if request_method == "thread/resume" and "error" in payload:
                    self._release_runtime_lease(thread_id)
                elif request_method == "thread/start":
                    if "error" in payload:
                        if reserved_initial_seed:
                            self._release_initial_thread_seed_reservation(request_key)
                    else:
                        started_thread_id = _response_thread_id(payload)
                        if started_thread_id:
                            try:
                                self._acquire_runtime_lease(started_thread_id)
                            except Exception:
                                if reserved_initial_seed:
                                    self._release_initial_thread_seed_reservation(request_key)
                                raise
                            if reserved_initial_seed:
                                self._bind_initial_thread_seed_once(
                                    started_thread_id,
                                    request_key=request_key,
                                )
                        elif reserved_initial_seed:
                            self._release_initial_thread_seed_reservation(request_key)
                elif request_method == "thread/unsubscribe" and "error" not in payload:
                    self._release_runtime_lease(thread_id)
            with self._lock:
                request_context = self._pending_client_request_by_id.pop(_jsonrpc_id_key(response_id), None)
            if request_context is not None:
                request_method, thread_id, acquired = request_context
                if request_method == "turn/start" and acquired and "error" in payload:
                    self._lease_store.release(thread_id, self._holder)
                    self._forget_owned_thread(thread_id)
            if rewrite_model_list and "result" in payload:
                payload = self._rewrite_model_list_response_for_launch_profile(payload)
        client_ws.send(_encode_jsonrpc_payload(payload, as_bytes=is_bytes))


def _close_quietly(ws: Any) -> None:
    try:
        ws.close()
    except Exception:
        pass


def _relay_messages(
    source_ws: Any,
    target_ws: Any,
    *,
    transform: Callable[[str | bytes], str | bytes] | None = None,
) -> None:
    try:
        for message in source_ws:
            payload = transform(message) if transform is not None else message
            try:
                target_ws.send(payload)
            except ConnectionClosed:
                break
    except ConnectionClosed:
        pass


def run_proxy(
    *,
    backend_url: str,
    cwd: str,
    data_dir: str | pathlib.Path | None = None,
    global_data_dir: str | pathlib.Path | None = None,
    instance_name: str = "",
    service_token: str = "",
    thread_profile_seed: str = "",
    thread_profile_model_seed: str = "",
    thread_profile_model_provider_seed: str = "",
    thread_memory_mode_seed: str = "",
    resume_profile_hint: str = "",
    listen_host: str = "127.0.0.1",
    listen_port: int = 0,
    idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT_SECONDS,
    parent_pid: int | None = None,
    on_listen: Callable[[str], None] | None = None,
) -> None:
    server_ref: dict[str, Any] = {}
    shutdown_once = threading.Event()
    state_lock = threading.Lock()
    active_connections = 0
    idle_deadline = 0.0
    runtime_lease_keeper = _ProxyRuntimeLeaseKeeper(
        global_data_dir=global_data_dir,
        instance_name=instance_name or os.environ.get("FC_INSTANCE", ""),
        service_token=service_token,
        holder_pid=parent_pid or os.getpid(),
    )
    thread_seed_state = _ProxyThreadSeedState(
        thread_profile_seed=thread_profile_seed,
        thread_profile_model_seed=thread_profile_model_seed,
        thread_profile_model_provider_seed=thread_profile_model_provider_seed,
        thread_memory_mode_seed=thread_memory_mode_seed,
    )

    def _shutdown_server() -> None:
        if shutdown_once.is_set():
            return
        shutdown_once.set()
        server = server_ref.get("server")
        if server is not None:
            threading.Thread(target=server.shutdown, daemon=True).start()

    def _arm_idle_shutdown() -> None:
        nonlocal idle_deadline
        with state_lock:
            idle_deadline = time.monotonic() + max(0.0, idle_timeout_seconds)

    def _cancel_idle_shutdown() -> None:
        nonlocal idle_deadline
        with state_lock:
            idle_deadline = 0.0

    def _wait_until_idle_deadline() -> None:
        while not shutdown_once.is_set():
            with state_lock:
                current_connections = active_connections
                deadline = idle_deadline
            if current_connections > 0 or deadline <= 0.0:
                time.sleep(0.05)
                continue
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(remaining, 0.05))
                continue
            with state_lock:
                if active_connections == 0 and idle_deadline == deadline:
                    _shutdown_server()
                    return

    def _wait_until_parent_exit() -> None:
        if parent_pid is None:
            return
        while not shutdown_once.is_set():
            if not process_exists(parent_pid):
                _shutdown_server()
                return
            time.sleep(0.25)

    def _handler(client_ws: Any) -> None:
        nonlocal active_connections
        with state_lock:
            active_connections += 1
        _cancel_idle_shutdown()
        try:
            with connect(backend_url, max_size=None, proxy=None) as backend_ws:
                holder_pid = parent_pid or os.getpid()
                gate = _ProxyInteractionGate(
                    cwd=cwd,
                    data_dir=pathlib.Path(data_dir or os.environ.get("FC_DATA_DIR") or "."),
                    global_data_dir=global_data_dir,
                    instance_name=instance_name or os.environ.get("FC_INSTANCE", ""),
                    service_token=service_token,
                    holder_pid=holder_pid,
                    thread_profile_seed=thread_profile_seed,
                    thread_profile_model_seed=thread_profile_model_seed,
                    thread_profile_model_provider_seed=thread_profile_model_provider_seed,
                    thread_memory_mode_seed=thread_memory_mode_seed,
                    resume_profile_hint=resume_profile_hint,
                    runtime_lease_keeper=runtime_lease_keeper,
                    thread_seed_state=thread_seed_state,
                )

                def _backend_to_client() -> None:
                    try:
                        try:
                            for backend_message in backend_ws:
                                gate.handle_backend_message(
                                    backend_message,
                                    client_ws=client_ws,
                                    backend_ws=backend_ws,
                                )
                        except ConnectionClosed:
                            pass
                    finally:
                        _close_quietly(client_ws)
                        _close_quietly(backend_ws)

                thread = threading.Thread(target=_backend_to_client, daemon=True)
                thread.start()
                try:
                    for client_message in client_ws:
                        gate.handle_client_message(
                            client_message,
                            client_ws=client_ws,
                            backend_ws=backend_ws,
                        )
                finally:
                    _close_quietly(backend_ws)
                    _close_quietly(client_ws)
                    thread.join(timeout=1)
                    gate.close()
        finally:
            with state_lock:
                active_connections = max(0, active_connections - 1)
                should_arm_idle = active_connections == 0
            if should_arm_idle:
                _arm_idle_shutdown()

    try:
        with serve(_handler, listen_host, listen_port, max_size=None) as server:
            server_ref["server"] = server
            actual_port = server.socket.getsockname()[1]
            listen_url = f"ws://{listen_host}:{actual_port}"
            if on_listen is not None:
                on_listen(listen_url)
            else:
                print(listen_url, flush=True)
            _arm_idle_shutdown()
            threading.Thread(target=_wait_until_idle_deadline, daemon=True).start()
            if parent_pid is not None:
                threading.Thread(target=_wait_until_parent_exit, daemon=True).start()
            server.serve_forever()
    finally:
        runtime_lease_keeper.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="fcodex local cwd proxy")
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--data-dir", default="")
    parser.add_argument("--global-data-dir", default="")
    parser.add_argument("--instance", default="")
    parser.add_argument("--service-token", default="")
    parser.add_argument("--thread-profile-seed", default="")
    parser.add_argument("--thread-profile-model-seed", default="")
    parser.add_argument("--thread-profile-model-provider-seed", default="")
    parser.add_argument("--thread-memory-mode-seed", default="")
    parser.add_argument("--resume-profile-hint", default="")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=0)
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args(argv)
    run_proxy(
        backend_url=args.backend_url,
        cwd=args.cwd,
        data_dir=args.data_dir or None,
        global_data_dir=args.global_data_dir or None,
        instance_name=args.instance,
        service_token=args.service_token,
        thread_profile_seed=args.thread_profile_seed,
        thread_profile_model_seed=args.thread_profile_model_seed,
        thread_profile_model_provider_seed=args.thread_profile_model_provider_seed,
        thread_memory_mode_seed=args.thread_memory_mode_seed,
        resume_profile_hint=args.resume_profile_hint,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        parent_pid=args.parent_pid or None,
    )


if __name__ == "__main__":
    main()
