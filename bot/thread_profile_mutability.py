from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

THREAD_RESUME_MUTABILITY_REASON_UNBOUND = "thread_resume_mutability_unbound"
THREAD_RESUME_MUTABILITY_REASON_LOADED = "thread_resume_mutability_loaded"
THREAD_RESUME_MUTABILITY_REASON_RUNTIME_UNVERIFIED = "thread_resume_mutability_runtime_unverified"


@dataclass(frozen=True, slots=True)
class ThreadResumeMutabilityCheck:
    allowed: bool
    reason_code: str = ""
    reason_text: str = ""
    thread_id: str = ""
    has_attached_binding: bool = False
    has_runtime_lease: bool = False
    listed_as_loaded: bool = False


def _local_reset_backend_command(instance_name: str) -> str:
    normalized = str(instance_name or "").strip()
    if normalized:
        return f"`feishu-codexctl --instance {normalized} service reset-backend`"
    return "`feishu-codexctl service reset-backend`"


def _instance_backend_label(instance_name: str, *, fallback: str) -> str:
    normalized = str(instance_name or "").strip()
    if normalized:
        return f"实例 `{normalized}` 的 backend"
    return fallback


def _format_loaded_reasons(check: ThreadResumeMutabilityCheck) -> str:
    facts: list[str] = []
    if check.has_attached_binding:
        facts.append("仍有 attached 的飞书会话")
    if check.has_runtime_lease:
        facts.append("仍有 live runtime lease")
    if check.listed_as_loaded:
        facts.append("backend 仍把它列为 loaded")
    return "、".join(facts)


def format_thread_resume_memory_mode_denial_for_local_cli(
    check: ThreadResumeMutabilityCheck,
    *,
    instance_name: str = "",
) -> str:
    if check.allowed:
        return ""
    if check.reason_code == THREAD_RESUME_MUTABILITY_REASON_UNBOUND:
        return check.reason_text
    if check.reason_code == THREAD_RESUME_MUTABILITY_REASON_RUNTIME_UNVERIFIED:
        backend_label = _instance_backend_label(instance_name, fallback="目标实例的 backend")
        reset_command = _local_reset_backend_command(instance_name)
        return (
            f"当前无法确认{backend_label}是否仍把该 thread 保持为 loaded；"
            "当前按 fail-close 拒绝改写该 thread 的 memory mode。"
            f"请先检查该实例状态；若确认可打断，可执行 {reset_command} 后重试。"
        )
    backend_label = _instance_backend_label(instance_name, fallback="目标实例的 backend")
    reset_command = _local_reset_backend_command(instance_name)
    loaded_reasons = _format_loaded_reasons(check)
    suffix = f" 当前观测：{loaded_reasons}。" if loaded_reasons else ""
    return (
        f"{backend_label} 当前仍把该 thread 保持为 loaded；"
        "当前不能直接改写该 thread 的 memory mode。"
        "因为 memory mode 属于 thread 级 next-load 设置，只有该 thread 下次从 unloaded 重新恢复时才会生效。"
        "若只是继续使用当前 thread，可保持现状。"
        f"若要立即改 memory mode，请先执行 {reset_command}，"
        "或在该实例对应的飞书会话里执行 `/memory <off|read|read_write>` 并点“应用并重置 backend”。"
        f"{suffix}"
    )


def format_thread_resume_memory_mode_denial_for_feishu(
    check: ThreadResumeMutabilityCheck,
    *,
    instance_name: str = "",
) -> str:
    if check.allowed:
        return ""
    if check.reason_code == THREAD_RESUME_MUTABILITY_REASON_UNBOUND:
        return check.reason_text
    if check.reason_code == THREAD_RESUME_MUTABILITY_REASON_RUNTIME_UNVERIFIED:
        backend_label = _instance_backend_label(instance_name, fallback="当前实例 backend")
        return (
            f"当前无法确认{backend_label}是否仍把该 thread 保持为 loaded。"
            "当前按 fail-close 拒绝直接改写 memory mode；请先检查当前实例状态，必要时执行 `/reset-backend`。"
        )
    backend_label = _instance_backend_label(instance_name, fallback="当前实例 backend")
    return (
        f"{backend_label} 当前仍把该 thread 保持为 loaded，所以现在不能直接改写该 thread-wise memory mode。"
        "memory mode 属于 thread 级 next-load 设置，只有该 thread 下次从 unloaded 重新恢复时才会生效。"
        "若要立即生效，请在当前实例执行 `/reset-backend`，或继续使用当前卡片里的“应用并重置 backend”路径。"
    )


def _check_thread_resume_mutable(
    thread_id: str,
    *,
    unbound_reason: str,
    has_attached_binding: Callable[[str], bool] | None = None,
    has_runtime_lease: Callable[[str], bool] | None = None,
    list_loaded_thread_ids: Callable[[], list[str]],
) -> ThreadResumeMutabilityCheck:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return ThreadResumeMutabilityCheck(
            allowed=False,
            reason_code=THREAD_RESUME_MUTABILITY_REASON_UNBOUND,
            reason_text=unbound_reason,
        )
    attached = bool(has_attached_binding(normalized_thread_id)) if has_attached_binding is not None else False
    runtime_lease = bool(has_runtime_lease(normalized_thread_id)) if has_runtime_lease is not None else False
    try:
        loaded_thread_ids = {
            str(item or "").strip()
            for item in list_loaded_thread_ids()
            if str(item or "").strip()
        }
    except Exception:
        return ThreadResumeMutabilityCheck(
            allowed=False,
            reason_code=THREAD_RESUME_MUTABILITY_REASON_RUNTIME_UNVERIFIED,
            thread_id=normalized_thread_id,
            has_attached_binding=attached,
            has_runtime_lease=runtime_lease,
        )
    listed_as_loaded = normalized_thread_id in loaded_thread_ids
    if attached or runtime_lease or listed_as_loaded:
        return ThreadResumeMutabilityCheck(
            allowed=False,
            reason_code=THREAD_RESUME_MUTABILITY_REASON_LOADED,
            thread_id=normalized_thread_id,
            has_attached_binding=attached,
            has_runtime_lease=runtime_lease,
            listed_as_loaded=listed_as_loaded,
        )
    return ThreadResumeMutabilityCheck(allowed=True, thread_id=normalized_thread_id)


def check_thread_resume_memory_mode_mutable(
    thread_id: str,
    *,
    unbound_reason: str,
    has_attached_binding: Callable[[str], bool] | None = None,
    has_runtime_lease: Callable[[str], bool] | None = None,
    list_loaded_thread_ids: Callable[[], list[str]],
) -> ThreadResumeMutabilityCheck:
    return _check_thread_resume_mutable(
        thread_id,
        unbound_reason=unbound_reason,
        has_attached_binding=has_attached_binding,
        has_runtime_lease=has_runtime_lease,
        list_loaded_thread_ids=list_loaded_thread_ids,
    )
