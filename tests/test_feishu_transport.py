"""Exercise the pinned SDK loop with local HTTP/WS fakes, never Feishu."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from types import SimpleNamespace

import pytest

from bot.feishu_transport import FeishuTransport


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("transport did not reach expected state")
        time.sleep(0.01)


@pytest.fixture
def sdk_transport(monkeypatch):
    import lark_oapi.ws.client as sdk

    calls = []
    connections = []
    original_loop, original_requests = sdk.loop, sdk.requests
    fail_next_receive = threading.Event()
    release_receive = threading.Event()

    class Connection:
        closed = False

        async def recv(self):
            while not release_receive.is_set():
                await asyncio.sleep(0.01)
            if fail_next_receive.is_set():
                fail_next_receive.clear()
                release_receive.clear()
                raise ConnectionError("controlled disconnect")
            await asyncio.Future()

        async def send(self, payload):
            pass

        async def close(self):
            self.closed = True

    async def connect(url, **kwargs):
        calls.append(("connect", url, kwargs))
        connection = Connection()
        connections.append(connection)
        return connection

    def post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return SimpleNamespace(
            status_code=200,
            content=json.dumps(
                {
                    "code": 0,
                    "data": {
                        "URL": "wss://test.invalid/ws?device_id=test&service_id=1",
                        "ClientConfig": {
                            "ReconnectNonce": 0,
                            "ReconnectCount": -1,
                            "ReconnectInterval": 0,
                            "PingInterval": 60,
                        },
                    },
                }
            ).encode(),
        )

    requests = SimpleNamespace(post=post)
    monkeypatch.setattr(sdk, "requests", requests)
    ws = SimpleNamespace(connect=connect)
    monkeypatch.setattr(sdk, "websockets", ws)
    monkeypatch.setattr(sdk, "_focus_original_websockets", ws, raising=False)
    # configure_feishu_ws_proxy writes this module-local hook; restore it after the test.
    monkeypatch.setattr(sdk, "_ws_connect_kwargs", sdk._ws_connect_kwargs)
    transport = FeishuTransport(
        app_id="test",
        app_secret="test",
        event_handler=None,
        proxy_mode="disabled",
        timeout=0.2,
    )
    yield SimpleNamespace(
        transport=transport,
        sdk=sdk,
        calls=calls,
        connections=connections,
        fail=fail_next_receive,
        release=release_receive,
        requests=requests,
        original_loop=original_loop,
    )
    transport.stop()
    assert sdk.loop is original_loop
    assert sdk.requests is requests
    assert not any(
        t.name == "focus-feishu" and t.is_alive() for t in threading.enumerate()
    )
    assert original_requests is not None


def test_connected_stop_closes_socket_tasks_and_restores_sdk_globals(sdk_transport):
    fixture = sdk_transport
    fixture.transport.start()
    wait_for(lambda: fixture.transport.snapshot()["state"] == "connected")
    post = next(call for call in fixture.calls if call[0] == "post")
    assert post[2]["timeout"] == 0.2
    fixture.transport.stop()
    fixture.transport.stop()
    assert all(connection.closed for connection in fixture.connections)
    assert fixture.transport._loop.is_closed()
    assert fixture.transport.snapshot()["state"] == "stopped"


def test_disconnect_reconnect_and_stop_have_one_producer(sdk_transport):
    fixture = sdk_transport
    fixture.transport.start()
    wait_for(lambda: len(fixture.connections) == 1)
    fixture.fail.set()
    fixture.release.set()
    wait_for(lambda: len(fixture.connections) == 2)
    assert fixture.connections[0].closed
    fixture.transport.stop()
    assert all(connection.closed for connection in fixture.connections)
    assert len(fixture.connections) == 2


def test_stop_during_reconnect_sleep_is_cancellable(sdk_transport, monkeypatch):
    fixture = sdk_transport
    entered = threading.Event()

    async def unavailable(_client):
        entered.set()
        raise ConnectionError("test offline")

    monkeypatch.setattr(fixture.sdk.Client, "_connect", unavailable)
    fixture.transport.start()
    assert entered.wait(2)
    wait_for(lambda: fixture.transport.snapshot()["state"] == "reconnecting")
    fixture.transport.stop()
    assert fixture.transport.snapshot()["state"] == "stopped"


def test_initialization_failure_is_reported_and_owner_released(
    sdk_transport, monkeypatch
):
    monkeypatch.setattr(
        "bot.feishu_transport.configure_feishu_ws_proxy",
        lambda *_: (_ for _ in ()).throw(ValueError("invalid SDK")),
    )
    with pytest.raises(RuntimeError, match="initialization failed"):
        sdk_transport.transport.start()
    sdk_transport.transport.stop()


def test_process_rejects_second_sdk_loop(sdk_transport):
    sdk_transport.transport.start()
    other = FeishuTransport(
        app_id="other",
        app_secret="other",
        event_handler=None,
        proxy_mode="env",
        timeout=0.2,
    )
    with pytest.raises(RuntimeError, match="only one"):
        other.start()
    other.stop()


def test_loop_creation_failure_releases_process_owner(sdk_transport, monkeypatch):
    from bot.feishu_transport import _SDK_OWNER

    def fail():
        raise OSError("no loop resources")

    monkeypatch.setattr("bot.feishu_transport.asyncio.new_event_loop", fail)
    with pytest.raises(RuntimeError, match="initialization failed"):
        sdk_transport.transport.start()
    sdk_transport.transport.stop()
    assert _SDK_OWNER.acquire(blocking=False)
    _SDK_OWNER.release()
