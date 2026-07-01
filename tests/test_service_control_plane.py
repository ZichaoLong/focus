import pathlib
import tempfile
import unittest
from unittest.mock import patch

from bot.service_control_plane import ServiceControlResponseTimeoutError, control_request
from bot.stores.service_instance_lease import ServiceInstanceLease


class ServiceControlPlaneTests(unittest.TestCase):
    def test_control_request_distinguishes_response_timeout_after_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = pathlib.Path(tmpdir)
            lease = ServiceInstanceLease(data_dir)
            lease.acquire(control_endpoint="tcp://127.0.0.1:32001")
            sent_payloads: list[bytes] = []

            class _FakeSocket:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def settimeout(self, timeout_seconds: float) -> None:
                    self.timeout_seconds = timeout_seconds

                def sendall(self, payload: bytes) -> None:
                    sent_payloads.append(payload)

                def recv(self, size: int) -> bytes:
                    raise TimeoutError("timed out")

            try:
                with patch("bot.service_control_plane.socket.create_connection", return_value=_FakeSocket()):
                    with self.assertRaises(ServiceControlResponseTimeoutError):
                        control_request(data_dir, "service/attach", timeout_seconds=0.1)
            finally:
                lease.release()

            self.assertEqual(len(sent_payloads), 1)


if __name__ == "__main__":
    unittest.main()
