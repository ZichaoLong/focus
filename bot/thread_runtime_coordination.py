"""
Cross-instance live thread runtime coordination helpers.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from bot.reason_codes import PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER
from bot.runtime_state import (
    BACKEND_THREAD_STATUS_NOT_LOADED,
    BACKEND_THREAD_STATUS_UNKNOWN,
    LOADED_BACKEND_THREAD_STATUSES,
)
from bot.service_control_plane import control_request
from bot.stores.instance_registry_store import InstanceRegistryEntry, InstanceRegistryStore
from bot.stores.thread_runtime_lease_store import (
    ThreadRuntimeLease,
    ThreadRuntimeLeaseAcquireResult,
    ThreadRuntimeLeaseHolder,
    ThreadRuntimeLeaseStore,
)


@dataclass(frozen=True, slots=True)
class ThreadRuntimeAcquirePreview:
    allowed: bool
    reason_code: str = ""
    reason_text: str = ""


@dataclass(frozen=True, slots=True)
class ThreadGlobalLoadedGatePreview:
    allowed: bool
    reason_code: str = ""
    reason_text: str = ""
    blocking_instance: str = ""
    blocking_status: str = ""


def preview_thread_global_loaded_gate(
    *,
    thread_id: str,
    current_instance_name: str,
    registry_store: InstanceRegistryStore | None = None,
    running_instances: list[InstanceRegistryEntry] | tuple[InstanceRegistryEntry, ...] | None = None,
    timeout_seconds: float = 3.0,
) -> ThreadGlobalLoadedGatePreview:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return ThreadGlobalLoadedGatePreview(allowed=True)
    normalized_current_instance = str(current_instance_name or "").strip().lower()
    if running_instances is None:
        effective_registry_store = registry_store or InstanceRegistryStore()
        entries = effective_registry_store.list_instances()
    else:
        entries = list(running_instances)
    for entry in entries:
        if normalized_current_instance and entry.instance_name == normalized_current_instance:
            continue
        try:
            backend_thread_status = _remote_backend_thread_status(
                entry,
                normalized_thread_id,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            return ThreadGlobalLoadedGatePreview(
                allowed=False,
                reason_code=PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
                reason_text=(
                    f"无法确认运行中的实例 `{entry.instance_name}` 是否仍将该 thread 保持为 loaded：{exc}。"
                    "当前按 fail-close 拒绝跨实例继续。"
                    f"请先检查该实例状态；若确认可打断，可执行 "
                    f"`focusctl --instance {entry.instance_name} service reset-backend` 后再试。"
                ),
                blocking_instance=entry.instance_name,
            )
        if backend_thread_status in LOADED_BACKEND_THREAD_STATUSES:
            return ThreadGlobalLoadedGatePreview(
                allowed=False,
                reason_code=PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
                reason_text=(
                    f"当前 thread 仍由运行中的实例 `{entry.instance_name}` 保持为 loaded "
                    f"(`{backend_thread_status}`)；当前按 fail-close 拒绝跨实例继续。"
                    "请先在该实例侧继续，或在确认要丢弃其 live runtime 后执行 "
                    f"`focusctl --instance {entry.instance_name} service reset-backend`。"
                ),
                blocking_instance=entry.instance_name,
                blocking_status=backend_thread_status,
            )
        if backend_thread_status != BACKEND_THREAD_STATUS_NOT_LOADED:
            reported_status = backend_thread_status or BACKEND_THREAD_STATUS_UNKNOWN
            return ThreadGlobalLoadedGatePreview(
                allowed=False,
                reason_code=PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
                reason_text=(
                    f"运行中的实例 `{entry.instance_name}` 对该 thread 返回了不可验证的状态："
                    f"`{reported_status}`。当前按 fail-close 拒绝跨实例继续。"
                ),
                blocking_instance=entry.instance_name,
                blocking_status=reported_status,
            )
    return ThreadGlobalLoadedGatePreview(allowed=True)


def build_runtime_lease_conflict_message(
    lease: ThreadRuntimeLease | None,
    *,
    reason: str = "",
) -> str:
    if lease is None:
        return "当前无法获取 thread live runtime。"
    base = f"当前线程正由实例 `{lease.owner_instance}` 持有 live runtime。"
    if reason:
        return f"{base} {reason}"
    return base


def acquire_thread_runtime_holder_or_raise(
    *,
    thread_id: str,
    holder: ThreadRuntimeLeaseHolder,
    lease_store: ThreadRuntimeLeaseStore,
) -> ThreadRuntimeLeaseAcquireResult:
    result = lease_store.acquire(thread_id, holder)
    if result.granted:
        return result

    current = result.lease
    if current is None:
        raise RuntimeError("当前无法获取 thread live runtime。")

    preview = preview_thread_runtime_holder_acquire_conflict(
        holder=holder,
        current=current,
    )
    if not preview.allowed:
        raise RuntimeError(preview.reason_text)
    raise RuntimeError(build_runtime_lease_conflict_message(current))


def preview_thread_runtime_holder_acquire(
    *,
    thread_id: str,
    holder: ThreadRuntimeLeaseHolder,
    lease_store: ThreadRuntimeLeaseStore,
) -> ThreadRuntimeAcquirePreview:
    current = lease_store.load(thread_id)
    if current is None or (
        current.owner_instance == holder.instance_name
        and current.owner_service_token == holder.owner_service_token
    ):
        return ThreadRuntimeAcquirePreview(allowed=True)
    return preview_thread_runtime_holder_acquire_conflict(
        holder=holder,
        current=current,
    )


def preview_thread_runtime_holder_acquire_conflict(
    *,
    holder: ThreadRuntimeLeaseHolder,
    current: ThreadRuntimeLease,
) -> ThreadRuntimeAcquirePreview:
    if (
        current.owner_instance == holder.instance_name
        and current.owner_service_token != holder.owner_service_token
    ):
        return ThreadRuntimeAcquirePreview(
            allowed=False,
            reason_code=PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
            reason_text=_stale_same_instance_owner_message(current),
        )

    if _has_non_service_holders(current):
        return ThreadRuntimeAcquirePreview(
            allowed=False,
            reason_code=PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
            reason_text=_external_holder_conflict_message(current),
        )

    return ThreadRuntimeAcquirePreview(
        allowed=False,
        reason_code=PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
        reason_text=_service_owner_conflict_message(current),
    )


def _stale_same_instance_owner_message(lease: ThreadRuntimeLease) -> str:
    return (
        f"当前线程仍记录为实例 `{lease.owner_instance}` 的上一代 service 持有 live runtime；"
        "当前按 fail-close 拒绝继续。"
        "请先执行 "
        f"`focusctl --instance {lease.owner_instance} service reset-backend` "
        "清理旧 live runtime 后再试。"
    )


def _service_owner_conflict_message(lease: ThreadRuntimeLease) -> str:
    return build_runtime_lease_conflict_message(
        lease,
        reason=(
            "当前不支持跨实例继续。请先在该实例侧继续，"
            f"或在确认要丢弃其 live runtime 后执行 "
            f"`focusctl --instance {lease.owner_instance} service reset-backend`。"
        ),
    )


def _has_non_service_holders(lease: ThreadRuntimeLease) -> bool:
    return any(holder.holder_type != "service" for holder in lease.holders)


def _external_holder_conflict_message(lease: ThreadRuntimeLease) -> str:
    has_fcodex_holder = any(holder.holder_type == "fcodex" for holder in lease.holders)
    if has_fcodex_holder:
        return (
            f"当前线程正由实例 `{lease.owner_instance}` 的本地 `fcodex` 持有 live runtime；"
            "当前不支持跨实例继续。请先关闭对应 `fcodex` TUI，或回到该实例继续。"
        )
    return build_runtime_lease_conflict_message(
        lease,
        reason=(
            "当前不支持跨实例继续。请先回到 owner 实例释放该 live runtime，"
            f"或在确认可丢弃后执行 "
            f"`focusctl --instance {lease.owner_instance} service reset-backend`。"
        ),
    )


def _remote_backend_thread_status(
    owner: InstanceRegistryEntry,
    thread_id: str,
    *,
    timeout_seconds: float = 3.0,
) -> str:
    payload = control_request(
        pathlib.Path(owner.data_dir),
        "thread/status",
        {"thread_id": thread_id},
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("控制面返回了无效 thread 状态。")
    return str(payload.get("backend_thread_status", "") or "").strip() or BACKEND_THREAD_STATUS_UNKNOWN
