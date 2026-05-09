from __future__ import annotations

from collections.abc import Callable

THREAD_RESUME_PROFILE_LOADED_REASON = (
    "当前 thread 仍处于 loaded 状态；本次 `fcodex resume` 不能同时携带 `-p/--profile` 改写该 thread 的 profile。"
    "若只是进入当前会话，请去掉 `-p/--profile` 后重试。"
    "若要修改该 thread 的 profile，需要先让它变成 verifiably globally unloaded；"
    "通常还要关闭仍打开该 thread 的 `fcodex` TUI，并等待上游 backend 自然 unload。"
    "若不想等待，请改在飞书侧执行 `/profile <name>` 并按卡片重置 backend，"
    "或先对当前实例执行 `feishu-codexctl service reset-backend`，再重新执行本命令。"
)
THREAD_RESUME_MEMORY_MODE_LOADED_REASON = (
    "当前 thread 仍处于 loaded 状态；当前不能直接改写该 thread 的 memory mode。"
    "若只是继续使用当前会话，可保持现状。"
    "若要修改该 thread 的 memory mode，需要先让它变成 verifiably globally unloaded；"
    "通常还要关闭仍打开该 thread 的 `fcodex` TUI，并等待上游 backend 自然 unload。"
    "若不想等待，请改在飞书侧执行 `/memory <off|read|read_write>` 并按卡片重置 backend，"
    "或先对当前实例执行 `feishu-codexctl service reset-backend`，再让该 thread 从 unloaded 状态重新恢复。"
)
THREAD_RESUME_MUTABILITY_ADAPTER_UNAVAILABLE_REASON = (
    "当前无法确认该 thread 是否已完全 unloaded；请稍后重试。"
)


def _check_thread_resume_mutable(
    thread_id: str,
    *,
    loaded_reason: str,
    unbound_reason: str,
    has_attached_binding: Callable[[str], bool] | None = None,
    has_runtime_lease: Callable[[str], bool] | None = None,
    list_loaded_thread_ids: Callable[[], list[str]],
) -> tuple[bool, str]:
    normalized_thread_id = str(thread_id or "").strip()
    if not normalized_thread_id:
        return False, unbound_reason
    if has_attached_binding is not None and has_attached_binding(normalized_thread_id):
        return False, loaded_reason
    if has_runtime_lease is not None and has_runtime_lease(normalized_thread_id):
        return False, loaded_reason
    try:
        loaded_thread_ids = {
            str(item or "").strip()
            for item in list_loaded_thread_ids()
            if str(item or "").strip()
        }
    except Exception:
        return False, THREAD_RESUME_MUTABILITY_ADAPTER_UNAVAILABLE_REASON
    if normalized_thread_id in loaded_thread_ids:
        return False, loaded_reason
    return True, ""


def check_thread_resume_profile_mutable(
    thread_id: str,
    *,
    unbound_reason: str,
    has_attached_binding: Callable[[str], bool] | None = None,
    has_runtime_lease: Callable[[str], bool] | None = None,
    list_loaded_thread_ids: Callable[[], list[str]],
) -> tuple[bool, str]:
    return _check_thread_resume_mutable(
        thread_id,
        loaded_reason=THREAD_RESUME_PROFILE_LOADED_REASON,
        unbound_reason=unbound_reason,
        has_attached_binding=has_attached_binding,
        has_runtime_lease=has_runtime_lease,
        list_loaded_thread_ids=list_loaded_thread_ids,
    )


def check_thread_resume_memory_mode_mutable(
    thread_id: str,
    *,
    unbound_reason: str,
    has_attached_binding: Callable[[str], bool] | None = None,
    has_runtime_lease: Callable[[str], bool] | None = None,
    list_loaded_thread_ids: Callable[[], list[str]],
) -> tuple[bool, str]:
    return _check_thread_resume_mutable(
        thread_id,
        loaded_reason=THREAD_RESUME_MEMORY_MODE_LOADED_REASON,
        unbound_reason=unbound_reason,
        has_attached_binding=has_attached_binding,
        has_runtime_lease=has_runtime_lease,
        list_loaded_thread_ids=list_loaded_thread_ids,
    )
