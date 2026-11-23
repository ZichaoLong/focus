"""Deployment matrix and disabled-frontend effects at the composition boundary."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest
import yaml

from bot.adapters.base import ThreadSummary, ThreadSnapshot
from bot.binding_identity import format_binding_id
from bot.constants import GROUP_SHARED_BINDING_OWNER_ID
from bot.focus_runtime.runtime import FocusRuntime
from bot.runtime_admin.application import RuntimeAdminApplication
from bot.service_control_plane import control_request
from bot.service_runtime_lifecycle import (
    ServiceRuntimePhase,
    ServiceRuntimeShutdownError,
)
from bot.stores.chat_binding_store import ChatBindingStore
from bot.stores.feishu_app_connection_lease import (
    FeishuAppConnectionLease,
    FeishuAppConnectionLeaseError,
)
from bot.system_config import SystemConfig
from tests.focus_runtime.codex_handler_fakes import _FakeAdapter, _FakeBot


@pytest.fixture
def web_static_dir(tmp_path):
    static_dir = tmp_path / "web-static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("Focus Web", encoding="utf-8")
    return static_dir


@pytest.fixture
def runtime_factory(tmp_path, monkeypatch, web_static_dir):
    runtimes = []
    monkeypatch.setenv("FOCUS_GLOBAL_DATA_DIR", str(tmp_path / "global"))
    monkeypatch.setattr("bot.focus_runtime.runtime.CodexAppServerAdapter", _FakeAdapter)

    def make(*, feishu=False, web=False, data_dir=None):
        root = data_dir or tmp_path / str(len(runtimes))
        config = root / "config"
        config.mkdir(parents=True, exist_ok=True)
        values = {"web_static_dir": str(web_static_dir)}
        if web is not None:
            values["web_enabled"] = web
        (config / "codex.yaml").write_text(
            yaml.safe_dump(values),
            encoding="utf-8",
        )
        runtime = FocusRuntime(data_dir=root, config_dir=config, feishu_enabled=feishu)
        runtimes.append(runtime)
        bot = _FakeBot(root) if feishu else None
        return runtime, bot

    yield make
    for runtime in reversed(runtimes):
        runtime.stop()


@pytest.mark.parametrize(
    "feishu,web", [(False, False), (False, True), (True, False), (True, True)]
)
def test_four_modes_have_one_core_and_only_selected_ingress(
    runtime_factory, feishu, web
):
    runtime, bot = runtime_factory(feishu=feishu, web=web)
    runtime.start(bot)
    assert runtime.phase is ServiceRuntimePhase.ACTIVE
    status = control_request(runtime.data_dir, "service/status", {})
    assert status["operator_status"]["feishu"]["enabled"] is feishu
    assert bool(status["web_gateway_url"]) is web
    assert runtime._adapter.start_calls == 1
    assert runtime._destination_liveness.snapshot().worker_running is feishu
    assert (runtime._feishu_app_connection_lease is not None) is feishu
    assert hasattr(runtime, "_feishu_surface") is feishu
    if not feishu:
        assert type(runtime._runtime_admin) is RuntimeAdminApplication
        assert not runtime._feishu_platform.is_attached
    runtime.stop()
    assert runtime.phase is ServiceRuntimePhase.CLOSED
    assert runtime._adapter.stop_calls == 1
    if bot:
        assert not bot.transport_running


def test_missing_web_flag_starts_web_without_feishu(runtime_factory):
    runtime, _ = runtime_factory(web=None)
    runtime.start()
    status = control_request(runtime.data_dir, "service/status", {})
    assert status["web_gateway_url"].startswith("http://127.0.0.1:")
    assert status["operator_status"]["feishu"]["enabled"] is False
    assert not hasattr(runtime, "_feishu_surface")


def test_credentials_do_not_enable_feishu_and_flags_are_strict():
    for raw in (
        {},
        {"app_id": "existing", "app_secret": "existing"},
        {"feishu_enabled": False},
    ):
        assert SystemConfig.from_dict(raw).feishu_enabled is False
    for value in ("true", 1, None):
        with pytest.raises(ValueError, match="feishu_enabled"):
            SystemConfig.from_dict({"feishu_enabled": value})
    with pytest.raises(ValueError, match="app_id|app_secret"):
        SystemConfig.from_dict({"feishu_enabled": True})


@pytest.mark.parametrize("sender", ["sender", GROUP_SHARED_BINDING_OWNER_ID])
def test_disabled_instance_does_not_take_app_lease_or_revive_records(
    runtime_factory, tmp_path, sender
):
    data_dir = tmp_path / "historical"
    binding = (sender, "chat")
    store = ChatBindingStore(data_dir)
    store.save(
        binding, {"current_thread_id": "thread-old", "feishu_runtime_state": "attached"}
    )
    before = store.load_all()
    lease = FeishuAppConnectionLease(tmp_path / "global")
    lease.acquire("cli_test_app", instance_name="other")
    try:
        runtime, _ = runtime_factory(data_dir=data_dir)
        runtime.start()
        runtime._adapter.thread_snapshots[("thread-old", False)] = ThreadSnapshot(
            summary=ThreadSummary(
                thread_id="thread-old",
                cwd=str(data_dir),
                name="old",
                preview="",
                created_at=0,
                updated_at=0,
                source="cli",
                status="notLoaded",
            )
        )
        records = control_request(data_dir, "binding/list", {})["bindings"]
        assert len(records) == 1
        assert records[0]["feishu_runtime_state"] == "detached"
        status = control_request(
            data_dir, "binding/status", {"binding_id": format_binding_id(binding)}
        )
        assert status["next_prompt_allowed"] is False
        assert status["next_prompt_reason_code"] == "feishu_disabled"
        detached = control_request(
            data_dir, "binding/detach", {"binding_id": format_binding_id(binding)}
        )
        assert detached["already_detached"] and not detached["changed"]
        thread = control_request(data_dir, "thread/status", {"thread_id": "thread-old"})
        assert thread["bound_binding_ids"] == [format_binding_id(binding)]
        detached_thread = control_request(
            data_dir, "thread/detach", {"thread_id": "thread-old"}
        )
        assert detached_thread["already_detached"] and not detached_thread["changed"]
        assert store.load_all() == before
        assert runtime._binding_runtime.binding_keys_locked() == ()
        for method, params in (
            ("service/attach", {}),
            ("binding/attach", {"binding_id": format_binding_id(binding)}),
            ("binding/submit-prompt", {}),
            ("thread/attach", {}),
            ("thread/send-image", {}),
            ("binding/list", {"refresh_names": True}),
        ):
            with pytest.raises(Exception, match="Feishu is disabled"):
                control_request(data_dir, method, params)
        control_request(
            data_dir, "binding/clear", {"binding_id": format_binding_id(binding)}
        )
        assert not store.load_all()
        assert not runtime._adapter.start_turn_calls
        enabled, bot = runtime_factory(feishu=True)
        with pytest.raises(FeishuAppConnectionLeaseError):
            enabled.start(bot)
        assert enabled.phase is ServiceRuntimePhase.CLOSED
    finally:
        lease.release()


def test_disabled_reset_disconnect_and_retention_do_not_call_feishu(runtime_factory):
    runtime, _ = runtime_factory(web=True)
    runtime.start()
    runtime._interaction_requests.retire_backend_epoch_after_stop = Mock(
        side_effect=AssertionError("Feishu effect")
    )
    runtime._feishu_root_operations.retire_backend_epoch_after_stop = Mock(
        side_effect=AssertionError("Feishu effect")
    )
    runtime.call(runtime._adapter_events.handle_disconnect_impl)
    result = control_request(
        runtime.data_dir, "service/reset-backend", {"force": False}
    )
    assert result["app_server_url"]
    control_request(runtime.data_dir, "data/prune", {})
    control_request(runtime.data_dir, "service/prepare-offline-maintenance", {})
    control_request(runtime.data_dir, "service/cancel-offline-maintenance", {})
    runtime._interaction_requests.retire_backend_epoch_after_stop.assert_not_called()
    runtime._feishu_root_operations.retire_backend_epoch_after_stop.assert_not_called()


def test_failed_feishu_stop_retains_authority_until_retry(runtime_factory):
    runtime, bot = runtime_factory(feishu=True)
    runtime.start(bot)
    stop = bot.stop
    bot.stop = Mock(side_effect=RuntimeError("transport still alive"))
    with pytest.raises(ServiceRuntimeShutdownError, match="Feishu transport barrier"):
        runtime.stop()
    assert runtime.phase is ServiceRuntimePhase.STOPPING
    assert runtime._service_instance_lease.owns_current_lease()
    assert runtime._feishu_app_connection_lease.app_id
    assert runtime._adapter.stop_calls == 0
    bot.stop = stop
    runtime.stop()
    assert runtime.phase is ServiceRuntimePhase.CLOSED
    assert not runtime._feishu_app_connection_lease.app_id


@pytest.mark.skipif(
    sys.platform == "win32", reason="SIGTERM is a POSIX graceful shutdown contract"
)
@pytest.mark.parametrize("web", [False, True])
def test_fresh_daemon_without_sdk_survives_until_sigterm_and_releases_lease(
    tmp_path, web, web_static_dir
):
    # A subprocess catches imports hidden by the main pytest process's SDK cache.
    config = tmp_path / "config"
    config.mkdir()
    (config / "codex.yaml").write_text(
        yaml.safe_dump({"web_enabled": web, "web_static_dir": str(web_static_dir)}),
        encoding="utf-8",
    )
    code = """
import importlib.abc, os, pathlib, sys
from types import SimpleNamespace
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "lark_oapi" or fullname.startswith("lark_oapi."):
            raise RuntimeError("disabled frontend imported SDK: " + fullname)
sys.meta_path.insert(0, Block())
import bot.focus_runtime.runtime as composition
from tests.focus_runtime.codex_handler_fakes import _FakeAdapter
composition.CodexAppServerAdapter = _FakeAdapter
import bot.__main__ as daemon
root = pathlib.Path(sys.argv[1])
def paths(instance):
    os.environ.update(FOCUS_CONFIG_DIR=str(root / "config"), FOCUS_DATA_DIR=str(root / "data"),
                      FOCUS_GLOBAL_DATA_DIR=str(root / "global"), FOCUS_INSTANCE="default")
    return SimpleNamespace(config_dir=root / "config", data_dir=root / "data")
daemon.apply_instance_environment = paths
daemon.main([])
assert not any(name.startswith("lark_oapi") for name in sys.modules)
"""
    with (tmp_path / "process.log").open("w+") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", code, str(tmp_path)], stdout=log, stderr=log
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                assert process.poll() is None, (tmp_path / "process.log").read_text()
                try:
                    status = control_request(
                        tmp_path / "data", "service/status", {}, timeout_seconds=0.25
                    )
                except Exception:
                    pass
                else:
                    # The control listener starts before an enabled Web gateway binds.
                    if not status["web_gateway_enabled"] or status["web_gateway_url"]:
                        break
                time.sleep(0.05)
            else:
                pytest.fail((tmp_path / "process.log").read_text())
            assert status["operator_status"]["feishu"]["state"] == "disabled"
            assert status["web_gateway_enabled"] is web
            assert bool(status["web_gateway_url"]) is web
            assert not (tmp_path / "global" / "feishu_app_connections").exists()
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=10) == 0, (tmp_path / "process.log").read_text()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    from bot.stores.service_instance_lease import ServiceInstanceLease

    lease = ServiceInstanceLease(tmp_path / "data")
    lease.acquire()
    lease.release()


def test_feishu_start_failure_rolls_back_after_active_ingress(runtime_factory):
    runtime, bot = runtime_factory(feishu=True)

    def fail():
        assert runtime.phase is ServiceRuntimePhase.ACTIVE
        runtime._ingress.call(lambda: None)
        raise RuntimeError("SDK initialization failed")

    bot.start = fail
    with pytest.raises(RuntimeError, match="SDK initialization"):
        runtime.start(bot)
    assert runtime.phase is ServiceRuntimePhase.CLOSED
    assert runtime._feishu_app_connection_lease.app_id == ""
    assert not bot.transport_running


def test_reenable_restores_bookmark_detached_without_replaying_input(
    runtime_factory, tmp_path
):
    root = tmp_path / "restart"
    store = ChatBindingStore(root)
    store.save(
        ("sender", "chat"),
        {"current_thread_id": "old", "feishu_runtime_state": "attached"},
    )
    disabled, _ = runtime_factory(data_dir=root)
    disabled.start()
    disabled.stop()
    enabled, bot = runtime_factory(feishu=True, data_dir=root)
    enabled.start(bot)
    records = control_request(root, "binding/list", {})["bindings"]
    assert records[0]["thread_id"] == "old"
    assert records[0]["feishu_runtime_state"] == "detached"
    assert not enabled._adapter.start_turn_calls
    assert not enabled._adapter.resume_thread_calls


def test_web_only_creates_thread_and_answers_canonical_approval(runtime_factory):
    runtime, _ = runtime_factory(web=True)
    runtime.start()
    runtime.call(runtime._adapter_events.accept_connection_ingress, 1)
    web = runtime._web_runtime
    runtime.call(web.client_connected, "browser")
    result = runtime._ingress.call(
        web.start_thread,
        "browser",
        text="hello",
        cwd=str(runtime.data_dir),
    )
    thread_id = result["thread_id"]
    assert result["accepted"]
    assert runtime._adapter.start_turn_calls
    runtime.call(
        runtime._adapter_events.handle_request_for_connection,
        1,
        "approval",
        "item/commandExecution/requestApproval",
        {"threadId": thread_id, "turnId": "turn-1", "command": "pwd"},
    )
    detail = runtime._ingress.call(web.read_thread, "browser", thread_id)
    pending = detail["pending_requests"][0]
    runtime._ingress.call(
        web.respond_request,
        "browser",
        pending["id"],
        connection_generation=pending["connection_generation"],
        response_capability=pending["response_capability"],
        action="approve_once",
    )
    assert runtime._adapter.respond_calls[-1]["result"] == {"decision": "accept"}
    assert not runtime._feishu_platform.is_attached


def test_headless_thread_and_goal_administration_uses_core(runtime_factory):
    runtime, _ = runtime_factory()
    runtime.start()
    runtime._adapter.thread_snapshots[("admin-thread", False)] = ThreadSnapshot(
        summary=ThreadSummary(
            thread_id="admin-thread",
            cwd=str(runtime.data_dir),
            name="admin",
            preview="",
            created_at=0,
            updated_at=0,
            source="cli",
            status="notLoaded",
        ),
    )
    goal = control_request(
        runtime.data_dir,
        "thread/goal/set",
        {
            "thread_id": "admin-thread",
            "objective": "maintenance",
            "status": "paused",
        },
    )
    assert goal["goal"]["status"] == "paused"
    control_request(
        runtime.data_dir, "thread/goal/clear", {"thread_id": "admin-thread"}
    )
    for action in ("archive", "unarchive", "delete"):
        control_request(
            runtime.data_dir, f"thread/{action}", {"thread_id": "admin-thread"}
        )
        assert getattr(runtime._adapter, f"{action}_thread_calls") == ["admin-thread"]
    assert not runtime._adapter.start_turn_calls
