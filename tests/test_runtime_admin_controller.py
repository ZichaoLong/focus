import pathlib
import tempfile
import threading
import types
import unittest

from bot.adapters.base import ThreadSnapshot, ThreadSummary
from bot.binding_runtime_manager import BindingRuntimeManager
from bot.reason_codes import (
    PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
    PROMPT_DENIED_BINDING_NOT_FOUND,
    PROMPT_DENIED_BY_INTERACTION_OWNER,
    PROMPT_DENIED_BY_RUNNING_TURN,
    DETACH_BLOCKED_BY_PENDING_REQUEST,
    ReasonedCheck,
)
from bot.runtime_admin_controller import RuntimeAdminController
from bot.runtime_state import ThreadStateChanged
from bot.stores.chat_binding_store import ChatBindingStore
from bot.stores.interaction_lease_store import InteractionLeaseStore
from bot.stores.thread_runtime_lease_store import ThreadRuntimeLease, ThreadRuntimeLeaseHolder
from bot.thread_subscription_registry import ThreadSubscriptionRegistry
from bot.thread_image_delivery import ThreadImageDeliveryController


class RuntimeAdminControllerTests(unittest.TestCase):
    def _make_controller(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        data_dir = pathlib.Path(tempdir.name)
        lock = threading.RLock()
        chat_binding_store = ChatBindingStore(data_dir)
        binding_runtime = BindingRuntimeManager(
            lock=lock,
            default_working_dir="/tmp/default",
            default_approval_policy="on-request",
            default_sandbox="workspace-write",
            default_collaboration_mode="default",
            default_model="gpt-5.4",
            default_reasoning_effort="medium",
            chat_binding_store=chat_binding_store,
            thread_subscription_registry=ThreadSubscriptionRegistry(),
            interaction_lease_store=InteractionLeaseStore(data_dir),
            is_group_chat=lambda chat_id, message_id: False,
        )
        unsubscribed: list[str] = []
        archived: list[str] = []
        released_runtime_leases: list[str] = []
        pending_by_thread: set[str] = set()
        pending_by_binding: set[tuple[str, str]] = set()
        summaries: dict[str, ThreadSummary] = {}
        loaded_thread_ids: list[str] = []
        pending_requests: list[dict[str, object]] = []
        reset_calls: list[bool] = []
        sent_images: list[tuple[str, str]] = []
        submitted_prompts: list[dict[str, object]] = []
        thread_memory_modes: dict[str, str] = {}

        def _read_thread(thread_id: str):
            return ThreadSnapshot(summary=summaries[thread_id])

        controller = RuntimeAdminController(
            lock=lock,
            binding_runtime=binding_runtime,
            interaction_requests=types.SimpleNamespace(
                thread_has_pending_request_locked=lambda thread_id: thread_id in pending_by_thread,
                binding_has_pending_request_locked=lambda binding: binding in pending_by_binding,
            ),
            clear_all_stored_bindings=chat_binding_store.clear_all,
            deactivate_binding_locked=lambda binding: binding_runtime.deactivate_binding_locked(binding),
            read_thread=_read_thread,
            list_loaded_thread_ids=lambda: list(loaded_thread_ids),
            current_app_server_url=lambda: "http://127.0.0.1:1234",
            app_server_mode=lambda: "managed",
            unsubscribe_thread=lambda thread_id: unsubscribed.append(thread_id),
            archive_thread=lambda thread_id: archived.append(thread_id),
            release_service_thread_runtime_lease=lambda thread_id: released_runtime_leases.append(thread_id),
            service_control_endpoint=lambda: "tcp://127.0.0.1:32001",
            instance_name=lambda: "corp-a",
            load_thread_runtime_lease=lambda thread_id: None,
            list_pending_interaction_requests=lambda: list(pending_requests),
            reset_current_instance_backend=lambda force: reset_calls.append(bool(force)) or {"force": bool(force)},
            attach_binding=lambda binding, thread_id: summaries[thread_id],
            load_thread_resume_profile=lambda thread_id: None,
            load_thread_memory_mode=lambda thread_id: (
                types.SimpleNamespace(mode=thread_memory_modes[thread_id])
                if thread_id in thread_memory_modes
                else None
            ),
            apply_thread_memory_mode=lambda thread_id, mode: (
                thread_memory_modes.__setitem__(thread_id, mode),
                types.SimpleNamespace(mode=mode),
            )[1],
            permissions_summary=lambda approval_policy, sandbox: f"{sandbox}/{approval_policy}",
            thread_image_delivery=ThreadImageDeliveryController(
                upload_image=lambda local_path: "img-key-1",
                send_image_by_key=lambda chat_id, image_key: sent_images.append((chat_id, image_key)) or f"msg:{chat_id}",
                path_exists=lambda path: True,
                path_is_file=lambda path: True,
            ),
            submit_prompt_for_control=lambda binding, **kwargs: submitted_prompts.append(
                {"binding": binding, **kwargs}
            ) or {
                "binding_id": f"p2p:{binding[0]}:{binding[1]}",
                "thread_id": "thread-1",
                "started": True,
                "turn_id": "turn-1",
                "reason_code": "",
                "reason": "",
                "synthetic_source": str(kwargs.get("synthetic_source", "") or ""),
                "display_mode": str(kwargs.get("display_mode", "silent") or "silent"),
            },
            prompt_write_denial_check=lambda binding, chat_id, thread_id, message_id="": ReasonedCheck.allow(),
            detached_runtime_attach_check=lambda thread_id: ReasonedCheck.allow(),
            resolve_thread_target_for_control_params=lambda params: ThreadSummary(
                thread_id=str(params.get("thread_id", "") or "").strip(),
                cwd="/tmp/project",
                name="demo",
                preview="",
                created_at=0,
                updated_at=0,
                source="cli",
                status="idle",
            ),
            cancel_patch_timer_locked=lambda state: state.update({"patch_timer": None}),
            cancel_mirror_watchdog_locked=lambda state: state.update({"mirror_watchdog_timer": None}),
            is_thread_not_found_error=lambda exc: False,
            is_thread_not_loaded_error=lambda exc: False,
            reprofile_possible_check=lambda thread_id: (thread_id not in loaded_thread_ids, ""),
        )
        controller._submitted_prompts = submitted_prompts  # type: ignore[attr-defined]
        controller._thread_memory_modes = thread_memory_modes  # type: ignore[attr-defined]
        return (
            lock,
            binding_runtime,
            controller,
            summaries,
            loaded_thread_ids,
            unsubscribed,
            archived,
            released_runtime_leases,
            pending_by_thread,
            pending_by_binding,
            pending_requests,
            reset_calls,
            sent_images,
        )

    def _bind_thread(self, lock, binding_runtime, binding, *, thread_id: str):
        with lock:
            state = binding_runtime.get_or_create_runtime_state_locked(binding)
            binding_runtime.bind_thread_locked(
                binding,
                state,
                thread_id=thread_id,
                thread_title="demo",
                working_dir="/tmp/project",
            )
        return state

    def test_detach_thread_availability_locked_blocks_on_pending_request(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        pending_by_thread.add("thread-1")

        allowed, reason = controller.detach_thread_availability_locked("thread-1")

        self.assertFalse(allowed)
        self.assertIn("审批或输入请求未处理", reason)
        check = controller.detach_thread_check_locked("thread-1")
        self.assertEqual(check.reason_code, DETACH_BLOCKED_BY_PENDING_REQUEST)

    def test_unsubscribe_by_thread_id_marks_binding_detached_and_unsubscribes(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            unsubscribed,
            _archived,
            released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )

        result = controller.detach_thread("thread-1")

        self.assertTrue(result["changed"])
        self.assertEqual(result["detached_binding_ids"], ["p2p:ou_user:c1"])
        with lock:
            snapshot = binding_runtime.binding_runtime_snapshot_locked(binding)
        assert snapshot is not None
        self.assertEqual(snapshot.feishu_runtime_state, "detached")
        self.assertEqual(unsubscribed, ["thread-1"])
        self.assertEqual(released_runtime_leases, ["thread-1"])

    def test_unsubscribe_by_thread_id_keeps_binding_attached_when_backend_unsubscribe_fails(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            unsubscribed,
            _archived,
            released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        def _fail_unsubscribe(thread_id: str) -> None:
            unsubscribed.append(thread_id)
            raise RuntimeError("backend unsubscribe failed")

        controller._unsubscribe_thread = _fail_unsubscribe

        with self.assertRaisesRegex(RuntimeError, "backend unsubscribe failed"):
            controller.detach_thread("thread-1")

        with lock:
            snapshot = binding_runtime.binding_runtime_snapshot_locked(binding)
        assert snapshot is not None
        self.assertEqual(snapshot.feishu_runtime_state, "attached")
        self.assertEqual(binding_runtime.attached_bindings_for_thread_locked("thread-1"), [binding])
        self.assertEqual(unsubscribed, ["thread-1"])
        self.assertEqual(released_runtime_leases, [])

        controller._unsubscribe_thread = lambda thread_id: unsubscribed.append(f"retry:{thread_id}")
        result = controller.detach_thread("thread-1")

        self.assertTrue(result["changed"])
        with lock:
            snapshot = binding_runtime.binding_runtime_snapshot_locked(binding)
        assert snapshot is not None
        self.assertEqual(snapshot.feishu_runtime_state, "detached")
        self.assertEqual(unsubscribed, ["thread-1", "retry:thread-1"])
        self.assertEqual(released_runtime_leases, ["thread-1"])

    def test_archive_thread_for_control_archives_and_clears_current_instance_bindings(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            unsubscribed,
            archived,
            released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding_a = ("ou_user", "c1")
        binding_b = ("ou_user2", "c2")
        self._bind_thread(lock, binding_runtime, binding_a, thread_id="thread-1")
        self._bind_thread(lock, binding_runtime, binding_b, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.archive_thread_for_control("thread-1", summary=summaries["thread-1"])

        self.assertEqual(archived, ["thread-1"])
        self.assertEqual(unsubscribed, ["thread-1"])
        self.assertEqual(released_runtime_leases, ["thread-1"])
        self.assertEqual(
            result["cleared_binding_ids"],
            ["p2p:ou_user:c1", "p2p:ou_user2:c2"],
        )
        with lock:
            self.assertIsNone(binding_runtime.binding_runtime_snapshot_locked(binding_a))
            self.assertIsNone(binding_runtime.binding_runtime_snapshot_locked(binding_b))

    def test_archive_thread_for_control_rejects_other_instance_live_runtime_owner(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )
        controller._load_thread_runtime_lease = lambda thread_id: ThreadRuntimeLease(
            thread_id=thread_id,
            owner_instance="explorer",
            owner_service_token="svc-token",
            control_endpoint="tcp://127.0.0.1:32001",
            backend_url="ws://127.0.0.1:8765",
            attached_at=1.0,
            holders=(),
        )

        with self.assertRaisesRegex(ValueError, "explorer"):
            controller.archive_thread_for_control("thread-1", summary=summaries["thread-1"])

        self.assertEqual(archived, [])
        with lock:
            self.assertIsNotNone(binding_runtime.binding_runtime_snapshot_locked(binding))

    def test_fail_close_service_attached_runtime_downgrades_attached_without_backend_unsubscribe(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            unsubscribed,
            _archived,
            released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding_a = ("ou_user", "c1")
        binding_b = ("ou_user2", "c2")
        self._bind_thread(lock, binding_runtime, binding_a, thread_id="thread-1")
        self._bind_thread(lock, binding_runtime, binding_b, thread_id="thread-2")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo-1",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )
        summaries["thread-2"] = ThreadSummary(
            thread_id="thread-2",
            cwd="/tmp/project",
            name="demo-2",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.fail_close_service_attached_runtime()

        self.assertCountEqual(
            result["detached_binding_ids"],
            ["p2p:ou_user:c1", "p2p:ou_user2:c2"],
        )
        self.assertEqual(result["detached_thread_ids"], ["thread-1", "thread-2"])
        self.assertEqual(result["released_thread_ids"], ["thread-1", "thread-2"])
        self.assertEqual(unsubscribed, [])
        self.assertEqual(released_runtime_leases, ["thread-1", "thread-2"])
        with lock:
            snapshot_a = binding_runtime.binding_runtime_snapshot_locked(binding_a)
            snapshot_b = binding_runtime.binding_runtime_snapshot_locked(binding_b)
        assert snapshot_a is not None
        assert snapshot_b is not None
        self.assertEqual(snapshot_a.feishu_runtime_state, "detached")
        self.assertEqual(snapshot_b.feishu_runtime_state, "detached")

    def test_archive_thread_for_control_rejects_running_binding(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        state = self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        state["running"] = True
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="active",
        )

        with self.assertRaisesRegex(ValueError, "飞书侧 turn 正在运行"):
            controller.archive_thread_for_control("thread-1", summary=summaries["thread-1"])

        self.assertEqual(archived, [])
        with lock:
            self.assertIsNotNone(binding_runtime.binding_runtime_snapshot_locked(binding))

    def test_archive_thread_for_control_rejects_pending_binding_request(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            archived,
            _released_runtime_leases,
            _pending_by_thread,
            pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        pending_by_binding.add(binding)
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        with self.assertRaisesRegex(ValueError, "待处理审批或补充输入"):
            controller.archive_thread_for_control("thread-1", summary=summaries["thread-1"])

        self.assertEqual(archived, [])
        with lock:
            self.assertIsNotNone(binding_runtime.binding_runtime_snapshot_locked(binding))

    def test_handle_service_control_request_service_status_aggregates_runtime_inventory(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        state = self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        state["running"] = True
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="active",
        )
        loaded_thread_ids.append("thread-1")

        status = controller.handle_service_control_request("service/status", {})

        self.assertEqual(status["instance_name"], "corp-a")
        self.assertEqual(status["binding_count"], 1)
        self.assertEqual(status["bound_binding_count"], 1)
        self.assertEqual(status["attached_binding_count"], 1)
        self.assertEqual(status["thread_count"], 1)
        self.assertEqual(status["loaded_thread_ids"], ["thread-1"])
        self.assertEqual(status["running_binding_ids"], ["p2p:ou_user:c1"])
        self.assertEqual(status["app_server_url"], "http://127.0.0.1:1234")
        self.assertEqual(status["backend_reset_status"], "force-only")
        self.assertEqual(status["backend_reset_reason_code"], "backend_reset_force_only_by_running_binding")

    def test_plan_thread_reprofile_allows_direct_write_after_detached_and_globally_unloaded(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        controller.detach_thread("thread-1")

        plan = controller.plan_thread_reprofile("thread-1")

        self.assertEqual(plan.status, "direct-write")
        self.assertEqual(plan.backend_thread_status, "notLoaded")
        self.assertEqual(plan.feishu_runtime_state, "detached")
        self.assertIn("verifiably globally unloaded", plan.reason_text)

    def test_plan_thread_reprofile_treats_thread_not_loaded_read_error_as_not_loaded(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            _summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        controller._read_thread = lambda thread_id: (_ for _ in ()).throw(RuntimeError("thread not loaded: thread-1"))
        controller._is_thread_not_loaded_error = lambda exc: "thread not loaded:" in str(exc)

        plan = controller.plan_thread_reprofile("thread-1")

        self.assertEqual(plan.status, "reset-available")
        self.assertEqual(plan.backend_thread_status, "notLoaded")

    def test_plan_thread_reprofile_blocks_when_live_runtime_owned_by_other_instance(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )
        controller._load_thread_runtime_lease = lambda thread_id: ThreadRuntimeLease(
            thread_id=thread_id,
            owner_instance="other-instance",
            owner_service_token="other-token",
            control_endpoint="tcp://127.0.0.1:9393",
            backend_url="ws://127.0.0.1:8765",
            attached_at=1.0,
            holders=(),
        )

        plan = controller.plan_thread_reprofile("thread-1")

        self.assertEqual(plan.status, "blocked")
        self.assertEqual(plan.reason_code, "reprofile_blocked_by_other_instance_owner")
        self.assertIn("other-instance", plan.reason_text)

    def test_thread_status_snapshot_exposes_machine_global_live_runtime_owner(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        controller._load_thread_runtime_lease = lambda thread_id: ThreadRuntimeLease(
            thread_id=thread_id,
            owner_instance="explorer",
            owner_service_token="svc-token",
            control_endpoint="tcp://127.0.0.1:32001",
            backend_url="ws://127.0.0.1:8765",
            attached_at=1.0,
            holders=(
                ThreadRuntimeLeaseHolder(
                    holder_id="service:svc-token",
                    holder_type="service",
                    instance_name="explorer",
                    owner_pid=4321,
                    owner_service_token="svc-token",
                    control_endpoint="tcp://127.0.0.1:32001",
                    backend_url="ws://127.0.0.1:8765",
                    updated_at=1.0,
                ),
            ),
        )

        snapshot = controller.thread_status_snapshot("thread-1")

        self.assertEqual(snapshot["backend_thread_status"], "notLoaded")
        self.assertEqual(snapshot["live_runtime_owner"]["label"], "explorer")
        self.assertEqual(snapshot["live_runtime_holder_labels"], ["service@explorer(pid=4321)"])
        self.assertEqual(snapshot["thread_memory_mode"], "（未设置）")

    def test_handle_service_control_request_reset_backend_forwards_force_flag(self) -> None:
        (
            _lock,
            _binding_runtime,
            controller,
            _summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            reset_calls,
            _sent_images,
        ) = self._make_controller()

        result = controller.handle_service_control_request("service/reset-backend", {"force": True})

        self.assertEqual(reset_calls, [True])
        self.assertTrue(result["force"])

    def test_handle_reset_backend_command_renders_available_preview_card(self) -> None:
        (
            _lock,
            _binding_runtime,
            controller,
            _summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()

        result = controller.handle_reset_backend_command("")

        assert result.card is not None
        self.assertEqual(result.card["header"]["title"]["content"], "Codex Backend Reset")
        self.assertIn("作用对象：当前实例 backend", result.card["elements"][0]["content"])
        action = result.card["elements"][2]["actions"][0]
        self.assertEqual(action["text"]["content"], "重置 backend")
        self.assertEqual(action["value"]["force"], False)

    def test_handle_reset_backend_command_renders_force_reset_button_when_force_only(self) -> None:
        (
            _lock,
            _binding_runtime,
            controller,
            _summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        pending_requests.append({"request_id": "req-1"})

        result = controller.handle_reset_backend_command("")

        assert result.card is not None
        self.assertIn("只能显式确认强制重置", result.card["elements"][0]["content"])
        action = result.card["elements"][2]["actions"][0]
        self.assertEqual(action["text"]["content"], "强制重置 backend")
        self.assertEqual(action["value"]["force"], True)

    def test_handle_reset_backend_action_executes_reset_and_returns_result_card(self) -> None:
        (
            _lock,
            _binding_runtime,
            controller,
            _summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            reset_calls,
            _sent_images,
        ) = self._make_controller()

        response = controller.handle_reset_backend_action("ou_user", "c1", "m1", {"force": True})

        self.assertEqual(reset_calls, [True])
        self.assertEqual(response.toast.type, "success")
        self.assertEqual(response.toast.content, "已重置当前实例 backend。")
        self.assertIsNotNone(response.card)
        assert response.card is not None
        self.assertEqual(response.card.data["header"]["title"]["content"], "Codex Backend Reset")
        self.assertIn("已重置当前实例 backend。", response.card.data["elements"][0]["content"])
        self.assertIn("如需确认飞书侧继续接收本地", response.card.data["elements"][0]["content"])
        actions = response.card.data["elements"][-1]["actions"]
        self.assertEqual([action["text"]["content"] for action in actions], ["附着当前实例", "保持 detached"])

    def test_handle_reset_backend_action_offers_current_thread_attach_after_reset(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        response = controller.handle_reset_backend_action("ou_user", "c1", "m1", {"force": False})

        self.assertIsNotNone(response.card)
        assert response.card is not None
        actions = response.card.data["elements"][-1]["actions"]
        self.assertEqual(
            [action["text"]["content"] for action in actions],
            ["附着当前线程", "附着当前实例", "保持 detached"],
        )
        self.assertEqual(actions[0]["value"]["thread_id"], "thread-1")

    def test_attach_service_is_partial_success_by_thread(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding_one = ("ou_user", "c1")
        binding_two = ("ou_user", "c2")
        state_one = self._bind_thread(lock, binding_runtime, binding_one, thread_id="thread-1")
        state_two = self._bind_thread(lock, binding_runtime, binding_two, thread_id="thread-2")
        with lock:
            state_one["feishu_runtime_state"] = "detached"
            state_two["feishu_runtime_state"] = "detached"
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo-1",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        summaries["thread-2"] = ThreadSummary(
            thread_id="thread-2",
            cwd="/tmp/project",
            name="demo-2",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        controller._detached_runtime_attach_check = lambda thread_id: (
            ReasonedCheck.allow()
            if thread_id == "thread-1"
            else ReasonedCheck.deny(
                PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
                "当前 thread 仍由运行中的实例 `explorer` 保持为 loaded (`idle`)；当前不支持跨实例 hot takeover。",
            )
        )

        result = controller.attach_service()

        self.assertEqual(result["attached_thread_ids"], ["thread-1"])
        self.assertEqual(result["attached_binding_ids"], ["p2p:ou_user:c1"])
        self.assertEqual(len(result["blocked_threads"]), 1)
        self.assertEqual(result["blocked_threads"][0]["thread_id"], "thread-2")
        self.assertEqual(result["blocked_threads"][0]["binding_ids"], ["p2p:ou_user:c2"])
        self.assertIn("不支持跨实例 hot takeover", result["blocked_threads"][0]["reason"])

    def test_handle_preflight_command_blocks_detached_binding_when_live_runtime_owner_blocks_attach(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        state = self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        state["feishu_runtime_state"] = "detached"
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        controller._detached_runtime_attach_check = lambda thread_id: ReasonedCheck.deny(
            PROMPT_DENIED_BY_LIVE_RUNTIME_OWNER,
            "当前线程正由实例 `default` 的本地 `fcodex` 持有 live runtime；当前不能自动转移。",
        )

        result = controller.handle_preflight_command(binding, "")

        assert result.card is not None
        content = result.card["elements"][0]["content"]
        self.assertIn("下一条普通消息：`blocked` (`prompt_denied_by_live_runtime_owner`)", content)
        self.assertIn("本地 `fcodex` 持有 live runtime", content)

    def test_service_status_reports_runtime_unverified_as_force_only(self) -> None:
        (
            _lock,
            _binding_runtime,
            controller,
            _summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        controller._list_loaded_thread_ids = lambda: (_ for _ in ()).throw(RuntimeError("backend down"))

        status = controller.handle_service_control_request("service/status", {})

        self.assertEqual(status["backend_reset_status"], "force-only")
        self.assertEqual(
            status["backend_reset_reason_code"],
            "backend_reset_force_only_by_runtime_unverified",
        )

    def test_plan_thread_reprofile_uses_force_only_reason_when_runtime_is_unverified(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )
        controller._list_loaded_thread_ids = lambda: (_ for _ in ()).throw(RuntimeError("backend down"))

        plan = controller.plan_thread_reprofile("thread-1")

        self.assertEqual(plan.status, "reset-force-only")
        self.assertEqual(
            plan.reason_code,
            "reprofile_reset_force_only_by_runtime_unverified",
        )

    def test_clear_all_bindings_for_control_rejects_when_binding_has_pending_request(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )
        pending_by_binding.add(binding)

        with self.assertRaises(ValueError) as ctx:
            controller.clear_all_bindings_for_control()

        self.assertIn("p2p:ou_user:c1", str(ctx.exception))
        self.assertIn("不能清除 binding", str(ctx.exception))

    def test_handle_service_control_request_thread_bindings_reports_attached_and_detached(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding_a = ("ou_user", "c1")
        binding_b = ("ou_user2", "c2")
        self._bind_thread(lock, binding_runtime, binding_a, thread_id="thread-1")
        state_b = self._bind_thread(lock, binding_runtime, binding_b, thread_id="thread-1")
        with lock:
            binding_runtime.unsubscribe_thread_locked(binding_b, "thread-1")
            binding_runtime.apply_persisted_runtime_state_message_locked(
                binding_b,
                state_b,
                ThreadStateChanged(feishu_runtime_state="detached"),
            )
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.handle_service_control_request("thread/bindings", {"thread_id": "thread-1"})

        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(
            result["bindings"],
            [
                {"binding_id": "p2p:ou_user:c1", "feishu_runtime_state": "attached"},
                {"binding_id": "p2p:ou_user2:c2", "feishu_runtime_state": "detached"},
            ],
        )

    def test_handle_service_control_request_thread_memory_reports_plan_without_mutation(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.handle_service_control_request("thread/memory", {"thread_id": "thread-1"})

        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(result["thread_memory_mode"], "（未设置）")
        self.assertEqual(result["plan_status"], "reset-available")
        self.assertFalse(result["applied"])

    def test_handle_service_control_request_thread_memory_applies_direct_write(self) -> None:
        (
            _lock,
            _binding_runtime,
            controller,
            summaries,
            loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        )
        loaded_thread_ids.clear()

        result = controller.handle_service_control_request(
            "thread/memory",
            {"thread_id": "thread-1", "mode": "read"},
        )

        self.assertTrue(result["applied"])
        self.assertEqual(result["thread_memory_mode"], "read")
        self.assertEqual(controller._thread_memory_modes["thread-1"], "read")  # type: ignore[attr-defined]

    def test_handle_service_control_request_thread_memory_can_reset_backend_then_apply(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.handle_service_control_request(
            "thread/memory",
            {"thread_id": "thread-1", "mode": "read_write", "reset_backend": True},
        )

        self.assertTrue(result["applied"])
        self.assertTrue(result["backend_reset_performed"])
        self.assertEqual(reset_calls, [False])
        self.assertEqual(controller._thread_memory_modes["thread-1"], "read_write")  # type: ignore[attr-defined]

    def test_handle_service_control_request_thread_archive_dispatches_control_action(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            archived,
            released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.handle_service_control_request("thread/archive", {"thread_id": "thread-1"})

        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(archived, ["thread-1"])
        self.assertEqual(released_runtime_leases, ["thread-1"])

    def test_handle_service_control_request_thread_send_image_fanouts_to_attached_bindings(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            sent_images,
        ) = self._make_controller()
        binding_a = ("ou_user", "c1")
        binding_b = ("ou_user2", "c2")
        self._bind_thread(lock, binding_runtime, binding_a, thread_id="thread-1")
        self._bind_thread(lock, binding_runtime, binding_b, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.handle_service_control_request(
            "thread/send-image",
            {
                "thread_id": "thread-1",
                "local_path": "/tmp/generated.png",
            },
        )

        self.assertTrue(result["fully_delivered"])
        self.assertEqual(result["delivered_binding_ids"], ["p2p:ou_user:c1", "p2p:ou_user2:c2"])
        self.assertEqual(result["failed_binding_ids"], [])
        self.assertEqual(
            sent_images,
            [("c1", "img-key-1"), ("c2", "img-key-1")],
        )

    def test_handle_service_control_request_binding_submit_prompt_dispatches_callback(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )

        result = controller.handle_service_control_request(
            "binding/submit-prompt",
            {
                "binding_id": "p2p:ou_user:c1",
                "text": "继续执行",
                "synthetic_source": "schedule",
                "display_mode": "announce",
            },
        )

        self.assertTrue(result["started"])
        self.assertEqual(result["thread_id"], "thread-1")
        self.assertEqual(result["turn_id"], "turn-1")
        submitted_prompts = getattr(controller, "_submitted_prompts")
        self.assertEqual(len(submitted_prompts), 1)
        self.assertEqual(submitted_prompts[0]["binding"], ("ou_user", "c1"))
        self.assertEqual(submitted_prompts[0]["text"], "继续执行")
        self.assertEqual(submitted_prompts[0]["synthetic_source"], "schedule")
        self.assertEqual(submitted_prompts[0]["display_mode"], "announce")

    def test_handle_service_control_request_binding_submit_prompt_fail_closes_on_preflight_denial(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        binding = ("ou_user", "c1")
        state = self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        state["running"] = True
        state["current_turn_id"] = "turn-1"
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="active",
        )

        result = controller.handle_service_control_request(
            "binding/submit-prompt",
            {
                "binding_id": "p2p:ou_user:c1",
                "text": "继续执行",
            },
        )

        self.assertFalse(result["started"])
        self.assertEqual(result["reason_code"], PROMPT_DENIED_BY_RUNNING_TURN)
        self.assertEqual(getattr(controller, "_submitted_prompts"), [])

    def test_handle_service_control_request_binding_submit_prompt_rejects_missing_binding(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            _summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            _pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()

        result = controller.handle_service_control_request(
            "binding/submit-prompt",
            {
                "binding_id": "p2p:ou_typo:chat-typo",
                "text": "继续执行",
            },
        )

        self.assertFalse(result["started"])
        self.assertEqual(result["reason_code"], PROMPT_DENIED_BINDING_NOT_FOUND)
        self.assertEqual(result["reason"], "未找到 binding：p2p:ou_typo:chat-typo")
        self.assertEqual(getattr(controller, "_submitted_prompts"), [])
        with lock:
            self.assertIsNone(binding_runtime.binding_runtime_snapshot_locked(("ou_typo", "chat-typo")))

    def test_binding_status_snapshot_includes_prompt_and_detach_reason_codes(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        controller._prompt_write_denial_check = lambda binding, chat_id, thread_id, message_id="": ReasonedCheck.deny(
            PROMPT_DENIED_BY_INTERACTION_OWNER,
            "当前线程正由另一飞书会话执行；本会话可继续查看，但暂时不能写入。待对方执行结束后再试。",
        )
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )
        pending_by_binding.add(binding)

        snapshot = controller.binding_status_snapshot(binding)

        self.assertFalse(snapshot["next_prompt_allowed"])
        self.assertEqual(snapshot["next_prompt_reason_code"], PROMPT_DENIED_BY_INTERACTION_OWNER)
        self.assertFalse(snapshot["detach_available"])
        self.assertEqual(snapshot["detach_reason_code"], DETACH_BLOCKED_BY_PENDING_REQUEST)

    def test_handle_preflight_command_renders_next_prompt_and_unsubscribe_checks(self) -> None:
        (
            lock,
            binding_runtime,
            controller,
            summaries,
            _loaded_thread_ids,
            _unsubscribed,
            _archived,
            _released_runtime_leases,
            _pending_by_thread,
            pending_by_binding,
            _pending_requests,
            _reset_calls,
            _sent_images,
        ) = self._make_controller()
        controller._prompt_write_denial_check = lambda binding, chat_id, thread_id, message_id="": ReasonedCheck.deny(
            PROMPT_DENIED_BY_INTERACTION_OWNER,
            "当前线程正由另一飞书会话执行；本会话可继续查看，但暂时不能写入。待对方执行结束后再试。",
        )
        binding = ("ou_user", "c1")
        self._bind_thread(lock, binding_runtime, binding, thread_id="thread-1")
        summaries["thread-1"] = ThreadSummary(
            thread_id="thread-1",
            cwd="/tmp/project",
            name="demo",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="idle",
        )
        pending_by_binding.add(binding)

        result = controller.handle_preflight_command(binding, "")

        card = result.card
        assert card is not None
        content = card["elements"][0]["content"]
        self.assertIn("作用对象：当前 chat binding；这是 dry-run", content)
        self.assertIn("下一条普通消息：`blocked` (`prompt_denied_by_interaction_owner`)", content)
        self.assertIn("detach：`blocked` (`detach_blocked_by_pending_request`)", content)
