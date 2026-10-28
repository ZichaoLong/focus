"""Native revert stays on the admitted thread and uses the existing owner."""
from bot.fcodex.proxy import _PendingClientRequest, _classify_coordinated_client_response
from bot.stores.interaction_lease_store import make_web_interaction_holder
from tests.fcodex_operation_harness import FcodexOperationHarness


class FcodexHistoryEditTests(FcodexOperationHarness):
    def attach(self):
        self._connect()
        admitted = self._admit(method="thread/resume", request_id=20)
        self.assertTrue(admitted["allowed"])
        self._client_response(request_id=20, outcome="success")

    def test_exact_native_revert_is_tracked_without_creating_a_branch_or_writer(self):
        self.attach()
        admitted = self._admit(method="thread/revert", request_params={"threadId": "root-1", "beforeTurnId": "turn-real"})
        self.assertTrue(admitted["allowed"])
        self.assertTrue(admitted["tracks_response"])
        settled = self._client_response(request_id=1, outcome="success", observed_thread_id="root-1", observed_root_thread_id="root-1")
        self.assertTrue(settled["settled"])
        self.assertFalse(settled["outcome_unknown"])
        self.assertIsNone(self.interaction_leases.load("root-1"))

    def test_unattached_or_malformed_revert_is_never_forwarded(self):
        self._connect()
        self.assertFalse(self._admit(method="thread/revert", request_params={"threadId": "root-1", "beforeTurnId": "t"})["allowed"])
        self.attach()
        for params in ({"threadId":"root-1"}, {"threadId":"other","beforeTurnId":"t"},
                       {"threadId":"root-1","beforeTurnId":" t"}, {"threadId":"root-1","beforeTurnId":"t","path":"/other"}):
            with self.subTest(params=params):
                self.assertFalse(self._admit(method="thread/revert", request_params=params)["allowed"])

    def test_foreign_exclusive_owner_still_blocks_revert(self):
        self.attach()
        self.interaction_leases.force_acquire("root-1", make_web_interaction_holder("tab-other", owner_pid=__import__("os").getpid()))
        self.assertFalse(self._admit(method="thread/revert", request_params={"threadId":"root-1","beforeTurnId":"t"})["allowed"])

    def test_wrong_success_identity_and_transport_loss_remain_unknown(self):
        self.attach()
        for rid, outcome, observed in ((1, "success", "different-root"), (2, "unknown", "")):
            admitted = self._admit(request_id=rid, method="thread/revert", request_params={"threadId":"root-1","beforeTurnId":"t"})
            self.assertTrue(admitted["allowed"])
            result = self._client_response(request_id=rid, outcome=outcome, observed_thread_id=observed, observed_root_thread_id=observed)
            self.assertTrue(result["outcome_unknown"])


def test_native_revert_internal_error_can_follow_commit():
    request = _PendingClientRequest(request_id=1, request_token=1, method="thread/revert", thread_id="root-1")
    for code, outcome in ((-32600,"error"),(-32601,"error"),(-32602,"error"),(-32603,"unknown")):
        assert _classify_coordinated_client_response({"id":1,"error":{"code":code,"message":"failure"}},request) == (outcome,None)
    assert _classify_coordinated_client_response({"id":1,"result":{"thread":{"id":"different"}}},request) is None
