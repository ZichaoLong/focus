from dataclasses import replace
from unittest.mock import Mock

from bot.adapters.base import ThreadSnapshot
from bot.web_runtime.contract import WebRuntimeError
from tests.web_runtime.harness import WebRuntimeControllerHarness


class WebThreadForkTests(WebRuntimeControllerHarness):
    def test_fork_creates_persistent_session_without_prompt_or_parent_selection_change(self):
        self.controller.meta("tab-1")
        original = self.profile_store.load("tab-1")
        branch = replace(self.fake.summary(), thread_id="fork-1", ephemeral=False)
        def fork(thread_id):
            self.assertEqual(thread_id, "thread-1")
            self.fake.extra_summaries.append(branch)
            return ThreadSnapshot(summary=branch, turns=[], effective_model="model-a", effective_approval_policy="never", effective_permissions_profile_id=":workspace")
        self.fake.fork_thread = Mock(side_effect=fork)
        result = self.controller.fork_thread("tab-1", "thread-1")
        self.assertEqual(result, {"accepted": True, "thread_id": "fork-1", "source_thread_id": "thread-1"})
        self.assertEqual(self.fake.started, [])
        self.assertEqual(self.profile_store.load("tab-1"), original)
        self.assertIsNone(self.store.load("thread-1"))
        self.assertIsNone(self.store.load("fork-1"))
        listing = self.controller.list_threads(client_id="tab-1", scope="global")
        self.assertIn("fork-1", [t["id"] for t in listing["threads"]])

    def test_fork_unknown_is_not_retried_or_used_as_a_parent_mutation_fence(self):
        self.fake.fork_thread = Mock(side_effect=TimeoutError("response lost"))
        with self.assertRaises(WebRuntimeError) as caught:
            self.controller.fork_thread("tab-1", "thread-1")
        self.assertEqual(caught.exception.code, "thread_fork_unknown")
        self.fake.fork_thread.assert_called_once_with("thread-1")
        self.assertIsNone(self.store.load("thread-1"))
        self.assertEqual(self.fake.started, [])

    def test_ephemeral_is_hidden_and_cannot_be_opened_or_forked_by_web(self):
        side = replace(self.fake.summary(), thread_id="side-1", ephemeral=True)
        self.fake.extra_summaries.append(side)
        self.fake.fork_thread = Mock()
        for scope in ("current", "global"):
            listing = self.controller.list_threads(client_id="tab-1", scope=scope)
            self.assertNotIn("side-1", [t["id"] for t in listing["threads"]])
        for action in (self.controller.read_thread, self.controller.fork_thread):
            with self.assertRaises(WebRuntimeError) as caught:
                action("tab-1", "side-1")
            self.assertEqual(caught.exception.code, "ephemeral_thread_unavailable")
        self.fake.fork_thread.assert_not_called()
