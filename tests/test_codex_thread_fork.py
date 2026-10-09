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
