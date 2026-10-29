"""First-output observations are passive, exact and never reconstructed from history."""
from __future__ import annotations

import json
import pathlib
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bot.stores.web_prompt_timing_store import WebPromptTimingStore
from bot.web_runtime import prompt_timing
from bot.web_runtime.prompt_timing import WebPromptTimingRecorder
from tests.web_runtime.harness import WebRuntimeControllerHarness

STAMP = 1_790_000_000_123
IDENTITY = '11111111-1111-4111-8111-111111111111'
SECOND = '22222222-2222-4222-8222-222222222222'


@pytest.fixture
def recorder(tmp_path):
    value = WebPromptTimingRecorder(WebPromptTimingStore(tmp_path), 'epoch')
    yield value
    value.close()


def arm(recorder, identity=IDENTITY, mode='start'):
    trace = recorder.begin(identity, 'doc', 'thread', STAMP)
    trace.mark('app_server_rpc_started', input_mode=mode)
    return trace


def start(recorder):
    recorder.observe_notification('turn/started', {'threadId': 'thread', 'turn': {'id': 'turn', 'items': []}})


def user(recorder, identity=IDENTITY, item_id='input'):
    recorder.observe_notification('item/started', {'threadId': 'thread', 'turnId': 'turn',
        'item': {'id': item_id, 'type': 'userMessage', 'clientId': f'focus-web:{identity}'}})


def output(recorder, method='item/agentMessage/delta', text='first text', **extra):
    recorder.observe_notification(method, {'threadId': 'thread', 'turnId': 'turn', 'itemId': 'output', 'delta': text, **extra})


def saved(recorder, identity=IDENTITY):
    recorder.flush()
    return recorder.detail(identity)['first_output']


def test_first_live_thinking_is_saved_once_with_focus_clock_and_survives_restart(recorder, monkeypatch, tmp_path):
    clock = SimpleNamespace(wall=STAMP / 1000, monotonic_value=10)
    monkeypatch.setattr(prompt_timing, 'time', SimpleNamespace(
        time=lambda: clock.wall, monotonic=lambda: clock.monotonic_value))
    arm(recorder)
    start(recorder)
    user(recorder)
    assert saved(recorder)['status'] == 'pending'
    output(recorder, text='')
    output(recorder, method='item/commandExecution/outputDelta')
    output(recorder, method='item/reasoning/summaryPartAdded')
    assert saved(recorder)['status'] == 'pending'
    writes = Mock(wraps=recorder.store.update)
    monkeypatch.setattr(recorder.store, 'update', writes)
    clock.wall -= 100
    clock.monotonic_value += 1.8
    output(recorder, method='item/reasoning/textDelta')
    first = saved(recorder)
    assert first == {'status': 'observed', 'at_ms': STAMP - 100_000, 'elapsed_ms': 1800,
                     'turn_id': 'turn', 'item_id': 'output', 'kind': 'thinking'}
    for _ in range(1000):
        output(recorder, text='later text must never enter diagnostics')
    assert saved(recorder) == first
    assert writes.call_count == 1
    assert 'later text' not in json.dumps(recorder.store.detail(IDENTITY))
    recorder.close()
    restarted = WebPromptTimingRecorder(WebPromptTimingStore(tmp_path), 'next-epoch')
    try:
        assert restarted.detail(IDENTITY)['first_output'] == first
    finally:
        restarted.close()


@pytest.mark.parametrize('mode', ['start', 'steer'])
def test_same_turn_additional_input_cannot_borrow_output_even_when_start_races_to_steer(recorder, mode):
    arm(recorder)
    start(recorder)
    user(recorder)
    arm(recorder, SECOND, mode)
    user(recorder, SECOND, 'second-input')
    output(recorder)
    assert saved(recorder)['status'] == 'observed'
    assert saved(recorder, SECOND) == {'status': 'unassociated',
        'reason_code': 'steered_input' if mode == 'steer' else 'additional_turn_input'}


def test_new_turn_requires_initial_input_before_any_output(recorder):
    arm(recorder)
    start(recorder)
    output(recorder)
    user(recorder)
    assert saved(recorder) == {'status': 'unassociated', 'reason_code': 'output_preceded_input'}


def test_missing_turn_start_foreign_thread_and_history_cannot_invent_first_output(recorder):
    arm(recorder)
    output(recorder, threadId='fork')
    assert saved(recorder)['status'] == 'pending'
    recorder.enrich({'thread_id': 'thread', 'turns': [{'role': 'assistant', 'text': 'history', 'rawTurnId': 'turn'}]})
    assert saved(recorder)['status'] == 'pending'
    user(recorder)
    output(recorder)
    assert saved(recorder) == {'status': 'unassociated', 'reason_code': 'not_observed_initial_input'}


@pytest.mark.parametrize('cause', ['backend', 'closed', 'notLoaded', 'shutdown'])
def test_observation_gap_is_terminal_even_if_output_arrives_later(recorder, cause):
    arm(recorder)
    start(recorder)
    user(recorder)
    if cause == 'backend':
        recorder.observe_event({'type': 'backend_disconnected'})
    elif cause == 'closed':
        recorder.observe_notification('thread/closed', {'threadId': 'thread'})
    elif cause == 'notLoaded':
        recorder.observe_notification('thread/status/changed', {'threadId': 'thread', 'status': {'type': 'notLoaded'}})
    else:
        recorder.close()
    start(recorder)
    user(recorder)
    output(recorder)
    assert saved(recorder)['status'] == 'interrupted'


def test_restart_does_not_call_old_pending_observation_active(recorder, tmp_path):
    arm(recorder)
    recorder.flush()
    restarted = WebPromptTimingRecorder(WebPromptTimingStore(tmp_path), 'next-epoch')
    try:
        assert restarted.detail(IDENTITY)['first_output']['status'] == 'interrupted'
        assert restarted.recent('thread')[0]['first_output']['status'] == 'interrupted'
        assert recorder.store.detail(IDENTITY)['first_output']['status'] == 'pending'
    finally:
        restarted.close()


def test_turn_ending_without_text_stops_waiting(recorder):
    arm(recorder)
    start(recorder)
    user(recorder)
    recorder.observe_notification('turn/completed', {'threadId': 'thread', 'turn': {'id': 'turn', 'items': []}})
    assert saved(recorder) == {'status': 'not_observed', 'reason_code': 'turn_ended_without_output'}


def test_first_nonempty_live_item_is_observed_without_stream_deltas(recorder):
    arm(recorder)
    start(recorder)
    user(recorder)
    recorder.observe_notification('item/started', {'threadId': 'thread', 'turnId': 'turn',
        'item': {'id': 'reply', 'type': 'agentMessage', 'text': ''}})
    assert saved(recorder)['status'] == 'pending'
    recorder.observe_notification('item/completed', {'threadId': 'thread', 'turnId': 'turn',
        'item': {'id': 'reply', 'type': 'agentMessage', 'text': 'done'}})
    assert saved(recorder)['kind'] == 'text'


def test_first_output_cache_eviction_is_interruption_not_missing_delivery(recorder):
    arm(recorder)
    start(recorder)
    user(recorder)
    for i in range(256):
        recorder.observe_notification('turn/started', {'threadId': 'thread', 'turn': {'id': f'other-{i}', 'items': []}})
    assert saved(recorder)['status'] == 'interrupted'


def test_schema_one_upgrades_without_inventing_old_first_output(tmp_path):
    store = WebPromptTimingStore(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute('''CREATE TABLE submissions (
            id TEXT PRIMARY KEY, client_id TEXT, thread_id TEXT, turn_id TEXT DEFAULT '', item_id TEXT DEFAULT '',
            submitted_at_ms INTEGER, received_at_ms INTEGER, result TEXT DEFAULT 'unconfirmed',
            reason_code TEXT DEFAULT '', epoch TEXT DEFAULT '', observation_id TEXT DEFAULT '',
            stages TEXT DEFAULT '[]', browser TEXT DEFAULT '{}', updated_at_ms INTEGER)''')
        db.execute('PRAGMA user_version=1')
        db.execute('INSERT INTO submissions(id,client_id,thread_id,submitted_at_ms,updated_at_ms) VALUES(?,?,?,?,?)',
                   (IDENTITY, 'doc', 'thread', STAMP, STAMP))
    record = store.detail(IDENTITY)
    assert record['submitted_at_ms'] == STAMP
    assert record['first_output'] == {'status': 'not_recorded', 'reason_code': ''}
    with sqlite3.connect(store.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2


class PromptOutputNotificationTests(WebRuntimeControllerHarness):
    def test_raw_observer_sees_first_delta_before_detached_projection(self):
        recorder = WebPromptTimingRecorder(WebPromptTimingStore(pathlib.Path(self.temp_dir.name)), 'epoch')
        unsubscribe = self.projection.subscribe_prompt_observations(recorder.observe_notification)
        try:
            trace = recorder.begin(IDENTITY, 'tab-1', 'thread-1', STAMP)
            trace.mark('app_server_rpc_started', input_mode='start')
            self.controller.handle_notification('turn/started', {'threadId': 'thread-1', 'turn': {'id': 'turn', 'items': []}})
            self.controller.handle_notification('item/started', {'threadId': 'thread-1', 'turnId': 'turn',
                'item': {'id': 'input', 'type': 'userMessage', 'clientId': f'focus-web:{IDENTITY}', 'content': []}})
            self.controller.handle_notification('item/reasoning/textDelta', {'threadId': 'thread-1', 'turnId': 'turn',
                'itemId': 'thinking', 'delta': 'one'})
            assert saved(recorder)['kind'] == 'thinking'
        finally:
            unsubscribe()
            recorder.close()
