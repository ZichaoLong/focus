"""Retention CLI works without Web and uses the service's lifecycle-fenced sweep."""

import os
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import yaml

from bot.data_retention import DataRetentionService
from bot.data_retention_contract import DataPruneResult, DataRetentionPolicy
from bot.focus_runtime.runtime import FocusRuntime
from bot.focusctl import focusctl_command_schema, main
from bot.instance_resolution import CliInstanceTarget
from bot.service_control_plane import ServiceControlPlane, ServiceControlResponseTimeoutError, control_request
from bot.service_runtime_lifecycle import ServiceRuntimeIngressDispatcher
from bot.stores.data_retention_store import DataRetentionStore
from bot.stores.service_instance_lease import ServiceInstanceLease
from bot.stores.terminal_result_store import TerminalResultRecord, TerminalResultStore
from tests.test_service_runtime_lifecycle import _LifecycleFixture


@pytest.fixture
def roots(tmp_path, monkeypatch):
    data, config = tmp_path / 'data', tmp_path / 'config'
    monkeypatch.setenv('FOCUS_DATA_ROOT', str(data))
    monkeypatch.setenv('FOCUS_CONFIG_ROOT', str(config))
    monkeypatch.setenv('FOCUS_GLOBAL_DATA_DIR', str(data / '_global'))
    monkeypatch.setenv('FOCUS_INSTANCE', 'default')
    return data, config


def run(*args):
    with pytest.raises(SystemExit) as exit:
        main(list(args))
    return exit.value.code


def test_offline_status_partial_settings_and_instance_isolation(roots, capsys):
    data, config = roots
    assert run('data', 'status') == 0
    assert '30 天' in capsys.readouterr().out
    assert not (config / 'codex.yaml').exists()
    assert run('data', 'retention', '--records-days', '7') == 0
    assert run('data', 'retention', '--attachments-days', '90') == 0
    store = DataRetentionStore(data, config_dir=config)
    assert store.load() == DataRetentionPolicy(7, 90)
    named = config / 'instances' / 'named'
    named.mkdir(parents=True)
    (named / 'codex.yaml').write_text('model: keep-model\n')
    assert run('--instance', 'named', 'data', 'retention', '--attachments-days', '7') == 0
    assert yaml.safe_load((named / 'codex.yaml').read_text()) == {'model': 'keep-model', 'attachments_retention_days': 7}
    assert store.load() == DataRetentionPolicy(7, 90)
    assert not (data / 'data_retention.json').exists()


def test_invalid_args_and_missing_instance_do_not_write_settings(roots):
    _, config = roots
    assert run('data', 'retention') == 2
    assert run('data', 'retention', '--records-days', '14') == 2
    assert run('--instance', 'missing', 'data', 'retention', '--records-days', '7') == 2
    assert run('--instance', 'default', '--instance', 'other', 'data', 'prune') == 2
    assert not config.exists()


def test_running_instance_published_config_path_is_the_only_cli_target(roots, tmp_path):
    data, config = roots
    published = tmp_path / 'published-config'
    target = CliInstanceTarget('selected', data, running_entry=SimpleNamespace(config_dir=str(published)))
    with patch('bot.manage_cli.data_commands.resolve_cli_instance_target', return_value=target):
        assert run('data', 'retention', '--records-days', '7') == 0
    assert yaml.safe_load((published / 'codex.yaml').read_text()) == {'records_retention_days': 7}
    assert not config.exists()


def test_diagnostic_cleanup_reads_the_same_yaml_period(roots):
    data, _ = roots
    assert run('data', 'retention', '--records-days', '7') == 0
    log = data / 'focus.log.1'
    log.write_text('10 day old diagnostic')
    old = time.time() - 10 * 86400
    os.utime(log, (old, old))
    assert run('--instance', 'default', 'logs', 'prune') == 0
    assert not log.exists()


def test_stopped_service_never_falls_back_to_direct_cleanup(roots, capsys):
    data, _ = roots
    data.mkdir()
    evidence = data / 'focus.log.1'
    evidence.write_text('old log')
    old = time.time() - 100 * 86400
    os.utime(evidence, (old, old))
    assert run('data', 'prune') == 2
    assert '无需启用 Web' in capsys.readouterr().err
    assert evidence.exists()


def test_live_control_plane_prunes_without_web_and_obeys_maintenance_gate(roots, capsys):
    data, config = roots
    store = DataRetentionStore(data, config_dir=config)
    store.update({'records_days': 7})
    terminal = TerminalResultStore(data)
    terminal.upsert(TerminalResultRecord('old', 'prompt', 'text', time.time() - 10 * 86400))
    lifecycle = _LifecycleFixture(web_running=False).lifecycle
    runtime = object.__new__(FocusRuntime)
    runtime._runtime_call = Mock(side_effect=AssertionError('sweep must stay outside RuntimeLoop'))
    runtime._ingress = ServiceRuntimeIngressDispatcher(
        lifecycle=lifecycle, call_runtime=runtime._runtime_call, submit_runtime=Mock())
    runtime._data_retention = DataRetentionService(store, {
        'terminal_results': lambda policy, now: terminal.prune(now - policy.records_days * 86400),
    })
    lease = ServiceInstanceLease(data)
    lease.acquire()
    plane = ServiceControlPlane(data_dir=data, dispatch=runtime._handle_service_control_request,
                                owns_current_lease=lease.owns_current_lease, auth_token=lambda: lease.owner_token)
    try:
        lifecycle.start()
        lease.publish_control_endpoint(plane.start())
        assert run('data', 'prune') == 0
        assert '清理合计: 1 项' in capsys.readouterr().out
        assert terminal.get('old') == ''
        lifecycle.prepare_offline_maintenance(lambda: {})
        assert run('data', 'prune') == 2
        assert 'active service runtime' in capsys.readouterr().err
        lifecycle.cancel_offline_maintenance()
        # Partial failures retain successful counts and return a failing exit code.
        def fail(*_):
            raise OSError('unavailable')
        runtime._data_retention = DataRetentionService(store, {'ok': lambda *_: DataPruneResult(2, 10), 'bad': fail})
        assert run('data', 'prune') == 1
        output = capsys.readouterr().out
        assert 'bad: 清理失败' in output and '清理合计: 2 项' in output
        with pytest.raises(Exception, match='no options'):
            control_request(data, 'data/prune', {'force': True})
    finally:
        plane.stop()
        lifecycle.stop()
        lease.release()


def test_ambiguous_control_reply_is_reported_without_retry(roots, capsys):
    with patch('bot.manage_cli.data_commands.control_request', side_effect=ServiceControlResponseTimeoutError('sent')) as request:
        assert run('data', 'prune') == 2
    assert request.call_count == 1
    assert '结果未知' in capsys.readouterr().err


@pytest.mark.parametrize('change', [{'policy': {}}, {'results': {'logs': {}}}, {'records': 999}])
def test_malformed_cleanup_receipt_is_not_printed_as_success(roots, capsys, change):
    result = {'policy': DataRetentionPolicy().payload(), 'results': {'logs': {'records': 1, 'bytes_freed': 5}},
              'errors': {}, 'records': 1, 'bytes_freed': 5, **change}
    with patch('bot.manage_cli.data_commands.control_request', return_value=result) as request:
        assert run('data', 'prune') == 2
    assert request.call_count == 1
    captured = capsys.readouterr()
    assert '清理合计' not in captured.out and '响应无效' in captured.err


def test_completion_uses_the_executable_command_schema():
    data = focusctl_command_schema().subcommand('data')
    assert data.subcommand('status') is not None
    assert data.subcommand('prune') is not None
    retention = data.subcommand('retention')
    assert {'--records-days', '--attachments-days'} <= {name for option in retention.options for name in option.names}
