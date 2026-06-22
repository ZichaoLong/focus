import pathlib
import tempfile
import threading
import unittest

from bot.adapter_notification_controller import AdapterNotificationController
from bot.binding_runtime_manager import BindingRuntimeManager
from bot.runtime_state import ExecutionStateChanged, apply_runtime_state_message
from bot.stores.chat_binding_store import ChatBindingStore
from bot.stores.interaction_lease_store import InteractionLeaseStore
from bot.thread_subscription_registry import ThreadSubscriptionRegistry
from bot.turn_execution_coordinator import TurnExecutionCoordinator


class AdapterNotificationControllerTests(unittest.TestCase):
    def _make_state(self):
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        data_dir = pathlib.Path(tempdir.name)
        manager = BindingRuntimeManager(
            lock=threading.RLock(),
            default_working_dir="/tmp/default",
            default_approval_policy="on-request",
            default_permissions_profile_id=":workspace",
            default_model="gpt-5.4",
            default_reasoning_effort="medium",
            chat_binding_store=ChatBindingStore(data_dir),
            thread_subscription_registry=ThreadSubscriptionRegistry(),
            interaction_lease_store=InteractionLeaseStore(data_dir),
            is_group_chat=lambda chat_id, message_id: False,
        )
        return manager.build_default_runtime_state()

    def _make_controller(self, states, subscribers_for_thread):
        lock = threading.RLock()
        note_events: list[tuple[str, str]] = []
        patches: list[dict[str, object]] = []
        sent_cards: list[tuple[str, str, bool]] = []
        watchdogs: list[tuple[str, str]] = []
        updates: list[tuple[str, str]] = []
        flushes: list[tuple[str, str, bool]] = []
        plan_flushes: list[tuple[str, str]] = []
        interrupts: list[tuple[str, str]] = []
        finalizations: list[tuple[str, str, str, str]] = []
        resolved: list[dict[str, object]] = []

        def _cancel_mirror_watchdog_locked(state) -> None:
            timer = state["mirror_watchdog_timer"]
            if timer is not None:
                timer.cancel()
            apply_runtime_state_message(
                state,
                ExecutionStateChanged(
                    mirror_watchdog_timer=None,
                    bump_mirror_watchdog_generation=True,
                ),
            )

        controller = AdapterNotificationController(
            lock=lock,
            turn_execution=TurnExecutionCoordinator(),
            thread_subscribers=lambda thread_id: subscribers_for_thread.get(thread_id, ()),
            get_runtime_state=lambda sender_id, chat_id: states[(sender_id, chat_id)],
            on_runtime_event_accepted=lambda sender_id, chat_id: note_events.append((sender_id, chat_id)),
            apply_runtime_state_message_locked=apply_runtime_state_message,
            apply_persisted_runtime_state_message_locked=lambda binding, state, message: apply_runtime_state_message(
                state,
                message,
            ),
            cancel_mirror_watchdog_locked=_cancel_mirror_watchdog_locked,
            finalize_execution_from_terminal_signal=lambda sender_id, chat_id, *, thread_id, turn_id="": (
                finalizations.append((sender_id, chat_id, thread_id, turn_id)) or True
            ),
            dispatch_execution_card_message=lambda message_id, *, transcript, running, elapsed, cancelled: patches.append(
                {
                    "message_id": message_id,
                    "reply_text": transcript.reply_text(),
                    "running": running,
                    "elapsed": elapsed,
                    "cancelled": cancelled,
                }
            )
            or True,
            send_execution_card=lambda chat_id, parent_message_id, *, reply_in_thread=False: sent_cards.append(
                (chat_id, parent_message_id, reply_in_thread)
            )
            or "new-card",
            schedule_mirror_watchdog=lambda sender_id, chat_id: watchdogs.append((sender_id, chat_id)),
            schedule_execution_card_update=lambda sender_id, chat_id: updates.append((sender_id, chat_id)),
            flush_execution_card=lambda sender_id, chat_id, immediate=False: flushes.append(
                (sender_id, chat_id, immediate)
            ),
            flush_plan_card=lambda sender_id, chat_id: plan_flushes.append((sender_id, chat_id)),
            interrupt_running_turn=lambda *, thread_id, turn_id: interrupts.append((thread_id, turn_id)),
            on_server_request_resolved=lambda params: resolved.append(params),
        )
        return controller, note_events, patches, sent_cards, watchdogs, updates, flushes, plan_flushes, interrupts, finalizations, resolved

    def test_handle_notification_routes_server_request_resolved(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        controller, *_, resolved = self._make_controller(
            {binding: state},
            {},
        )

        controller.handle_notification("serverRequest/resolved", {"requestId": "req-1"})
        controller.handle_notification("unknown", {"noop": True})

        self.assertEqual(resolved, [{"requestId": "req-1"}])

    def test_handle_thread_name_updated_updates_all_bound_subscribers(self) -> None:
        binding_a = ("ou_user", "chat-a")
        binding_b = ("ou_user", "chat-b")
        state_a = self._make_state()
        state_b = self._make_state()
        state_a["current_thread_id"] = "thread-1"
        state_b["current_thread_id"] = "thread-1"
        state_a["current_thread_title"] = "old-a"
        state_b["current_thread_title"] = "old-b"

        controller, note_events, *_ = self._make_controller(
            {binding_a: state_a, binding_b: state_b},
            {"thread-1": (binding_a, binding_b)},
        )

        controller.handle_thread_name_updated({"threadId": "thread-1", "threadName": "new-title"})

        self.assertEqual(note_events, [binding_a, binding_b])
        self.assertEqual(state_a["current_thread_title"], "new-title")
        self.assertEqual(state_b["current_thread_title"], "new-title")

    def test_handle_thread_goal_updated_projects_goal_state(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"

        controller, note_events, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_goal_updated(
            {
                "threadId": "thread-1",
                "goal": {
                    "objective": "ship goal support",
                    "status": "active",
                    "tokenBudget": 200,
                    "tokensUsed": 12,
                    "timeUsedSeconds": 34,
                    "createdAt": 1712476800,
                    "updatedAt": 1712476801,
                },
            }
        )

        self.assertEqual(note_events, [binding])
        self.assertEqual(state["goal_objective"], "ship goal support")
        self.assertEqual(state["goal_status"], "active")
        self.assertEqual(state["goal_token_budget"], 200)
        self.assertEqual(state["goal_tokens_used"], 12)
        self.assertEqual(state["goal_time_used_seconds"], 34)

    def test_handle_thread_goal_cleared_resets_goal_projection(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["goal_objective"] = "stale goal"
        state["goal_status"] = "paused"
        state["goal_token_budget"] = 200
        state["goal_tokens_used"] = 12
        state["goal_time_used_seconds"] = 34
        state["goal_created_at"] = 1712476800
        state["goal_updated_at"] = 1712476801

        controller, note_events, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_goal_cleared({"threadId": "thread-1"})

        self.assertEqual(note_events, [binding])
        self.assertEqual(state["goal_objective"], "")
        self.assertEqual(state["goal_status"], "")
        self.assertIsNone(state["goal_token_budget"])
        self.assertEqual(state["goal_tokens_used"], 0)
        self.assertEqual(state["goal_time_used_seconds"], 0)

    def test_handle_turn_started_patches_previous_card_and_assigns_new_card(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "old-card"
        state["execution_transcript"].set_reply_text("old reply")
        state["started_at"] = 2.0

        (
            controller,
            note_events,
            patches,
            sent_cards,
            watchdogs,
            updates,
            *_,
        ) = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_turn_started({"threadId": "thread-1", "turn": {"id": "turn-2"}})

        self.assertEqual(note_events, [binding])
        self.assertEqual(
            patches[0]["message_id"],
            "old-card",
        )
        self.assertEqual(patches[0]["reply_text"], "old reply")
        self.assertEqual(sent_cards, [("chat-1", "", False)])
        self.assertEqual(state["current_message_id"], "new-card")
        self.assertEqual(state["current_turn_id"], "turn-2")
        self.assertEqual(watchdogs, [binding])
        self.assertEqual(updates, [binding])

    def test_handle_turn_started_sends_execution_card_to_each_subscriber(self) -> None:
        binding_a = ("ou_user", "chat-a")
        binding_b = ("ou_user", "chat-b")
        state_a = self._make_state()
        state_b = self._make_state()
        state_a["current_thread_id"] = "thread-1"
        state_b["current_thread_id"] = "thread-1"
        state_a["current_message_id"] = "card-a"
        state_a["running"] = True
        state_a["awaiting_local_turn_started"] = True

        (
            controller,
            note_events,
            _patches,
            sent_cards,
            watchdogs,
            updates,
            *_,
        ) = self._make_controller(
            {binding_a: state_a, binding_b: state_b},
            {"thread-1": (binding_a, binding_b)},
        )

        controller.handle_turn_started({"threadId": "thread-1", "turn": {"id": "turn-1"}})

        self.assertEqual(note_events, [binding_a, binding_b])
        self.assertEqual(sent_cards, [("chat-b", "", False)])
        self.assertEqual(state_a["current_message_id"], "card-a")
        self.assertEqual(state_b["current_message_id"], "new-card")
        self.assertEqual(state_a["current_turn_id"], "turn-1")
        self.assertEqual(state_b["current_turn_id"], "turn-1")
        self.assertEqual(watchdogs, [binding_a, binding_b])
        self.assertEqual(updates, [binding_a, binding_b])

    def test_handle_turn_started_ignores_stale_turn_for_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "queued-card"
        state["current_turn_id"] = "turn-2"
        state["running"] = True
        state["awaiting_local_turn_started"] = True

        (
            controller,
            note_events,
            patches,
            sent_cards,
            watchdogs,
            updates,
            *_,
        ) = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_turn_started({"threadId": "thread-1", "turn": {"id": "turn-1"}})

        self.assertEqual(note_events, [])
        self.assertEqual(patches, [])
        self.assertEqual(sent_cards, [])
        self.assertEqual(watchdogs, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["current_message_id"], "queued-card")
        self.assertEqual(state["current_turn_id"], "turn-2")

    def test_turn_scoped_notifications_without_turn_id_do_not_touch_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "queued-card"
        state["current_turn_id"] = "turn-2"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["current_execution_kind"] = "compact"

        controller, note_events, patches, sent_cards, watchdogs, updates, flushes, plan_flushes, _, finalizations, _ = (
            self._make_controller({binding: state}, {"thread-1": (binding,)})
        )

        cases = [
            lambda: controller.handle_turn_started({"threadId": "thread-1", "turn": {}}),
            lambda: controller.handle_turn_plan_updated({"threadId": "thread-1", "plan": [{"step": "old"}]}),
            lambda: controller.handle_item_started(
                {"threadId": "thread-1", "item": {"type": "contextCompaction", "id": "compact-1"}}
            ),
            lambda: controller.handle_agent_message_delta({"threadId": "thread-1", "delta": "old"}),
            lambda: controller.handle_command_delta({"threadId": "thread-1", "delta": "old stdout"}),
            lambda: controller.handle_file_change_delta({"threadId": "thread-1", "delta": "old patch"}),
            lambda: controller.handle_item_completed(
                {"threadId": "thread-1", "item": {"type": "agentMessage", "text": "old final text"}}
            ),
            lambda: controller.handle_turn_completed({"threadId": "thread-1", "turn": {"status": "completed"}}),
        ]
        for index, call in enumerate(cases):
            with self.subTest(index=index):
                call()

        self.assertEqual(note_events, [])
        self.assertEqual(patches, [])
        self.assertEqual(sent_cards, [])
        self.assertEqual(watchdogs, [])
        self.assertEqual(updates, [])
        self.assertEqual(flushes, [])
        self.assertEqual(plan_flushes, [])
        self.assertEqual(finalizations, [])
        self.assertEqual(state["current_turn_id"], "turn-2")
        self.assertEqual(state["current_message_id"], "queued-card")
        self.assertTrue(state["running"])
        self.assertEqual(state["execution_transcript"].reply_text(), "")
        self.assertEqual(state["execution_transcript"].process_text(), "")

    def test_thread_level_events_for_stale_subscription_do_not_refresh_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-2"
        state["current_thread_title"] = "current"
        state["current_turn_id"] = "turn-2"
        state["current_message_id"] = "card-2"
        state["running"] = True
        state["goal_objective"] = "keep"
        state["goal_status"] = "active"

        controller, note_events, _, _, _, updates, flushes, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_status_changed({"threadId": "thread-1", "status": {"type": "idle"}})
        controller.handle_thread_closed({"threadId": "thread-1"})
        controller.handle_thread_name_updated({"threadId": "thread-1", "threadName": "stale"})
        controller.handle_thread_goal_updated({"threadId": "thread-1", "goal": {"objective": "stale"}})
        controller.handle_thread_goal_cleared({"threadId": "thread-1"})

        self.assertEqual(note_events, [])
        self.assertEqual(updates, [])
        self.assertEqual(flushes, [])
        self.assertEqual(finalizations, [])
        self.assertEqual(state["current_thread_id"], "thread-2")
        self.assertEqual(state["current_thread_title"], "current")
        self.assertEqual(state["current_turn_id"], "turn-2")
        self.assertEqual(state["current_message_id"], "card-2")
        self.assertEqual(state["goal_objective"], "keep")
        self.assertEqual(state["goal_status"], "active")

    def test_handle_thread_status_changed_ignores_idle_while_waiting_for_turn_started(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "card-1"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["awaiting_attach_status_settle"] = True
        state["current_turn_id"] = "turn-1"

        controller, note_events, _, _, _, updates, flushes, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_status_changed({"threadId": "thread-1", "status": {"type": "idle"}})

        self.assertEqual(note_events, [binding])
        self.assertEqual(finalizations, [])
        self.assertEqual(flushes, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["current_message_id"], "card-1")
        self.assertTrue(state["awaiting_local_turn_started"])

    def test_handle_thread_status_changed_ignores_idle_while_turn_id_unbound(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "compact-card"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["awaiting_attach_status_settle"] = False
        state["current_turn_id"] = ""

        controller, note_events, _, _, _, updates, flushes, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_status_changed({"threadId": "thread-1", "status": {"type": "idle"}})

        self.assertEqual(note_events, [binding])
        self.assertEqual(finalizations, [])
        self.assertEqual(flushes, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["current_message_id"], "compact-card")
        self.assertTrue(state["running"])
        self.assertTrue(state["awaiting_local_turn_started"])

    def test_handle_thread_status_changed_active_does_not_clear_waiting_for_turn_started(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "card-1"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["awaiting_attach_status_settle"] = True
        state["current_turn_id"] = "turn-1"

        controller, note_events, _, _, _, updates, flushes, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_status_changed({"threadId": "thread-1", "status": {"type": "active"}})

        self.assertEqual(note_events, [binding])
        self.assertEqual(finalizations, [])
        self.assertEqual(flushes, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["current_message_id"], "card-1")
        self.assertTrue(state["awaiting_local_turn_started"])

    def test_handle_thread_closed_ignores_close_while_waiting_for_turn_started(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "card-1"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["awaiting_attach_status_settle"] = True
        state["current_turn_id"] = "turn-1"

        controller, note_events, _, _, _, _, _, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_closed({"threadId": "thread-1"})

        self.assertEqual(note_events, [binding])
        self.assertEqual(finalizations, [])
        self.assertEqual(state["current_message_id"], "card-1")
        self.assertTrue(state["awaiting_local_turn_started"])

    def test_item_delta_does_not_bind_unstarted_execution_to_stale_turn(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "compact-card"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["current_execution_kind"] = "prompt"
        state["current_turn_id"] = ""

        controller, note_events, _, _, _, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_agent_message_delta({"threadId": "thread-1", "turnId": "old-turn", "delta": "old"})
        controller.handle_item_started(
            {
                "threadId": "thread-1",
                "turnId": "old-turn",
                "item": {"type": "contextCompaction", "id": "compact-1"},
            }
        )

        self.assertEqual(note_events, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["current_turn_id"], "")
        self.assertEqual(state["execution_transcript"].reply_text(), "")
        self.assertEqual(state["execution_transcript"].process_text(), "")

    def test_context_compaction_item_started_binds_unstarted_compact_anchor(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "compact-card"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["current_execution_kind"] = "compact"
        state["current_turn_id"] = ""

        controller, note_events, _, _, watchdogs, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_item_started(
            {
                "threadId": "thread-1",
                "turnId": "compact-turn",
                "item": {"type": "contextCompaction", "id": "compact-1"},
            }
        )

        self.assertEqual(note_events, [binding])
        self.assertEqual(state["current_turn_id"], "compact-turn")
        self.assertFalse(state["awaiting_local_turn_started"])
        self.assertIn("上下文压缩", state["execution_transcript"].process_text())
        self.assertEqual(watchdogs, [binding])
        self.assertEqual(updates, [binding])

    def test_context_compaction_item_started_does_not_bind_unstarted_prompt_anchor(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_message_id"] = "prompt-card"
        state["running"] = True
        state["awaiting_local_turn_started"] = True
        state["current_execution_kind"] = "prompt"
        state["current_turn_id"] = ""

        controller, note_events, _, _, watchdogs, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_item_started(
            {
                "threadId": "thread-1",
                "turnId": "compact-turn",
                "item": {"type": "contextCompaction", "id": "compact-1"},
            }
        )

        self.assertEqual(note_events, [])
        self.assertEqual(state["current_turn_id"], "")
        self.assertTrue(state["awaiting_local_turn_started"])
        self.assertEqual(state["execution_transcript"].process_text(), "")
        self.assertEqual(watchdogs, [])
        self.assertEqual(updates, [])

    def test_handle_turn_completed_delegates_terminal_finalize(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-1"
        state["running"] = True

        controller, note_events, _, _, _, _, _, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_turn_completed({"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}})

        self.assertEqual(note_events, [binding])
        self.assertEqual(finalizations, [("ou_user", "chat-1", "thread-1", "turn-1")])

    def test_handle_turn_completed_ignores_stale_turn_for_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-2"
        state["current_message_id"] = "queued-card"
        state["running"] = True
        state["awaiting_local_turn_started"] = True

        controller, note_events, _, _, _, _, _, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_turn_completed({"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}})

        self.assertEqual(note_events, [])
        self.assertEqual(finalizations, [])
        self.assertEqual(state["current_turn_id"], "turn-2")
        self.assertEqual(state["current_message_id"], "queued-card")
        self.assertTrue(state["running"])

    def test_handle_agent_message_delta_ignores_stale_turn_for_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-2"
        state["current_message_id"] = "queued-card"
        state["running"] = True

        controller, note_events, _, _, _, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_agent_message_delta({"threadId": "thread-1", "turnId": "turn-1", "delta": "old"})

        self.assertEqual(note_events, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["execution_transcript"].reply_text(), "")

    def test_handle_command_delta_ignores_stale_turn_for_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-2"
        state["current_message_id"] = "queued-card"
        state["running"] = True

        controller, note_events, _, _, _, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_command_delta({"threadId": "thread-1", "turnId": "turn-1", "delta": "old stdout"})

        self.assertEqual(note_events, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["execution_transcript"].process_text(), "")

    def test_handle_file_change_delta_ignores_stale_turn_for_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-2"
        state["current_message_id"] = "queued-card"
        state["running"] = True

        controller, note_events, _, _, _, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_file_change_delta({"threadId": "thread-1", "turnId": "turn-1", "delta": "old patch"})

        self.assertEqual(note_events, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["execution_transcript"].process_text(), "")

    def test_handle_item_started_ignores_stale_turn_for_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-2"
        state["current_message_id"] = "queued-card"
        state["running"] = True

        controller, note_events, _, _, _, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_item_started(
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {"type": "commandExecution", "command": "echo old", "cwd": "/tmp"},
            }
        )

        self.assertEqual(note_events, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["execution_transcript"].process_text(), "")

    def test_handle_item_completed_ignores_stale_turn_for_current_execution(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-2"
        state["current_message_id"] = "queued-card"
        state["running"] = True

        controller, note_events, _, _, _, updates, *_ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_item_completed(
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "item": {"type": "agentMessage", "text": "old final text"},
            }
        )

        self.assertEqual(note_events, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["execution_transcript"].reply_text(), "")

    def test_handle_turn_completed_finalizes_each_subscriber(self) -> None:
        binding_a = ("ou_user", "chat-a")
        binding_b = ("ou_user", "chat-b")
        state_a = self._make_state()
        state_b = self._make_state()
        for state in (state_a, state_b):
            state["current_thread_id"] = "thread-1"
            state["current_turn_id"] = "turn-1"
            state["running"] = True

        controller, note_events, _, _, _, _, _, _, _, finalizations, _ = self._make_controller(
            {binding_a: state_a, binding_b: state_b},
            {"thread-1": (binding_a, binding_b)},
        )

        controller.handle_turn_completed({"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}})

        self.assertEqual(note_events, [binding_a, binding_b])
        self.assertEqual(
            finalizations,
            [
                ("ou_user", "chat-a", "thread-1", "turn-1"),
                ("ou_user", "chat-b", "thread-1", "turn-1"),
            ],
        )

    def test_handle_thread_status_changed_system_error_waits_for_error_or_turn_completed(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-1"
        state["current_message_id"] = "card-1"
        state["running"] = True

        controller, note_events, _, _, _, updates, flushes, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_status_changed({"threadId": "thread-1", "status": {"type": "systemError"}})

        self.assertEqual(note_events, [binding])
        self.assertEqual(finalizations, [])
        self.assertEqual(flushes, [])
        self.assertEqual(updates, [])
        self.assertEqual(state["current_message_id"], "card-1")
        self.assertEqual(state["current_turn_id"], "turn-1")

    def test_system_error_followed_by_error_and_turn_completed_preserves_failure_text(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-1"
        state["current_message_id"] = "card-1"
        state["running"] = True

        controller, note_events, _, _, _, updates, _, _, _, finalizations, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_thread_status_changed({"threadId": "thread-1", "status": {"type": "systemError"}})
        controller.handle_notification(
            "error",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "willRetry": False,
                "error": {
                    "message": "Missing environment variable: `CODEX_ZH_API_KEY`.",
                },
            },
        )
        controller.handle_turn_completed(
            {
                "threadId": "thread-1",
                "turn": {
                    "id": "turn-1",
                    "status": "failed",
                    "error": {"message": "Missing environment variable: `CODEX_ZH_API_KEY`."},
                },
            }
        )

        self.assertEqual(
            note_events,
            [binding, binding, binding],
        )
        self.assertEqual(
            updates,
            [binding],
        )
        self.assertEqual(
            state["execution_transcript"].reply_text(),
            "Missing environment variable: `CODEX_ZH_API_KEY`.",
        )
        self.assertEqual(finalizations, [("ou_user", "chat-1", "thread-1", "turn-1")])

    def test_handle_error_notification_uses_non_retry_error_as_fallback_reply(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-1"
        state["running"] = True

        controller, note_events, _, _, _, updates, _, _, _, _, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_notification(
            "error",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "willRetry": False,
                "error": {
                    "message": "provider unavailable",
                    "additionalDetails": "timeout while contacting upstream",
                },
            },
        )

        self.assertEqual(note_events, [binding])
        self.assertEqual(updates, [binding])
        self.assertEqual(
            state["execution_transcript"].reply_text(),
            "provider unavailable\ntimeout while contacting upstream",
        )

    def test_handle_error_notification_records_retry_message_in_process_panel(self) -> None:
        binding = ("ou_user", "chat-1")
        state = self._make_state()
        state["current_thread_id"] = "thread-1"
        state["current_turn_id"] = "turn-1"
        state["running"] = True

        controller, note_events, _, _, _, updates, _, _, _, _, _ = self._make_controller(
            {binding: state},
            {"thread-1": (binding,)},
        )

        controller.handle_notification(
            "error",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "willRetry": True,
                "error": {
                    "message": "temporary transport error",
                },
            },
        )

        self.assertEqual(note_events, [binding])
        self.assertEqual(updates, [binding])
        self.assertEqual(state["execution_transcript"].reply_text(), "")
        self.assertEqual(
            state["execution_transcript"].process_text(),
            "\n[重试中] temporary transport error\n",
        )
