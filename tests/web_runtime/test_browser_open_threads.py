"""Instance-wide browser intent, independent from page and backend residency."""

from dataclasses import replace
from unittest.mock import patch

from bot.web_runtime.contract import WebRuntimeError
from tests.web_runtime.harness import WebRuntimeControllerHarness


class WebBrowserOpenThreadTests(WebRuntimeControllerHarness):
    def setUp(self):
        super().setUp()
        self.controller.client_connected("tab-2")

    def current_ids(self):
        return [t["id"] for t in self.controller.list_threads(scope="current")["threads"]]

    def test_browser_exit_retains_open_intent_and_close_from_another_device_releases(self):
        self.controller.read_thread("tab-1", "thread-1")
        self.controller.client_disconnected("tab-1")
        self.assertEqual(self.fake.unsubscribed, [])
        self.assertEqual(self.current_ids(), ["thread-1"])
        self.assertTrue(self.controller.retains_runtime("thread-1"))

        self.controller.close_thread("tab-2", "thread-1")

        self.assertEqual(self.current_ids(), [])
        self.assertEqual(self.fake.unsubscribed, ["thread-1"])
        self.assertEqual(self.profile_store.load("tab-1").selected_thread_id, "")
        self.assertTrue(any(e.get("reason") == "web_thread_closed" for e in self.events))
        with self.assertRaises(WebRuntimeError) as caught:
            self.controller.prepare_read_thread("tab-2", "thread-1", open_in_browser=False)
        self.assertEqual(caught.exception.code, "thread_not_open")
        self.controller.read_thread("tab-2", "thread-1")
        self.assertEqual(self.current_ids(), ["thread-1"])

    def test_closing_clears_all_selections_without_destroying_thread_attachments(self):
        self.controller.read_thread("tab-1", "thread-1")
        self.controller.read_thread("tab-2", "thread-1")
        self.profile_store.update("offline", selected_thread_id="thread-1", working_dir="/work/keep")
        with patch.object(self.attachment_store, "delete_scope") as delete_scope:
            self.controller.close_thread("tab-2", "thread-1")
        delete_scope.assert_not_called()
        for client in ("tab-1", "tab-2", "offline"):
            self.assertEqual(self.profile_store.load(client).selected_thread_id, "")
        self.assertEqual(self.profile_store.load("offline").working_dir, "/work/keep")

    def test_feishu_subscription_survives_close_but_loaded_rows_do_not_reappear(self):
        self.controller.read_thread("tab-1", "thread-1")
        self.fake.subscribers = (("feishu", "chat-1"),)
        self.fake.loaded_thread_ids = ["thread-1"]
        self.controller.close_thread("tab-2", "thread-1")
        self.assertEqual(self.fake.unsubscribed, [])
        self.assertEqual(self.fake.subscribers, (("feishu", "chat-1"),))
        self.assertEqual(self.current_ids(), [])
        row = self.controller.list_threads(scope="global")["threads"][0]
        self.assertEqual(row["loaded_instance"], "default")
        self.assertFalse(row["action_capabilities"]["close"])

    def test_close_rejects_active_unknown_status_pending_interaction_and_uncertain_effect(self):
        self.controller.read_thread("tab-1", "thread-1")
        for status in ("active", "systemError", "future-status"):
            self.fake.status = status
            with self.assertRaises(WebRuntimeError):
                self.controller.close_thread("tab-2", "thread-1")
        self.fake.status = "idle"
        self.external_pending_roots.add("thread-1")
        with self.assertRaises(WebRuntimeError):
            self.controller.close_thread("tab-2", "thread-1")
        self.external_pending_roots.clear()
        self.controller._runtime_interest.mark_unknown("thread-1")
        with self.assertRaises(WebRuntimeError):
            self.controller.close_thread("tab-2", "thread-1")
        self.assertEqual(self.current_ids(), ["thread-1"])
        self.assertEqual(self.fake.unsubscribed, [])

    def test_close_rejects_unreconciled_prompt_receipt(self):
        self.controller.read_thread("tab-1", "thread-1")
        with patch.object(self.controller._prompt_submissions, "has_prompt_result_reconciliation", return_value=True):
            with self.assertRaises(WebRuntimeError) as caught:
                self.controller.close_thread("tab-2", "thread-1")
        self.assertEqual(caught.exception.code, "thread_close_blocked")
        self.assertEqual(self.current_ids(), ["thread-1"])

    def test_close_supersedes_inflight_open_even_when_newer_explicit_reopen_succeeds(self):
        self.controller.read_thread("tab-1", "thread-1")
        owner = self.controller._thread_open
        prepared = owner.prepare_read_thread("tab-1", "thread-1")
        observed = owner.execute_read_thread_observation(prepared)
        self.controller.close_thread("tab-2", "thread-1")
        self.controller.read_thread("tab-2", "thread-1")
        with self.assertRaises(WebRuntimeError) as caught:
            owner.prepare_read_thread_effect(prepared, observed)
        self.assertEqual(caught.exception.code, "thread_not_open")
        self.assertEqual(self.profile_store.load("tab-1").selected_thread_id, "")
        self.assertEqual(self.current_ids(), ["thread-1"])

    def test_known_resume_after_close_is_settled_without_reopening(self):
        self.profile_store.update("tab-1", selected_thread_id="", working_dir=self.fake.cwd)
        owner = self.controller._thread_open
        prepared = owner.prepare_read_thread("tab-1", "thread-1")
        observed = owner.execute_read_thread_observation(prepared)
        effect_preparation = owner.prepare_read_thread_effect(prepared, observed)
        effect = owner.execute_read_thread_effect(effect_preparation)
        self.controller.close_thread("tab-2", "thread-1")
        with self.assertRaises(WebRuntimeError):
            owner.finish_read_thread_effect(effect_preparation, effect)
        self.assertEqual(self.current_ids(), [])
        self.assertFalse(self.controller._runtime_interest.is_browser_open("thread-1"))
        self.assertEqual(self.profile_store.load("tab-1").selected_thread_id, "")
        self.assertEqual(self.fake.unsubscribed, ["thread-1"])

    def test_backend_reset_clears_open_set_without_resuming_or_cleanup_io(self):
        self.controller.read_thread("tab-1", "thread-1")
        self.fake.extra_summaries.append(replace(self.fake.summary(), thread_id="thread-2"))
        self.controller.read_thread("tab-2", "thread-2")
        with patch.object(self.fake, "read_thread") as read, patch.object(self.fake, "resume_thread_page") as resume:
            self.controller.retire_backend_epoch_after_stop()
        read.assert_not_called()
        resume.assert_not_called()
        self.assertEqual(self.current_ids(), [])
        self.assertEqual(self.fake.unsubscribed, [])
        for client in ("tab-1", "tab-2"):
            self.assertEqual(self.profile_store.load(client).selected_thread_id, "")

    def test_passive_restore_of_pre_restart_profile_cannot_open(self):
        self.profile_store.update("tab-1", selected_thread_id="thread-1", working_dir=self.fake.cwd)
        with self.assertRaises(WebRuntimeError):
            self.controller.prepare_read_thread("tab-1", "thread-1", open_in_browser=False)
        self.assertEqual(self.current_ids(), [])
        self.assertEqual(self.profile_store.load("tab-1").selected_thread_id, "")
