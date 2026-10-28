"""Native history edits prepare the original before one same-thread mutation."""
from unittest.mock import Mock

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage
from bot.codex_protocol.client import CodexRpcError
from bot.stores.interaction_lease_store import make_fcodex_interaction_holder
from bot.web_runtime.contract import WebRuntimeError
from tests.web_runtime.harness import WebRuntimeControllerHarness


class WebHistoryPromptEditTests(WebRuntimeControllerHarness):
    def prepare_edit(self, turn_id="turn-first", item_id="prompt-original", content=None):
        self.fake.history_mode = "paginated"
        text = "  original\n" + "完整原文" * 3000
        content = content if content is not None else [{"type": "text", "text": text, "text_elements": []}]
        self.fake.list_thread_items = Mock(return_value=ThreadItemsPage(items=[
            ThreadItemEntry(turn_id=turn_id, item={"type": "userMessage", "id": item_id, "content": content}),
        ]))
        self.fake.revert_thread = Mock()
        self.fake.fork_thread = Mock()
        self.fake.rename_thread = Mock()
        return text

    def read_prompt(self, turn_id="turn-first", item_id="prompt-original"):
        return self.controller.history_edit_prompt("tab-1", "thread-1", turn_id=turn_id, item_id=item_id)

    def revert(self, turn_id="turn-first"):
        return self.controller.revert_thread("tab-1", "thread-1", turn_id=turn_id)

    def test_first_earlier_and_inherited_ids_prepare_full_original_without_mutating(self):
        for turn_id in ("turn-first", "turn-older-83", "inherited-turn-2"):
            with self.subTest(turn_id=turn_id):
                text = self.prepare_edit(turn_id)
                original = self.read_prompt(turn_id)
                self.assertEqual(original, {"thread_id": "thread-1", "turn_id": turn_id,
                                            "item_id": "prompt-original", "text": text})
                self.fake.revert_thread.assert_not_called()
                self.fake.fork_thread.assert_not_called()
                self.assertEqual(self.fake.started, [])

    def test_revert_keeps_the_thread_without_fork_rename_or_prompt_submission(self):
        self.prepare_edit()
        result = self.revert()
        self.assertEqual(result, {"accepted": True, "thread_id": "thread-1"})
        self.fake.revert_thread.assert_called_once_with(
            "thread-1", before_turn_id="turn-first", expected_connection_generation=1,
        )
        self.fake.fork_thread.assert_not_called()
        self.fake.rename_thread.assert_not_called()
        self.assertEqual(self.fake.started, [])
        self.assertEqual(self.fake.resumed, [])
        self.assertTrue(any(event.get("reason") == "thread/reverted" for event in self.events))

    def test_supplement_and_attachments_are_rejected_before_preparation(self):
        for item_id, content in (
            ("supplement", [{"type": "text", "text": "first"}]),
            ("prompt-original", [{"type": "text", "text": "look"}, {"type": "image", "url": "data:image/png;base64,AA=="}]),
            ("prompt-original", [{"type": "text", "text": "@file", "text_elements": [{"byteRange": {"start": 0, "end": 5}}]}]),
            ("prompt-original", [{"type": "mention", "path": "/file", "name": "file"}]),
        ):
            with self.subTest(item_id=item_id, content=content):
                self.prepare_edit(content=content)
                with self.assertRaises(WebRuntimeError) as caught:
                    self.read_prompt(item_id=item_id)
                self.assertEqual(caught.exception.code, "history_edit_unsupported")
                self.fake.revert_thread.assert_not_called()

    def test_pagination_locates_first_user_item_and_rejects_mismatched_identity(self):
        self.prepare_edit()
        target = self.fake.list_thread_items.return_value
        self.fake.list_thread_items.side_effect = [ThreadItemsPage(next_cursor="next"), target]
        self.read_prompt()
        self.assertEqual(self.fake.list_thread_items.call_count, 2)
        self.assertEqual(self.fake.list_thread_items.call_args.kwargs["cursor"], "next")
        self.prepare_edit("different-turn")
        with self.assertRaises(WebRuntimeError):
            self.read_prompt()
        self.fake.revert_thread.assert_not_called()

    def test_unknown_revert_is_not_retried_and_blocks_another_control(self):
        self.prepare_edit()
        self.fake.revert_thread.side_effect = TimeoutError("response lost")
        with self.assertRaises(WebRuntimeError) as caught:
            self.revert()
        self.assertEqual(caught.exception.code, "mutation_unknown")
        self.assertEqual(caught.exception.details["operation"], "revert")
        with self.assertRaises(WebRuntimeError):
            self.revert()
        self.fake.revert_thread.assert_called_once()
        self.assertTrue(any(event.get("reason") == "web_thread_revert_unconfirmed" for event in self.events))

    def test_internal_revert_error_can_follow_a_committed_history_change(self):
        self.prepare_edit()
        self.fake.revert_thread.side_effect = CodexRpcError(
            "thread/revert", {"code": -32603, "message": "reload failed after commit"},
        )
        with self.assertRaises(WebRuntimeError) as caught:
            self.revert()
        self.assertEqual(caught.exception.code, "mutation_unknown")
        self.fake.revert_thread.assert_called_once()

    def test_native_validation_error_is_preserved_without_fork_fallback(self):
        self.prepare_edit()
        self.fake.revert_thread.side_effect = CodexRpcError(
            "thread/revert", {"code": -32600, "message": "turn disappeared"},
        )
        with self.assertRaises(CodexRpcError):
            self.revert()
        self.fake.fork_thread.assert_not_called()
        self.assertFalse(self.controller._operations.has_unknown_mutation("thread-1"))

    def test_foreign_exclusive_writer_blocks_revert(self):
        self.prepare_edit()
        self.store.acquire("thread-1", make_fcodex_interaction_holder("fcodex:12", owner_pid=0))
        with self.assertRaises(WebRuntimeError) as caught:
            self.revert()
        self.assertEqual(caught.exception.code, "interaction_owned")
        self.fake.revert_thread.assert_not_called()

    def test_read_failure_is_explicitly_before_history_mutation(self):
        self.prepare_edit()
        self.fake.list_thread_items.side_effect = TimeoutError("disconnected during read")
        with self.assertRaises(WebRuntimeError) as caught:
            self.read_prompt()
        self.assertEqual(caught.exception.code, "history_edit_unavailable")
        self.fake.revert_thread.assert_not_called()

    def test_nonadvancing_history_page_is_not_retried_or_reverted(self):
        self.prepare_edit()
        self.fake.list_thread_items.return_value = ThreadItemsPage(next_cursor="same-cursor")
        with self.assertRaises(WebRuntimeError):
            self.read_prompt()
        self.assertEqual(self.fake.list_thread_items.call_count, 2)
        self.fake.revert_thread.assert_not_called()

    def test_legacy_and_missing_targets_do_not_mutate(self):
        self.prepare_edit()
        self.fake.history_mode = "legacy"
        for operation in (self.read_prompt, self.revert):
            with self.assertRaises(WebRuntimeError):
                operation()
        self.fake.revert_thread.assert_not_called()
        self.fake.history_mode = "paginated"
        self.fake.list_thread_items.return_value = ThreadItemsPage()
        with self.assertRaises(WebRuntimeError):
            self.read_prompt("missing", "missing")
        self.fake.revert_thread.assert_not_called()

    def test_native_reverted_notification_discards_history_and_invalidates_browser(self):
        self.controller.read_thread("tab-1", "thread-1")
        self.controller.handle_notification("thread/reverted", {"threadId": "thread-1"})
        self.assertEqual(list(self.controller._thread_read_model.turns("thread-1")), [])
        self.assertTrue(any(event.get("type") == "thread_invalidated" and event.get("reason") == "thread/reverted" for event in self.events))
