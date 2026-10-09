import json
from unittest.mock import patch

import pytest

from bot.fcodex.proxy import _ProxyInteractionGate


class Socket:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        pass


@pytest.fixture
def connection(tmp_path):
    calls = []

    def control(_data_dir, method, params):
        calls.append((method, params))
        return {"allowed": True, "tracks_response": False, "request_token": None}

    gate = _ProxyInteractionGate(
        cwd="/project", data_dir=tmp_path, control_request_fn=control
    )
    client, backend = Socket(), Socket()
    yield gate, client, backend, calls
    gate.close()


@pytest.mark.parametrize(
    "edits",
    [
        [
            {
                "keyPath": 'projects."C:\\\\work\\\\project".trust_level',
                "value": "trusted",
                "mergeStrategy": "replace",
            }
        ],
        [
            {"keyPath": "model", "value": "gpt-6", "mergeStrategy": "replace"},
            {
                "keyPath": "model_reasoning_effort",
                "value": "high",
                "mergeStrategy": "replace",
            },
        ],
        [],  # Native TUI also uses an empty batch to request a config reload.
    ],
)
@pytest.mark.parametrize("failed", [False, True])
def test_native_config_write_preserves_params_and_upstream_result(
    connection, tmp_path, edits, failed
):
    gate, client, backend, calls = connection
    params = {
        "edits": edits,
        "filePath": None,
        "expectedVersion": "v1",
        "reloadUserConfig": True,
    }
    request = {"id": "config-1", "method": "config/batchWrite", "params": params}
    gate.handle_client_message(
        json.dumps(request), client_ws=client, backend_ws=backend
    )
    assert backend.sent == [request]
    assert client.sent == []
    assert calls[-1][0] == "operation/admit"
    assert calls[-1][1]["thread_id"] == ""
    response = {
        "id": "config-1",
        **(
            {
                "error": {
                    "code": -32600,
                    "message": "Configuration was modified since last read",
                    "data": {"private": "not a diagnostic field"},
                }
            }
            if failed
            else {
                "result": {
                    "status": "ok",
                    "version": "v2",
                    "filePath": "/codex/config.toml",
                }
            }
        ),
    }
    gate.handle_backend_message(
        json.dumps(response), client_ws=client, backend_ws=backend
    )
    assert client.sent == [response]
    assert len(backend.sent) == 1  # Errors never retry a configuration mutation.
    assert not any(method == "operation/client-response" for method, _ in calls)
    if failed:
        record = json.loads((tmp_path / "fcodex.log").read_text(encoding="utf-8"))
        assert record["method"] == "config/batchWrite"
        assert record["stage"] == "upstream_error"
        assert "private" not in record
        assert "not a diagnostic field" not in str(record)
        assert "edits" not in record


def test_config_write_respects_backend_reset_fence(connection):
    gate, client, backend, _ = connection
    with patch.object(
        gate, "_control", side_effect=RuntimeError("backend reset fenced")
    ):
        gate.handle_client_message(
            json.dumps(
                {"id": 1, "method": "config/batchWrite", "params": {"edits": []}}
            ),
            client_ws=client,
            backend_ws=backend,
        )
    assert backend.sent == []
    assert "fenced" in client.sent[0]["error"]["message"]


def test_diagnostic_failure_does_not_mask_original_rejection(connection):
    gate, client, backend, _ = connection
    with patch("bot.fcodex.diagnostics.append_log", side_effect=OSError("disk full")):
        gate.handle_client_message(
            json.dumps({"id": 1, "method": "unknown/method", "params": {}}),
            client_ws=client,
            backend_ws=backend,
        )
    assert backend.sent == []
    assert "unknown/method" in client.sent[0]["error"]["message"]


def test_local_rejection_records_method_without_prompt_body(connection, tmp_path):
    gate, client, backend, _ = connection
    gate.handle_client_message(
        json.dumps(
            {"id": 1, "method": "turn/steer", "params": {"input": "private prompt"}}
        ),
        client_ws=client,
        backend_ws=backend,
    )
    record = json.loads((tmp_path / "fcodex.log").read_text(encoding="utf-8"))
    assert record["stage"] == "local_rejection"
    assert record["method"] == "turn/steer"
    assert "private prompt" not in str(record)
