"""Surface-neutral runtime administration and control-plane composition."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Callable, TypeAlias

from bot.adapters.base import ThreadGoalSummary, ThreadSummary
from bot.backend_reset.contract import (
    BACKEND_RESET_STATUS_AVAILABLE,
    BACKEND_RESET_STATUS_FORCE_ONLY,
    BackendResetPreview,
)
from bot.backend_reset.diagnostics import (
    BackendResetDiagnostics,
    BackendResetDiagnosticsPorts,
)
from bot.binding_runtime_manager import BindingRuntimeManager
from bot.direct_thread_target_policy import (
    DirectThreadTargetPolicyError,
    read_direct_thread_target,
)
from bot.reason_codes import (
    BACKEND_RESET_FORCE_ONLY_BY_ACTIVE_LOADED_THREAD,
    BACKEND_RESET_FORCE_ONLY_BY_PENDING_REQUEST,
    BACKEND_RESET_FORCE_ONLY_BY_RUNNING_BINDING,
    BACKEND_RESET_FORCE_ONLY_BY_RUNTIME_UNVERIFIED,
    ReasonedCheck,
)
from bot.runtime_state import (
    BACKEND_THREAD_STATUS_ACTIVE,
    BACKEND_THREAD_LOOKUP_ERROR,
    BACKEND_THREAD_LOOKUP_MISSING,
    BACKEND_THREAD_STATUS_UNKNOWN,
    FEISHU_RUNTIME_ATTACHED,
)
from bot.runtime_admin.binding_clear import (
    RuntimeBindingBatchDeactivationReceipt,
)
from bot.runtime_admin.binding_application import (
    RuntimeAdminAttachBinding,
    RuntimeAdminBindingApplication,
    RuntimeAdminBindingApplicationPorts,
)
from bot.runtime_admin.control_router import (
    RuntimeAdminBindingControlPorts,
    RuntimeAdminControlRouter,
    RuntimeAdminControlRouterPorts,
    RuntimeAdminServiceControlPorts,
    RuntimeAdminThreadControlPorts,
)
from bot.stores.interaction_lease_store import InteractionLeaseHolder
from bot.stores.thread_runtime_lease_store import ThreadRuntimeLease
from bot.thread_image_delivery import ThreadImageDeliveryController
from bot.thread_lifecycle_service import (
    ThreadLifecyclePolicyError,
    ThreadLifecycleService,
)

logger = logging.getLogger(__name__)

ChatBindingKey: TypeAlias = tuple[str, str]


@dataclass(frozen=True, slots=True)
class RuntimeAdminThreadPort:
    read_thread: Callable[[str], Any]
    read_thread_for_stale_cleanup: Callable[[str], Any]
    list_loaded_thread_ids: Callable[[], list[str]]
    current_app_server_url: Callable[[], str]
    unsubscribe_thread: Callable[[str], None]
    attach_binding: RuntimeAdminAttachBinding | None
    get_thread_goal: Callable[[str], ThreadGoalSummary | None]
    set_thread_goal: Callable[..., ThreadGoalSummary]
    clear_thread_goal: Callable[[str], bool]
    resolve_thread_target_for_control_params: Callable[[dict[str, Any]], ThreadSummary]


@dataclass(frozen=True, slots=True)
class RuntimeAdminCoordinationPort:
    clear_all_stored_bindings: Callable[[], None]
    deactivate_binding_and_invalidate_queue_locked: Callable[
        [ChatBindingKey], RuntimeBindingBatchDeactivationReceipt
    ]
    deactivate_bindings_and_invalidate_queues_locked: Callable[
        [tuple[ChatBindingKey, ...], list[str]],
        RuntimeBindingBatchDeactivationReceipt,
    ]
    release_service_thread_runtime_lease: Callable[[str], None]
    service_control_endpoint: Callable[[], str]
    web_gateway_enabled: Callable[[], bool]
    current_web_gateway_url: Callable[[], str]
    instance_name: Callable[[], str]
    load_thread_runtime_lease: Callable[[str], ThreadRuntimeLease | None]
    pending_interaction_request_count: Callable[[], int]
    reset_current_instance_backend: Callable[[bool], dict[str, Any]]
    submit_to_runtime: Callable[..., None]
    invalidate_feishu_execution_queue_locked: Callable[[ChatBindingKey], None]
    invalidate_all_feishu_execution_queues_locked: Callable[[], int]
    operational_status: Callable[[], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class RuntimeAdminPolicyPort:
    prompt_write_denial_check: Callable[[ChatBindingKey, str, str, str], ReasonedCheck]
    external_control_write_denial_check: Callable[..., ReasonedCheck]
    all_mode_thread_exclusivity_check: Callable[[str, str], ReasonedCheck]
    detached_runtime_attach_check: Callable[[str], ReasonedCheck]
    is_thread_not_found_error: Callable[[Exception], bool]
    is_thread_not_loaded_error: Callable[[Exception], bool]


@dataclass(frozen=True, slots=True)
class RuntimeAdminPresentationPort:
    permissions_summary: Callable[..., str]
    thread_image_delivery: ThreadImageDeliveryController
    reply_text: Callable[..., None]
    reply_card: Callable[..., None]
    submit_prompt_for_control: Callable[..., dict[str, Any]]
    resolve_binding_chat_display_name: Callable[..., str]


@dataclass(frozen=True, slots=True)
class RuntimeAdminPorts:
    thread: RuntimeAdminThreadPort
    coordination: RuntimeAdminCoordinationPort
    policy: RuntimeAdminPolicyPort
    presentation: RuntimeAdminPresentationPort | None = None


class RuntimeAdminApplication:
    def __init__(
        self,
        *,
        lock,
        binding_runtime: BindingRuntimeManager,
        interaction_requests,
        thread_lifecycle: ThreadLifecycleService,
        ports: RuntimeAdminPorts,
    ) -> None:
        thread = ports.thread
        coordination = ports.coordination
        policy = ports.policy
        presentation = ports.presentation
        self._feishu_enabled = presentation is not None
        self._lock = lock
        self._thread_lifecycle = thread_lifecycle
        self._read_thread = thread.read_thread
        self._list_loaded_thread_ids = thread.list_loaded_thread_ids
        self._current_app_server_url = thread.current_app_server_url
        self._service_control_endpoint = coordination.service_control_endpoint
        self._web_gateway_enabled = coordination.web_gateway_enabled
        self._current_web_gateway_url = coordination.current_web_gateway_url
        self._instance_name = coordination.instance_name
        self._load_thread_runtime_lease = coordination.load_thread_runtime_lease
        self._pending_interaction_request_count = (
            coordination.pending_interaction_request_count
        )
        self._reset_current_instance_backend = (
            coordination.reset_current_instance_backend
        )
        self._thread_image_delivery = (
            presentation.thread_image_delivery if presentation else None
        )
        self._get_thread_goal = thread.get_thread_goal
        self._set_thread_goal = thread.set_thread_goal
        self._clear_thread_goal = thread.clear_thread_goal
        self._submit_to_runtime = coordination.submit_to_runtime
        self._external_control_write_denial_check = (
            policy.external_control_write_denial_check
        )
        self._resolve_thread_target_for_control_params = (
            thread.resolve_thread_target_for_control_params
        )
        self._operational_status = coordination.operational_status
        self._binding_application = RuntimeAdminBindingApplication(
            lock=lock,
            binding_runtime=binding_runtime,
            thread_lifecycle=thread_lifecycle,
            ports=RuntimeAdminBindingApplicationPorts(
                read_thread=thread.read_thread,
                read_thread_for_stale_cleanup=(thread.read_thread_for_stale_cleanup),
                unsubscribe_thread=thread.unsubscribe_thread,
                attach_binding=thread.attach_binding,
                get_thread_goal=thread.get_thread_goal,
                clear_all_stored_bindings=(coordination.clear_all_stored_bindings),
                deactivate_binding_and_invalidate_queue_locked=(
                    coordination.deactivate_binding_and_invalidate_queue_locked
                ),
                deactivate_bindings_and_invalidate_queues_locked=(
                    coordination.deactivate_bindings_and_invalidate_queues_locked
                ),
                release_service_thread_runtime_lease=(
                    coordination.release_service_thread_runtime_lease
                ),
                instance_name=coordination.instance_name,
                load_thread_runtime_lease=(coordination.load_thread_runtime_lease),
                submit_prompt_for_control=(
                    presentation.submit_prompt_for_control if presentation else None
                ),
                prompt_write_denial_check=policy.prompt_write_denial_check,
                external_control_write_denial_check=(
                    policy.external_control_write_denial_check
                ),
                all_mode_thread_exclusivity_check=(
                    policy.all_mode_thread_exclusivity_check
                ),
                detached_runtime_attach_check=(policy.detached_runtime_attach_check),
                resolve_binding_chat_display_name=(
                    presentation.resolve_binding_chat_display_name
                    if presentation
                    else None
                ),
                is_thread_not_found_error=policy.is_thread_not_found_error,
                is_thread_not_loaded_error=policy.is_thread_not_loaded_error,
                invalidate_feishu_execution_queue_locked=(
                    coordination.invalidate_feishu_execution_queue_locked
                ),
                invalidate_all_feishu_execution_queues_locked=(
                    coordination.invalidate_all_feishu_execution_queues_locked
                ),
                operational_status=coordination.operational_status,
                thread_has_pending_request_locked=(
                    interaction_requests.thread_has_pending_request_locked
                ),
                binding_has_pending_request_locked=(
                    interaction_requests.binding_has_pending_request_locked
                ),
            ),
        )
        self._backend_reset_diagnostics = BackendResetDiagnostics(
            BackendResetDiagnosticsPorts(
                instance_name=self._instance_name,
                format_binding_ids=self._format_binding_ids,
                short_thread_ids=self._short_thread_ids,
            )
        )
        self._control_router = RuntimeAdminControlRouter(
            RuntimeAdminControlRouterPorts(
                service=RuntimeAdminServiceControlPorts(
                    binding_inventory_snapshot=(
                        self._binding_application.binding_inventory_snapshot
                    ),
                    backend_reset_preview=self.backend_reset_preview,
                    list_loaded_thread_ids=self._list_loaded_thread_ids,
                    instance_name=self._instance_name,
                    service_control_endpoint=self._service_control_endpoint,
                    current_app_server_url=self._current_app_server_url,
                    web_gateway_enabled=self._web_gateway_enabled,
                    current_web_gateway_url=self._current_web_gateway_url,
                    operational_status=self._operational_status,
                    reset_backend=self._reset_current_instance_backend,
                    attach_service=lambda: (
                        self._binding_application.attach_service(writer_binding=None)
                    ),
                ),
                binding=RuntimeAdminBindingControlPorts(
                    list_response=(self._binding_application.binding_list_response),
                    status_snapshot=(self._binding_application.binding_status_snapshot),
                    attach=lambda binding: (
                        self._binding_application.attach_binding(
                            binding,
                            writer_binding=None,
                        )
                    ),
                    submit_prompt=(
                        self._binding_application.submit_binding_prompt_for_control
                    ),
                    detach=self._binding_application.detach_binding,
                    clear=self._binding_application.clear_binding_for_control,
                    clear_all=(
                        self._binding_application.clear_all_bindings_for_control
                    ),
                    clear_stale=(
                        self._binding_application.clear_stale_bindings_for_control
                    ),
                ),
                thread=RuntimeAdminThreadControlPorts(
                    resolve_target=self._resolve_thread_target_for_control_params,
                    status_snapshot=(self._binding_application.thread_status_snapshot),
                    goal_snapshot=self.thread_goal_snapshot,
                    set_goal=self.set_thread_goal_for_control,
                    clear_goal=self.clear_thread_goal_for_control,
                    clear_archived_bindings=(
                        self.clear_archived_thread_bindings_for_control
                    ),
                    local_bindings=self.local_thread_bindings_for_control,
                    loaded_status=self.loaded_thread_status_for_control,
                    archive=self.archive_thread_for_control,
                    unarchive=self.unarchive_thread_for_control,
                    delete=self.delete_thread_for_control,
                    send_image=self.send_image_to_thread_attached_bindings,
                    attach=lambda thread_id: (
                        self._binding_application.attach_thread(
                            thread_id,
                            writer_binding=None,
                        )
                    ),
                    detach=self._binding_application.detach_thread,
                ),
            )
        )

    def binding_inventory_locked(self) -> list[dict[str, Any]]:
        return self._binding_application.binding_inventory_locked()

    def read_thread_summary_for_status(
        self,
        thread_id: str,
    ) -> tuple[ThreadSummary | None, str]:
        return self._thread_lifecycle.read_thread_summary_for_status(thread_id)

    def _require_direct_thread_target(
        self,
        thread_id: str,
        *,
        operation: str,
    ) -> ThreadSummary:
        normalized_thread_id = str(thread_id or "").strip()
        try:
            return read_direct_thread_target(
                normalized_thread_id,
                read_thread=self._read_thread,
                operation=operation,
            )
        except DirectThreadTargetPolicyError as exc:
            raise ThreadLifecyclePolicyError(str(exc)) from exc
        except Exception as exc:
            raise ThreadLifecyclePolicyError(
                "无法确认 root thread 是否可直接操作；已按 fail-closed 拒绝"
                f" {operation}。"
            ) from exc

    def loaded_thread_status_for_control(self, thread_id: str) -> dict[str, str]:
        return self._thread_lifecycle.loaded_thread_status_for_control(thread_id)

    def clear_all_bindings_for_control(self) -> dict[str, Any]:
        return self._binding_application.clear_all_bindings_for_control()

    def binding_status_snapshot(
        self,
        binding: ChatBindingKey,
    ) -> dict[str, Any]:
        return self._binding_application.binding_status_snapshot(binding)

    @staticmethod
    def _thread_goal_snapshot(goal: ThreadGoalSummary | None) -> dict[str, Any] | None:
        if goal is None:
            return None
        return {
            "thread_id": goal.thread_id,
            "objective": goal.objective,
            "status": goal.status,
            "token_budget": goal.token_budget,
            "tokens_used": goal.tokens_used,
            "time_used_seconds": goal.time_used_seconds,
            "created_at": goal.created_at,
            "updated_at": goal.updated_at,
        }

    @staticmethod
    def _thread_identity_snapshot(summary: ThreadSummary) -> dict[str, Any]:
        return {
            "thread_id": summary.thread_id,
            "thread_title": summary.title,
            "working_dir": summary.cwd,
        }

    def thread_goal_snapshot(
        self, thread_id: str, *, summary: ThreadSummary
    ) -> dict[str, Any]:
        verified_summary = self._require_direct_thread_target(
            thread_id, operation="查看 goal"
        )
        goal = self._get_thread_goal(verified_summary.thread_id)
        return {
            **self._thread_identity_snapshot(verified_summary),
            "goal": self._thread_goal_snapshot(goal),
        }

    def set_thread_goal_for_control(
        self,
        thread_id: str,
        *,
        summary: ThreadSummary,
        objective: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        verified_summary = self._require_direct_thread_target(
            thread_id, operation="修改 goal"
        )
        normalized_thread_id = verified_summary.thread_id
        denial = self._external_control_write_denial_check(normalized_thread_id)
        if not denial.allowed:
            raise ThreadLifecyclePolicyError(
                denial.reason_text or "当前 main-turn 状态不允许从控制面修改 goal。"
            )
        normalized_objective = None
        if objective is not None:
            normalized_objective = str(objective or "").strip()
            if not normalized_objective:
                raise ValueError("thread/goal/set 的 objective 不能为空。")
        normalized_status = None
        if status is not None:
            normalized_status = str(status or "").strip()
            if not normalized_status:
                raise ValueError("thread/goal/set 的 status 不能为空。")
        if normalized_objective is None and normalized_status is None:
            raise ValueError("thread/goal/set 至少需要 `objective` 或 `status`。")
        # The local control plane intentionally has no live frontend identity
        # that could receive an approval/question.  In current app-server
        # behavior an objective-only set can default to `active`, and an
        # explicit `active` set can continue an idle goal immediately.  Do
        # not start such a main turn without an exact frontend submission; Web,
        # Feishu, or fcodex must perform that activation through their own
        # root admission path.  An explicit paused persisted-goal edit remains
        # a bounded maintenance mutation under the existing unowned-root gate.
        may_activate_goal = bool(
            normalized_status == "active"
            or (normalized_objective is not None and normalized_status != "paused")
        )
        if may_activate_goal:
            raise ThreadLifecyclePolicyError(
                "本地控制面不能激活或以默认状态设置 goal；这可能立即启动无人可处理交互的 main turn。"
                "请改由已连接的 Web、飞书或 fcodex writer 执行。"
            )
        goal = self._set_thread_goal(
            normalized_thread_id,
            objective=normalized_objective,
            status=normalized_status,
        )
        return {
            **self._thread_identity_snapshot(verified_summary),
            "goal": self._thread_goal_snapshot(goal),
        }

    def clear_thread_goal_for_control(
        self, thread_id: str, *, summary: ThreadSummary
    ) -> dict[str, Any]:
        verified_summary = self._require_direct_thread_target(
            thread_id, operation="清除 goal"
        )
        # Clearing a goal cannot start a new turn. The external-control gate
        # still rejects a conflicting active/submission lease; when the thread
        # is idle, this is the documented identity-less maintenance exception
        # rather than a writer handoff.
        denial = self._external_control_write_denial_check(verified_summary.thread_id)
        if not denial.allowed:
            raise ThreadLifecyclePolicyError(
                denial.reason_text or "当前 main turn 不允许从控制面清除 goal。"
            )
        cleared = self._clear_thread_goal(verified_summary.thread_id)
        return {
            **self._thread_identity_snapshot(verified_summary),
            "goal": None,
            "cleared": bool(cleared),
        }

    @staticmethod
    def _short_thread_ids(thread_ids: tuple[str, ...] | list[str]) -> str:
        normalized = [
            str(thread_id or "").strip()
            for thread_id in thread_ids
            if str(thread_id or "").strip()
        ]
        if not normalized:
            return "（无）"
        return ", ".join(f"`{thread_id[:8]}…`" for thread_id in normalized)

    @staticmethod
    def _format_binding_ids(binding_ids: tuple[str, ...] | list[str]) -> str:
        normalized = [
            str(binding_id or "").strip()
            for binding_id in binding_ids
            if str(binding_id or "").strip()
        ]
        if not normalized:
            return "（无）"
        return ", ".join(f"`{binding_id}`" for binding_id in normalized)

    @staticmethod
    def _preview_thread_ids(
        thread_ids: tuple[str, ...] | list[str],
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        normalized = [
            str(thread_id or "").strip()
            for thread_id in thread_ids
            if str(thread_id or "").strip()
        ]
        if limit <= 0:
            return ()
        return tuple(normalized[:limit])

    def detach_binding(self, binding: ChatBindingKey) -> dict[str, Any]:
        return self._binding_application.detach_binding(binding)

    def attach_binding(
        self,
        binding: ChatBindingKey,
        *,
        writer_binding: ChatBindingKey | None = None,
    ) -> dict[str, Any]:
        return self._binding_application.attach_binding(
            binding,
            writer_binding=writer_binding,
        )

    def fail_close_service_attached_runtime(self) -> dict[str, Any]:
        return self._binding_application.fail_close_service_attached_runtime()

    def detach_thread(self, thread_id: str) -> dict[str, Any]:
        return self._binding_application.detach_thread(thread_id)

    def archive_thread_for_control(
        self,
        thread_id: str,
        *,
        summary: ThreadSummary | None = None,
        writer_holder: InteractionLeaseHolder | None = None,
    ) -> dict[str, Any]:
        return self._thread_lifecycle.archive_thread_for_control(
            thread_id,
            summary=summary,
            writer_holder=writer_holder,
        )

    def unarchive_thread_for_control(
        self,
        thread_id: str,
        *,
        writer_holder: InteractionLeaseHolder | None = None,
    ) -> dict[str, Any]:
        return self._thread_lifecycle.unarchive_thread_for_control(
            thread_id,
            writer_holder=writer_holder,
        )

    def delete_thread_for_control(
        self,
        thread_id: str,
        *,
        writer_holder: InteractionLeaseHolder | None = None,
    ) -> dict[str, Any]:
        return self._thread_lifecycle.delete_thread_for_control(
            thread_id,
            writer_holder=writer_holder,
        )

    def local_thread_bindings_for_control(self, thread_id: str) -> dict[str, Any]:
        return self._thread_lifecycle.local_thread_bindings_for_control(thread_id)

    def clear_archived_thread_bindings_for_control(
        self,
        thread_id: str,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._thread_lifecycle.clear_archived_thread_bindings_for_control(
            thread_id,
            dry_run=dry_run,
        )

    def send_image_to_thread_attached_bindings(
        self,
        thread_id: str,
        *,
        local_path: str,
        summary: ThreadSummary | None = None,
    ) -> dict[str, Any]:
        if self._thread_image_delivery is None:
            raise RuntimeError(
                "Feishu is disabled; enable feishu_enabled in system.yaml and restart focusd"
            )
        normalized_thread_id = str(thread_id or "").strip()
        with self._lock:
            attached_bindings = tuple(
                self._binding_application.attached_bindings_for_thread_locked(
                    normalized_thread_id
                )
            )
        result = self._thread_image_delivery.deliver_local_image(
            thread_id=normalized_thread_id,
            local_path=local_path,
            attached_bindings=attached_bindings,
        )
        effective_summary = summary
        if effective_summary is None:
            resolved_summary, _backend_thread_status = (
                self.read_thread_summary_for_status(normalized_thread_id)
            )
            effective_summary = resolved_summary
        return {
            "thread_id": result.thread_id,
            "thread_title": effective_summary.title
            if effective_summary is not None
            else "",
            "working_dir": effective_summary.cwd
            if effective_summary is not None
            else "",
            "local_path": result.local_path,
            "attached_binding_ids": [
                item.binding_id for item in (*result.delivered, *result.failed)
            ],
            "delivered_binding_ids": [item.binding_id for item in result.delivered],
            "failed_binding_ids": [item.binding_id for item in result.failed],
            "delivered_message_ids": {
                item.binding_id: item.message_id for item in result.delivered
            },
            "fully_delivered": result.fully_delivered,
        }

    def _backend_reset_preview(self) -> BackendResetPreview:
        pending_request_count = self._pending_interaction_request_count()
        if (
            isinstance(pending_request_count, bool)
            or not isinstance(pending_request_count, int)
            or pending_request_count < 0
        ):
            raise RuntimeError("backend reset pending interaction inventory is invalid")
        with self._lock:
            inventory = self.binding_inventory_locked()
        running_binding_ids = tuple(
            item["binding_id"] for item in inventory if item["running_turn"]
        )
        attached_binding_ids = tuple(
            sorted(
                str(item["binding_id"] or "").strip()
                for item in inventory
                if str(item.get("binding_id") or "").strip()
                and str(item.get("binding_state") or "").strip() == "bound"
                and str(item.get("feishu_runtime_state") or "").strip()
                == FEISHU_RUNTIME_ATTACHED
            )
        )

        loaded_thread_ids: tuple[str, ...] = ()
        active_loaded_thread_ids: tuple[str, ...] = ()
        holder_labels: set[str] = set()
        runtime_verification_failed = False
        try:
            loaded_thread_ids = tuple(
                sorted(
                    str(thread_id or "").strip()
                    for thread_id in self._list_loaded_thread_ids()
                    if str(thread_id or "").strip()
                )
            )
            active_loaded: list[str] = []
            for thread_id in loaded_thread_ids:
                holder_labels.update(
                    self._binding_application.live_runtime_holder_labels(
                        self._load_thread_runtime_lease(thread_id)
                    )
                )
                _summary, backend_status = self.read_thread_summary_for_status(
                    thread_id
                )
                if backend_status in {
                    BACKEND_THREAD_LOOKUP_ERROR,
                    BACKEND_THREAD_LOOKUP_MISSING,
                    BACKEND_THREAD_STATUS_UNKNOWN,
                }:
                    runtime_verification_failed = True
                    continue
                if backend_status == BACKEND_THREAD_STATUS_ACTIVE:
                    active_loaded.append(thread_id)
            active_loaded_thread_ids = tuple(active_loaded)
        except Exception:
            logger.exception("构造 backend reset preview 时读取 loaded thread 失败")
            runtime_verification_failed = True

        common_kwargs = {
            "pending_request_count": pending_request_count,
            "running_binding_ids": running_binding_ids,
            "active_loaded_thread_ids": active_loaded_thread_ids,
            "loaded_thread_ids": loaded_thread_ids,
            "runtime_verification_failed": runtime_verification_failed,
            "blocking_holder_labels": tuple(sorted(holder_labels)),
            "attached_binding_ids": attached_binding_ids,
            "loaded_thread_preview": self._preview_thread_ids(loaded_thread_ids),
            "active_loaded_thread_preview": self._preview_thread_ids(
                active_loaded_thread_ids
            ),
            "blocking_active_turn_count": len(active_loaded_thread_ids),
            "blocking_pending_request_count": pending_request_count,
            "collateral_loaded_thread_count": len(loaded_thread_ids),
            "collateral_active_loaded_thread_count": len(active_loaded_thread_ids),
        }

        if pending_request_count:
            preview = BackendResetPreview(
                status=BACKEND_RESET_STATUS_FORCE_ONLY,
                reason_code=BACKEND_RESET_FORCE_ONLY_BY_PENDING_REQUEST,
                reason_text="当前实例还有待处理审批或输入请求；如确认可打断，可执行 force reset。",
                **common_kwargs,
            )
            return replace(
                preview,
                diagnostics=self._backend_reset_diagnostics.flat_diagnostics(preview),
            )
        if running_binding_ids:
            preview = BackendResetPreview(
                status=BACKEND_RESET_STATUS_FORCE_ONLY,
                reason_code=BACKEND_RESET_FORCE_ONLY_BY_RUNNING_BINDING,
                reason_text="当前实例仍有运行中的 Feishu turn；如确认可打断，可执行 force reset。",
                **common_kwargs,
            )
            return replace(
                preview,
                diagnostics=self._backend_reset_diagnostics.flat_diagnostics(preview),
            )
        if active_loaded_thread_ids:
            preview = BackendResetPreview(
                status=BACKEND_RESET_STATUS_FORCE_ONLY,
                reason_code=BACKEND_RESET_FORCE_ONLY_BY_ACTIVE_LOADED_THREAD,
                reason_text="当前 backend 仍有 active thread；如确认可打断，可执行 force reset。",
                **common_kwargs,
            )
            return replace(
                preview,
                diagnostics=self._backend_reset_diagnostics.flat_diagnostics(preview),
            )
        if runtime_verification_failed:
            preview = BackendResetPreview(
                status=BACKEND_RESET_STATUS_FORCE_ONLY,
                reason_code=BACKEND_RESET_FORCE_ONLY_BY_RUNTIME_UNVERIFIED,
                reason_text="当前无法完整确认 backend 是否仍有运行中的 thread；如确认可打断，可执行 force reset。",
                **common_kwargs,
            )
            return replace(
                preview,
                diagnostics=self._backend_reset_diagnostics.flat_diagnostics(preview),
            )
        preview = BackendResetPreview(
            status=BACKEND_RESET_STATUS_AVAILABLE,
            reason_code="",
            reason_text="当前实例 backend 可安全重置。",
            **common_kwargs,
        )
        return replace(
            preview,
            diagnostics=self._backend_reset_diagnostics.flat_diagnostics(preview),
        )

    def backend_reset_preview(self) -> BackendResetPreview:
        return self._backend_reset_preview()

    def handle_service_control_request(
        self, method: str, params: dict[str, Any]
    ) -> Any:
        if not self._feishu_enabled and (
            method
            in {
                "service/attach",
                "binding/attach",
                "binding/submit-prompt",
                "thread/attach",
                "thread/send-image",
            }
            or (method == "binding/list" and params.get("refresh_names"))
        ):
            raise RuntimeError(
                "Feishu is disabled; enable feishu_enabled in system.yaml and restart focusd"
            )
        return self._control_router.handle(method, params)
