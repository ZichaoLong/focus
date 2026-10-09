import json
import tempfile
import unittest
from pathlib import Path

from bot.fcodex.proxy import _RESOLVED_SERVER_REQUEST_RECEIPT_LIMIT
from bot.jsonrpc_id import jsonrpc_id_key
from tests import test_fcodex_proxy_operation_receipts as _operation_receipts


class ProxyServerRequestResolutionTests(unittest.TestCase):
    """Resolved receipt and exact retry coverage for the proxy wire owner."""

    _FakeWs = _operation_receipts.ProxyInteractionGateTests._FakeWs
    _FakeOperationControl = (
        _operation_receipts.ProxyInteractionGateTests._FakeOperationControl
    )
    _decode_payload = staticmethod(
        _operation_receipts.ProxyInteractionGateTests._decode_payload
    )
    _gate = _operation_receipts.ProxyInteractionGateTests._gate
    _request = staticmethod(_operation_receipts.ProxyInteractionGateTests._request)

    def test_known_not_sent_response_reprojects_the_exact_server_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            control = self._FakeOperationControl()
            control.response_submission = {
                "allowed": False,
                "response_disposition": "not_sent",
            }
            gate = self._gate(Path(tmpdir), control)
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()
            request = self._request(
                7,
                "item/permissions/requestApproval",
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "permissions": {"network": {"enabled": True}},
                },
            )
            gate.handle_backend_message(
                request,
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 7,
                        "result": {
                            "permissions": {"network": {"enabled": True}},
                            "scope": "session",
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            self.assertEqual(len(client_ws.sent), 2)
            self.assertEqual(
                self._decode_payload(client_ws.sent[-1]),
                self._decode_payload(request),
            )
            self.assertIn(jsonrpc_id_key(7), gate._pending_server_request_ids)
            self.assertFalse(client_ws.closed)
            self.assertFalse(backend_ws.closed)

    def test_resolved_first_silently_retires_a_late_tui_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            control = self._FakeOperationControl()
            gate = self._gate(Path(tmpdir), control)
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()
            gate.handle_backend_message(
                self._request(
                    "req-1",
                    "item/commandExecution/requestApproval",
                    {
                        "threadId": "thread-1",
                        "turnId": "turn-1",
                        "command": "ls",
                    },
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "serverRequest/resolved",
                        "params": {
                            "requestId": "req-1",
                            "threadId": "thread-1",
                        },
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            gate.handle_client_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "req-1",
                        "result": {"decision": "accept"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            self.assertEqual(
                control.calls_for("operation/request-response-submit"),
                [],
            )
            self.assertFalse(client_ws.closed)
            self.assertFalse(backend_ws.closed)

    def test_resolved_receipt_preserves_jsonrpc_id_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            control = self._FakeOperationControl()
            gate = self._gate(Path(tmpdir), control)
            client_ws = self._FakeWs()
            backend_ws = self._FakeWs()
            gate.handle_backend_message(
                self._request(
                    1,
                    "item/commandExecution/requestApproval",
                    {"threadId": "thread-1", "turnId": "turn-1"},
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )
            gate.handle_backend_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "serverRequest/resolved",
                        "params": {"requestId": 1, "threadId": "thread-1"},
                    }
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            gate.handle_backend_message(
                self._request(
                    "1",
                    "item/commandExecution/requestApproval",
                    {"threadId": "thread-1", "turnId": "turn-1"},
                ),
                client_ws=client_ws,
                backend_ws=backend_ws,
            )

            self.assertIn(jsonrpc_id_key(1), gate._resolved_server_request_ids)
            self.assertIn(jsonrpc_id_key("1"), gate._pending_server_request_ids)
            self.assertFalse(client_ws.closed)
            self.assertFalse(backend_ws.closed)

    def test_resolved_receipts_are_bounded_and_cleared_with_the_wire(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            gate = self._gate(Path(tmpdir), self._FakeOperationControl())
            with gate._lock:
                for request_id in range(
                    _RESOLVED_SERVER_REQUEST_RECEIPT_LIMIT + 1
                ):
                    gate._remember_resolved_server_request_locked(
                        jsonrpc_id_key(request_id)
                    )

            self.assertEqual(
                len(gate._resolved_server_request_ids),
                _RESOLVED_SERVER_REQUEST_RECEIPT_LIMIT,
            )
            self.assertNotIn(
                jsonrpc_id_key(0),
                gate._resolved_server_request_ids,
            )
            gate.close()
            self.assertEqual(gate._resolved_server_request_ids, {})


if __name__ == "__main__":
    unittest.main()
    def test_delegated_response_uses_original_socket_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            control = self._FakeOperationControl()
            control.response_submission = {"allowed": True, "response_disposition": "proxy_send"}
            gate = self._gate(Path(tmpdir), control)
            client, backend = self._FakeWs(), self._FakeWs()
            gate.handle_backend_message(self._request(9, "item/tool/requestUserInput", {
                "threadId": "side-1", "turnId": "turn-1", "questions": [],
            }), client_ws=client, backend_ws=backend)
            response = {"id": 9, "result": {"answers": {"q": {"answers": ["yes"]}}}}
            gate.handle_client_message(json.dumps(response), client_ws=client, backend_ws=backend)
            self.assertEqual(len(backend.sent), 1)
            self.assertEqual(self._decode_payload(backend.sent[0])["result"], response["result"])
            self.assertEqual(len(control.calls_for("operation/request-response-sent")), 1)
            gate.handle_client_message(json.dumps(response), client_ws=client, backend_ws=backend)
            self.assertEqual(len(backend.sent), 1)
            self.assertFalse(client.closed)

    def test_delegated_send_failure_reports_unknown_and_closes_wire(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            control = self._FakeOperationControl()
            control.response_submission = {"allowed": True, "response_disposition": "proxy_send"}
            gate = self._gate(Path(tmpdir), control)
            client, backend = self._FakeWs(), self._FakeWs()
            gate.handle_backend_message(self._request(9, "item/tool/requestUserInput", {
                "threadId": "side-1", "turnId": "turn-1", "questions": [],
            }), client_ws=client, backend_ws=backend)
            backend.close()
            gate.handle_client_message(json.dumps({"id": 9, "result": {"answers": {}}}), client_ws=client, backend_ws=backend)
            self.assertEqual(len(control.calls_for("operation/request-response-unknown")), 1)
            self.assertTrue(client.closed)

    def test_native_fork_payload_and_new_thread_response_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            control = self._FakeOperationControl()
            gate = self._gate(Path(tmpdir), control)
            client, backend = self._FakeWs(), self._FakeWs()
            params = {"threadId": "parent", "ephemeral": True, "developerInstructions": "native", "model": "model-x", "config": {"model_reasoning_effort": "high"}}
            gate.handle_client_message(self._request(1, "thread/fork", params), client_ws=client, backend_ws=backend)
            self.assertEqual(self._decode_payload(backend.sent[0])["params"], params)
            gate.handle_backend_message(json.dumps({"id": 1, "result": {"thread": {"id": "side", "ephemeral": True}}}), client_ws=client, backend_ws=backend)
            self.assertEqual(self._decode_payload(client.sent[-1])["result"]["thread"]["id"], "side")
            self.assertFalse(client.closed)
