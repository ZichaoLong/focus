"""Expiry boundaries, persistent replay fences and shared attachment ownership."""
import json
import pathlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch

import pytest

from bot.data_retention import DataRetentionService
from bot.data_retention_contract import DataPruneResult, DataRetentionPolicy
from bot.stores.data_retention_store import DataRetentionStore
from bot.stores.attachment_store import AttachmentStore
from bot.stores.generated_image_delivery_store import GeneratedImageDeliveryRecord, GeneratedImageDeliveryStore
from bot.stores.group_chat_store import GroupChatStore
from bot.stores.terminal_result_store import TerminalResultRecord, TerminalResultStore
from bot.stores.web_prompt_timing_store import WebPromptTimingStore
from bot.stores.web_writer_profile_store import WebWriterProfile, WebWriterProfileStore
from tests.test_web_attachment_store import _PNG_1X1

DAY = 86400
NOW = 200 * DAY


def test_policy_defaults_atomic_partial_updates_and_corruption(tmp_path):
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    assert store.load() == DataRetentionPolicy()
    assert not (tmp_path / 'data_retention.json').exists()
    with ThreadPoolExecutor(2) as pool:
        results = [pool.submit(DataRetentionStore(tmp_path, config_dir=tmp_path / 'config').update, change)
                   for change in ({'records_days': 7}, {'attachments_days': 90})]
        for result in results:
            result.result()
    assert DataRetentionStore(tmp_path, config_dir=tmp_path / 'config').load() == DataRetentionPolicy(7, 90)
    for changes in ({'records_days': True}, {'records_days': 7.0}, {'records_days': 14}, {}, {'unknown': 30}):
        with pytest.raises(ValueError):
            store.update(changes)
    (tmp_path / 'config' / 'codex.yaml').write_text('{broken')
    called = []
    service = DataRetentionService(store, {'test': lambda *_: called.append(True)})
    with pytest.raises(ValueError):
        service.prune()
    assert not called


def test_cleanup_reports_partial_failure_and_uses_updated_policy(tmp_path):
    store = DataRetentionStore(tmp_path, config_dir=tmp_path / 'config')
    def success(policy, now):
        assert (policy.records_days, now) == (90, NOW)
        return DataPruneResult(3, 50)
    def failure(*_):
        raise OSError('disk unavailable')
    service = DataRetentionService(store, {'a': success, 'b': failure})
    service.update({'records_days': 90})
    result = service.prune(now=NOW)
    assert result['records'] == 3
    assert result['bytes_freed'] == 50
    assert result['errors'] == {'b': 'cleanup_failed'}


def test_terminal_and_image_retirement_fences_survive_restart(tmp_path):
    terminal = TerminalResultStore(tmp_path)
    terminal.upsert(TerminalResultRecord('reply-old', 'prompt-old', 'old', NOW - 31 * DAY))
    terminal.upsert(TerminalResultRecord('reply-new', 'prompt-new', 'new', NOW))
    assert terminal.prune(NOW - 30 * DAY).records == 1
    terminal = TerminalResultStore(tmp_path)
    assert terminal.get('reply-old') == ''
    assert terminal.get('reply-new') == 'new'
    for started in (0, NOW - 40 * DAY):
        assert terminal.has_execution_result(execution_message_id='prompt-old', final_reply_text='old', execution_started_at=started)
    assert not terminal.has_execution_result(execution_message_id='fresh', final_reply_text='fresh', execution_started_at=NOW)
    images = GeneratedImageDeliveryStore(tmp_path)
    key = dict(sender_id='s', chat_id='c', thread_id='thread', turn_id='turn', item_id='image')
    claim = images.claim_delivery(**key)
    images.commit_delivery(claim, GeneratedImageDeliveryRecord(**key, local_path='/work/image.png', message_id='sent', delivered_at=NOW-31*DAY))
    assert images.prune(NOW - 30 * DAY).records == 1
    images = GeneratedImageDeliveryStore(tmp_path)
    assert images.claim_delivery(**key, execution_started_at=NOW-40*DAY) is None
    assert images.claim_delivery(**key) is None
    assert images.claim_delivery(**{**key, 'turn_id': 'fresh'}, execution_started_at=NOW) is not None
    assert images.prune(NOW - 90 * DAY).records == 0
    assert GeneratedImageDeliveryStore(tmp_path).claim_delivery(**key) is None


def test_group_cleanup_preserves_activation_boundary_unknown_lines_and_active_chat(tmp_path):
    store = GroupChatStore(tmp_path)
    store.activate_chat('chat', activated_by='admin', activated_at=100)
    store.set_last_boundary_seq('chat', 5)
    for created in (int((NOW - 31 * DAY) * 1000), int(NOW * 1000)):
        store.append_message('chat', {'created_at': created, 'message_id': str(created), 'text': 'text'})
    before = store.group_snapshot('chat')
    path = store.log_path('chat')
    with path.open('a') as handle:
        handle.write('{invalid}\n')
    assert store.prune(NOW-30*DAY, protected_chats=('chat',)).records == 0
    result = store.prune(NOW-30*DAY)
    assert result.records == 1 and result.bytes_freed > 0
    assert store.group_snapshot('chat') == before
    assert '{invalid}' in path.read_text()
    assert len(store.read_messages_between('chat')) == 1


def test_browser_profiles_expire_by_idle_time_and_connected_profiles_are_touched(tmp_path):
    store = WebWriterProfileStore(tmp_path)
    for key in ('active', 'idle'):
        store.save(WebWriterProfile(key, 'thread', '/work', updated_at=NOW-31*DAY))
    with patch('bot.stores.web_writer_profile_store.time.time', return_value=NOW):
        assert store.prune(NOW-30*DAY, protected_clients=('active',)).records == 1
    assert store.load('idle') is None
    assert store.load('active').updated_at == NOW
    assert store.load('active').selected_thread_id == 'thread'


def test_shared_attachment_policy_protects_active_cwd_and_never_touches_legacy_files(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    legacy = workspace / '_feishu_attachments' / 'legacy.txt'
    legacy.parent.mkdir()
    legacy.write_text('user owned')
    policy = DataRetentionStore(tmp_path / 'data', config_dir=tmp_path / 'config')
    store = AttachmentStore(tmp_path / 'data', ttl_seconds=1800, retained_days=lambda: policy.load().attachments_days,
                            scheduled_retention=True)
    with patch('bot.stores.attachment_store.time.time', return_value=NOW-10*DAY):
        feishu = store.stage_feishu(client_id='sender', scope_key='feishu:chat:', cwd=str(workspace),
                                   display_name='notes.txt', media_type='text/plain', content=b'arbitrary Feishu file')
        web = store.stage(client_id='web', scope_key='thread:web', cwd=str(workspace),
                          display_name='image.png', media_type='image/png', content=_PNG_1X1)
        store.mark_submitted([feishu.attachment_id, web.attachment_id], submitted=True)
    assert pathlib.Path(feishu.local_path).parent == tmp_path / 'data' / 'web_attachment_cache'
    assert store.prune(now=NOW).records == 0
    policy.update({'attachments_days': 7})
    assert store.prune(now=NOW, protected_cwds=(str(workspace),)).records == 0
    result = store.prune(now=NOW)
    assert result.records == 2
    assert result.bytes_freed == len(b'arbitrary Feishu file') + len(_PNG_1X1)
    assert legacy.read_text() == 'user owned'
    assert not pathlib.Path(feishu.local_path).exists()


def test_legacy_web_expiry_recalculated_and_shared_pending_ttl_unchanged(tmp_path):
    store = AttachmentStore(tmp_path, ttl_seconds=1800, retained_days=lambda: 90, scheduled_retention=True)
    record = store.stage(client_id='web', scope_key='draft', cwd=str(tmp_path), display_name='image.png',
                         media_type='image/png', content=_PNG_1X1, now=NOW-40*DAY)
    store.mark_submitted([record.attachment_id], submitted=True, now=NOW-40*DAY+1)
    raw = json.loads((tmp_path / 'web_attachments.json').read_text())
    for value in raw['attachments'].values():
        value.pop('retained_at')
        value.pop('channel')
        value['expires_at'] = NOW-10*DAY+1  # Existing 30-day cache.
    (tmp_path / 'web_attachments.json').write_text(json.dumps(raw))
    assert store.prune(now=NOW).records == 0
    assert store.download(attachment_id=record.attachment_id, now=NOW).content == _PNG_1X1
    with patch('bot.stores.attachment_store.time.time', return_value=NOW):
        pending = store.stage_feishu(client_id='sender', scope_key='feishu:chat:', cwd=str(tmp_path),
                                     display_name='text', media_type='text/plain', content=b'pending')
    assert store.prune(now=NOW+1801).records == 1
    assert not pathlib.Path(pending.local_path).exists()


def test_prompt_timing_prune_protects_live_trace_and_rejects_expired_upload(tmp_path):
    store = WebPromptTimingStore(tmp_path)
    old = {'submission_id': 'old', 'client_id': 'client', 'thread_id': 'thread',
           'submitted_at_ms': int((NOW-31*DAY)*1000), 'received_at_ms': int((NOW-31*DAY)*1000),
           'epoch': 'epoch', 'observation_id': 'token', 'first_output': {'status': 'pending', 'reason_code': ''}}
    store.receive(old)
    store.receive({**old, 'submission_id': 'active'})
    assert store.prune(NOW-30*DAY, protected_ids=('active',)).records == 1
    assert store.detail('old') is None
    assert store.detail('active') is not None
    with patch('bot.stores.web_prompt_timing_store.time.time', return_value=NOW):
        store.sync_browser('client', [{'submission_id': 'old', 'thread_id': 'thread',
                                      'submitted_at_ms': old['submitted_at_ms'], 'browser': {}}])
    assert store.detail('old') is None
    assert store.prune(NOW-30*DAY).records == 1


def test_lifecycle_does_not_release_authority_if_retention_worker_join_fails():
    from tests.test_service_runtime_lifecycle import _LifecycleFixture
    from bot.service_runtime_lifecycle import ServiceRuntimeShutdownError
    fixture = _LifecycleFixture()
    def fail():
        raise RuntimeError('worker alive')
    fixture.lifecycle._shutdown = replace(fixture.lifecycle._shutdown, stop_data_retention=fail)
    fixture.lifecycle.start()
    with pytest.raises(ServiceRuntimeShutdownError):
        fixture.lifecycle.stop()
    assert 'release_machine_authority' not in fixture.events
    fixture.lifecycle._shutdown = replace(fixture.lifecycle._shutdown, stop_data_retention=lambda: None)
    fixture.lifecycle.stop()
    assert fixture.events[-1] == 'release_machine_authority'


def test_attachment_orphans_are_bounded_without_following_links(tmp_path):
    import os
    store = AttachmentStore(tmp_path, ttl_seconds=60, scheduled_retention=True)
    record = store.stage(client_id='web', scope_key='draft', cwd=str(tmp_path), display_name='image.png',
                         media_type='image/png', content=_PNG_1X1, now=NOW)
    path = pathlib.Path(record.local_path)
    (tmp_path / 'web_attachments.json').unlink()  # Crash after metadata retirement.
    os.utime(path, (NOW-61, NOW-61))
    external = tmp_path / 'external'
    external.write_text('keep')
    link = path.parent / '22222222-2222-4222-8222-222222222222-link'
    link.symlink_to(external)
    result = store.prune(now=NOW)
    assert result.records == 1 and result.bytes_freed == len(_PNG_1X1)
    assert external.read_text() == 'keep'
    assert link.is_symlink()


def test_active_execution_monotonic_clock_is_converted_and_delivery_recovery_defers_pruning(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from bot.focus_runtime.data_retention_composition import compose_data_retention
    terminal = TerminalResultStore(tmp_path)
    terminal.upsert(TerminalResultRecord('old', 'old-card', 'old', NOW - 31*DAY))
    active = SimpleNamespace(execution=SimpleNamespace(running=True, started_at=60*DAY), working_dir='/work', binding=('s', 'c'))
    recovering = [False]
    files = Mock(prune_pending=Mock(return_value=DataPruneResult()))
    service = compose_data_retention(
        data_dir=tmp_path, policy=DataRetentionStore(tmp_path, config_dir=tmp_path / 'config'), sessions=lambda: (active,),
        web_cwds=lambda: (), recovery_active=lambda: recovering[0],
        prune_profiles=lambda _: DataPruneResult(), prune_timings=lambda _: DataPruneResult(),
        prune_groups=lambda *_, **__: DataPruneResult(), files=files,
        attachments=Mock(prune=Mock(return_value=DataPruneResult())),
        terminal_results=terminal, image_deliveries=GeneratedImageDeliveryStore(tmp_path))
    with patch('bot.focus_runtime.data_retention_composition.time.monotonic', return_value=100*DAY):
        assert service.prune(now=NOW)['results']['terminal_results']['records'] == 0
    active.execution.running = False
    recovering[0] = True
    assert service.prune(now=NOW)['results']['terminal_results']['records'] == 0
    recovering[0] = False
    assert service.prune(now=NOW)['results']['terminal_results']['records'] == 1
    # A current execution is recent in UTC even on a machine with short uptime.
    assert not terminal.has_execution_result(execution_message_id='new-card', final_reply_text='new', execution_started_at=NOW-10)


def test_terminal_target_converts_process_monotonic_to_utc():
    from bot.execution_recovery_runtime import ExecutionRecoveryRuntimeTransitions
    from tests.test_execution_recovery_runtime import ExecutionRecoveryRuntimeTransitionTests
    harness = ExecutionRecoveryRuntimeTransitionTests()
    lock, manager, _, runtime = harness._make_runtime()
    state, session = harness._seed_execution(manager, lock, ('s', 'c'))
    state['started_at'] = 10.0
    with lock:
        session = manager.session_snapshot_locked(session.handle)
    with patch('bot.execution_recovery_runtime.time.monotonic', return_value=20.0), patch('bot.execution_recovery_runtime.time.time', return_value=NOW):
        target = ExecutionRecoveryRuntimeTransitions._terminal_target(session, thread_id='thread-1', turn_id='turn-1', occurred_at=20)
    harness.doCleanups()
    assert target.execution_started_at == NOW-10
