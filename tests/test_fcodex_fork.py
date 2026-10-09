"""Native fork/side admission, creation, and independent runtime ownership."""
from tests.fcodex_operation_harness import FcodexOperationHarness


class FcodexForkTests(FcodexOperationHarness):
    def test_persistent_and_ephemeral_forks_register_independent_roots(self):
        self._connect()
        for request_id, ephemeral in enumerate((False, True), 1):
            with self.subTest(ephemeral=ephemeral):
                admitted = self._admit(
                    request_id=request_id, method="thread/fork",
                    request_params={"threadId": "root-1", "ephemeral": ephemeral,
                                    "developerInstructions": "native instructions"},
                )
                self.assertTrue(admitted["allowed"])
                fork_id = f"fork-{request_id}"
                result = self._client_response(
                    request_id=request_id, outcome="success",
                    observed_thread_id=fork_id, observed_root_thread_id=fork_id,
                )
                self.assertTrue(result["settled"])
                source = self.participant_runtime.source_snapshot(self.participant_id, fork_id)
                self.assertEqual(source.connection_ids, ("connection-a",))
                self.assertIsNone(self.interaction_leases.load(fork_id))
                for offset, method in enumerate(("thread/inject_items", "turn/start", "turn/interrupt", "thread/unsubscribe"), 10):
                    decision = self._admit(
                        request_id=request_id * 100 + offset, method=method, thread_id=fork_id,
                        request_params={"threadId": fork_id, "turnId": ""} if method == "turn/interrupt" else {"threadId": fork_id},
                    )
                    self.assertTrue(decision["allowed"], decision)
                self.assertIsNone(self.interaction_leases.load("root-1"))

    def test_path_override_and_unproven_source_are_rejected(self):
        self._connect()
        for params in ({"threadId": "root-1", "path": "/other/thread"}, {"threadId": "different"}):
            self.assertFalse(self._admit(method="thread/fork", request_params=params)["allowed"])
        self.assertFalse(self._admit(method="thread/fork", thread_id="", request_params={})["allowed"])

    def test_fork_connection_loss_does_not_retry_or_hold_parent_writer(self):
        self._connect()
        self.assertTrue(self._admit(method="thread/fork", request_params={"threadId": "root-1"})["allowed"])
        self.coordinator.participant_disconnected(self.participant_id, "connection-a")
        self.assertEqual(self.operation_service._client_requests, {})
        self.assertIsNone(self.interaction_leases.load("root-1"))

    def test_success_cannot_register_the_parent_as_the_created_branch(self):
        self._connect()
        self.assertTrue(self._admit(method="thread/fork", request_params={"threadId": "root-1"})["allowed"])
        result = self._client_response(
            request_id=1, outcome="success", observed_thread_id="root-1", observed_root_thread_id="root-1",
        )
        self.assertTrue(result["settled"])
        self.assertTrue(result["retained"])
        self.assertEqual(self.participant_runtime.source_snapshot(self.participant_id, "root-1").connection_ids, ())
