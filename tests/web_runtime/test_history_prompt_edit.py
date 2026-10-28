"""Exact upstream boundaries and lossless draft admission for Web history edits."""
from dataclasses import replace
from unittest.mock import Mock

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage, ThreadSnapshot
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
        self.fake.fork_thread = Mock(return_value=ThreadSnapshot(summary=replace(self.fake.summary(), thread_id="branch"), effective_model="model-a", effective_approval_policy="never", effective_permissions_profile_id=":workspace"))
        self.fake.rename_thread = Mock()
        return text

    def test_first_earlier_and_inherited_ids_use_native_boundary_and_full_original(self):
        for turn_id in ("turn-first", "turn-older-83", "inherited-turn-2"):
            with self.subTest(turn_id=turn_id):
                text = self.prepare_edit(turn_id)
                source = list(self.fake.turns)
                result = self.controller.fork_thread("tab-1", "thread-1", turn_id=turn_id, item_id="prompt-original")
                self.fake.fork_thread.assert_called_once_with(
                    "thread-1", before_turn_id=turn_id, expected_connection_generation=1,
                )
                self.assertEqual(result["edit_prompt"], {"turn_id": turn_id, "item_id": "prompt-original", "text": text})
                self.assertEqual(self.fake.turns, source)
                self.assertEqual(self.fake.started, [])
                self.assertEqual(self.fake.resumed, [])

    def test_supplement_and_attachments_are_rejected_before_creation(self):
        for item_id, content in (
            ("supplement", [{"type": "text", "text": "first"}]),
            ("prompt-original", [{"type": "text", "text": "look"}, {"type": "image", "url": "data:image/png;base64,AA=="}]),
            ("prompt-original", [{"type": "text", "text": "@file", "text_elements": [{"byteRange": {"start": 0, "end": 5}}]}]),
            ("prompt-original", [{"type": "mention", "path": "/file", "name": "file"}]),
        ):
            with self.subTest(item_id=item_id, content=content):
                self.prepare_edit(content=content)
                with self.assertRaises(WebRuntimeError) as caught:
                    self.controller.fork_thread("tab-1", "thread-1", turn_id="turn-first", item_id=item_id)
                self.assertEqual(caught.exception.code, "history_edit_unsupported")
                self.fake.fork_thread.assert_not_called()

    def test_pagination_locates_first_user_item_and_rejects_mismatched_identity(self):
        self.prepare_edit()
        target = self.fake.list_thread_items.return_value
        self.fake.list_thread_items.side_effect = [ThreadItemsPage(next_cursor="next"), target]
        self.controller.fork_thread("tab-1", "thread-1", turn_id="turn-first", item_id="prompt-original")
        self.assertEqual(self.fake.list_thread_items.call_count, 2)
        self.assertEqual(self.fake.list_thread_items.call_args.kwargs["cursor"], "next")
        self.prepare_edit("different-turn")
        with self.assertRaises(WebRuntimeError):
            self.controller.fork_thread("tab-1", "thread-1", turn_id="turn-first", item_id="prompt-original")
        self.fake.fork_thread.assert_not_called()

    def test_unknown_creation_never_repeats_and_keeps_source(self):
        self.prepare_edit()
        self.fake.fork_thread.side_effect = TimeoutError("response lost")
        with self.assertRaises(WebRuntimeError) as caught:
            self.controller.fork_thread("tab-1", "thread-1", turn_id="turn-first", item_id="prompt-original")
        self.assertEqual(caught.exception.code, "thread_fork_unknown")
        self.fake.fork_thread.assert_called_once()
        self.assertEqual(self.fake.started, [])

    def test_read_failure_is_explicitly_before_creation(self):
        self.prepare_edit()
        self.fake.list_thread_items.side_effect = TimeoutError("disconnected during read")
        with self.assertRaises(WebRuntimeError) as caught:
            self.controller.fork_thread("tab-1", "thread-1", turn_id="turn-first", item_id="prompt-original")
        self.assertEqual(caught.exception.code, "history_edit_unavailable")
        self.assertIn("未创建分支", str(caught.exception))
        self.fake.fork_thread.assert_not_called()

    def test_nonadvancing_history_page_is_not_retried_or_forked(self):
        self.prepare_edit()
        self.fake.list_thread_items.return_value = ThreadItemsPage(next_cursor="same-cursor")
        with self.assertRaises(WebRuntimeError):
            self.controller.fork_thread("tab-1", "thread-1", turn_id="turn-first", item_id="prompt-original")
        self.assertEqual(self.fake.list_thread_items.call_count, 2)
        self.fake.fork_thread.assert_not_called()

    def test_legacy_and_missing_targets_do_not_create(self):
        self.prepare_edit()
        self.fake.history_mode = "legacy"
        with self.assertRaises(WebRuntimeError):
            self.controller.fork_thread("tab-1", "thread-1", turn_id="turn-first", item_id="prompt-original")
        self.fake.fork_thread.assert_not_called()
        self.fake.history_mode = "paginated"
        self.fake.list_thread_items.return_value = ThreadItemsPage()
        with self.assertRaises(WebRuntimeError):
            self.controller.fork_thread("tab-1", "thread-1", turn_id="missing", item_id="missing")
        self.fake.fork_thread.assert_not_called()

    def test_native_reverted_notification_discards_history_and_invalidates_browser(self):
        self.controller.read_thread("tab-1", "thread-1")
        self.controller.handle_notification("thread/reverted", {"threadId": "thread-1"})
        self.assertEqual(list(self.controller._thread_read_model.turns("thread-1")), [])
        self.assertTrue(any(event.get("type") == "thread_invalidated" and event.get("reason") == "thread/reverted" for event in self.events))
