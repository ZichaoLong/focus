"""Native revert stays on the requested thread and never falls back to a fork."""
import unittest
from unittest.mock import Mock

from bot.adapters.codex_app_server import CodexAppServerAdapter, CodexAppServerConfig
from bot.codex_protocol.client import CodexRpcError, CodexRpcProtocolError


class CodexThreadRevertTests(unittest.TestCase):
    def adapter(self, thread_id="parent", mode="paginated"):
        adapter = CodexAppServerAdapter(CodexAppServerConfig())
        adapter._rpc_request = Mock(return_value={
            "thread": {"id": thread_id, "source": "cli", "historyMode": mode, "ephemeral": False},
            "turnsBackwardsCursor": None, "itemsBackwardsCursor": None,
        })
        return adapter

    def test_uses_native_parameters_and_same_connection_without_config_overrides(self):
        adapter = self.adapter()
        adapter.revert_thread("parent", before_turn_id="original-turn", expected_connection_generation=7)
        adapter._rpc_request.assert_called_once_with(
            "thread/revert", {"threadId": "parent", "beforeTurnId": "original-turn"},
            expected_connection_generation=7, require_existing_connection=True,
            admit_existing_connection=True,
        )

    def test_rejects_wrong_thread_or_history_mode_as_uncertain_response(self):
        for thread_id, mode in (("branch", "paginated"), ("parent", "legacy")):
            with self.subTest(thread_id=thread_id, mode=mode):
                adapter = self.adapter(thread_id, mode)
                with self.assertRaises(CodexRpcProtocolError):
                    adapter.revert_thread("parent", before_turn_id="turn", expected_connection_generation=7)
                adapter._rpc_request.assert_called_once()

    def test_unsupported_method_is_not_replaced_with_another_operation(self):
        adapter = self.adapter()
        error = CodexRpcError("thread/revert", {"code": -32601, "message": "unsupported"})
        adapter._rpc_request.side_effect = error
        with self.assertRaises(CodexRpcError) as caught:
            adapter.revert_thread("parent", before_turn_id="turn", expected_connection_generation=7)
        self.assertIs(caught.exception, error)
        adapter._rpc_request.assert_called_once()
