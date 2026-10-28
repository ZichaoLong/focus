import unittest
from unittest.mock import Mock

from bot.adapters.codex_app_server import CodexAppServerAdapter, CodexAppServerConfig


class CodexThreadForkTests(unittest.TestCase):
    def test_persistent_fork_keeps_native_history_mode_and_does_not_override_permissions(self):
        for mode in ("legacy", "paginated"):
            with self.subTest(mode=mode):
                adapter = CodexAppServerAdapter(CodexAppServerConfig())
                adapter._rpc = Mock()
                adapter._rpc.request.return_value = {
                    "thread": {"id": "fork", "cwd": "/repo", "source": "cli", "historyMode": mode, "ephemeral": False},
                    "model": "model-a", "reasoningEffort": None, "approvalPolicy": "on-request", "approvalsReviewer": "user",
                    "activePermissionProfile": {"id": ":read-only"},
                }
                snapshot = adapter.fork_thread("parent")
                self.assertEqual(snapshot.summary.thread_id, "fork")
                self.assertEqual(snapshot.history_mode, mode)
                self.assertEqual(adapter._rpc.request.call_args.args, (
                    "thread/fork", {"threadId": "parent", "ephemeral": False, "excludeTurns": True},
                ))
                self.assertEqual(snapshot.effective_permissions_profile_id, ":read-only")

    def test_fork_rejects_a_parent_or_ephemeral_response(self):
        for thread in ({"id": "parent", "ephemeral": False}, {"id": "fork", "ephemeral": True}):
            adapter = CodexAppServerAdapter(CodexAppServerConfig())
            adapter._rpc = Mock()
            adapter._rpc.request.return_value = {"model": "model-a", "reasoningEffort": None, "thread": {"source": "cli", "historyMode": "legacy", **thread}}
            with self.assertRaises(ValueError):
                adapter.fork_thread("parent")

    def test_history_boundary_is_version_and_connection_pinned_without_goal_continuation(self):
        for version in ("0.164.0", "0.165.0"):
            adapter = CodexAppServerAdapter(CodexAppServerConfig())
            adapter._rpc = Mock()
            adapter._rpc.current_initialize_result.return_value = (7, {"userAgent": f"focus/{version} (Linux; x86_64)"})
            adapter._rpc_request = Mock(return_value={
                "thread": {"id":"branch", "source":"cli", "historyMode":"paginated", "ephemeral":False},
                "model":"m", "reasoningEffort":None,
            })
            adapter.fork_thread("parent", before_turn_id="real-first-turn", expected_connection_generation=7)
            adapter._rpc_request.assert_called_once_with("thread/fork", {
                "threadId":"parent", "ephemeral":False, "excludeTurns":True,
                "beforeTurnId":"real-first-turn", "deferGoalContinuation":False,
            }, expected_connection_generation=7, require_existing_connection=True, admit_existing_connection=True)

    def test_history_boundary_never_falls_back_on_unknown_version_or_connection(self):
        from bot.codex_protocol.client import CodexRpcPreSendError
        for identity in (None, (7,{"userAgent":"focus/0.147.0"}), (7,{"userAgent":"focus/0.166.0"}),
                         (8,{"userAgent":"focus/0.164.0"})):
            adapter = CodexAppServerAdapter(CodexAppServerConfig())
            adapter._rpc = Mock()
            adapter._rpc.current_initialize_result.return_value = identity
            adapter._rpc_request = Mock()
            with self.assertRaises(CodexRpcPreSendError):
                adapter.fork_thread("parent", before_turn_id="turn", expected_connection_generation=7)
            adapter._rpc_request.assert_not_called()
