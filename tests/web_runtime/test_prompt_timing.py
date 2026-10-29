"""Display evidence must never become submission or replay authority."""
from __future__ import annotations

import copy
import pathlib
import uuid
from dataclasses import replace

import pytest

from bot.codex_protocol.client import CodexRpcTransportError
from bot.stores.web_prompt_timing_store import WebPromptTimingStore
from bot.web_runtime.gateway_prompt_timing import decode_browser_records
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.prompt_timing import WebPromptTimingRecorder
from bot.web_runtime.projection import project_turns
from bot.web_runtime.transcript_window import project_transcript_item
from tests.web_runtime.gateway_harness import WebGatewayHarness
from tests.web_runtime.harness import WebRuntimeControllerHarness

STAMP = 1_790_000_000_123
IDENTITY = '11111111-1111-4111-8111-111111111111'


def browser_record(**kwargs):
    return dict(submission_id=IDENTITY, thread_id='thread-1', submitted_at_ms=STAMP, browser={}, **kwargs)


def user_row(**kwargs):
    return dict(role='user', rawTurnId='turn-1', itemId='item-1', clientUserMessageId=f'focus-web:{IDENTITY}', **kwargs)


@pytest.fixture
def recorder(tmp_path):
    recorder = WebPromptTimingRecorder(WebPromptTimingStore(tmp_path), 'epoch-1')
    yield recorder
    recorder.close()


def test_reload_sync_cannot_claim_service_receipt_or_change_original_time(recorder):
    record = browser_record()
    record['browser'] = {'result': 'succeeded'}
    recorder.store.sync_browser('replaced-document', [record])
    detail = recorder.store.detail(IDENTITY)
    assert detail['result'] == 'unconfirmed'
    assert detail['received_at_ms'] is None
    rows = [user_row()]
    recorder.store.attach('thread-1', rows)
    assert 'promptTiming' not in rows[0]
    trace = recorder.begin(IDENTITY, 'original-document', 'thread-1', STAMP)
    trace.mark('settled', result='outcome_unknown')
    recorder.flush()
    original = recorder.store.detail(IDENTITY)
    record['submitted_at_ms'] += 10
    record['browser'] = {'result': 'known_no_effect'}
    recorder.store.sync_browser('different-document', [record])
    assert recorder.store.detail(IDENTITY) == original
    assert recorder.begin(IDENTITY, 'original-document', 'thread-1', STAMP + 10) is None
    assert original['result'] == 'outcome_unknown'


def test_exact_item_mapping_survives_restart_and_does_not_follow_fork(recorder, tmp_path):
    recorder.begin(IDENTITY, 'document', 'thread-1', STAMP)
    recorder.flush()
    recorder.store.attach('thread-1', [user_row()])
    reopened = WebPromptTimingStore(tmp_path)
    row = user_row()
    del row['clientUserMessageId']
    reopened.attach('thread-1', [row])
    assert row['promptTiming'] == {'submissionId': IDENTITY, 'submittedAtMs': STAMP}
    fork_row = user_row()
    reopened.attach('fork-thread', [fork_row])
    assert 'promptTiming' not in fork_row
    wrong_item = {**user_row(), 'itemId': 'different'}
    reopened.attach('thread-1', [wrong_item])
    assert 'promptTiming' not in wrong_item
    assert reopened.detail(IDENTITY)['item_id'] == 'item-1'
    restarted = WebPromptTimingRecorder(reopened, 'epoch-2')
    try:
        trace = restarted.begin(IDENTITY, 'document', 'thread-1', STAMP)
        trace.mark('settled', result='known_no_effect')
        restarted.flush()
        assert not trace.accepted
        assert reopened.detail(IDENTITY)['result'] == 'succeeded'
        assert reopened.detail(IDENTITY)['epoch'] == 'epoch-1'
    finally:
        restarted.close()


def test_live_observations_are_bounded_and_do_not_write_per_token(tmp_path):
    changed = []
    recorder = WebPromptTimingRecorder(WebPromptTimingStore(tmp_path), 'epoch', lambda *args: changed.append(args))
    try:
        recorder.begin(IDENTITY, 'doc', 'thread-1', STAMP)
        recorder.flush()
        event = {'type': 'thread_delta', 'thread_id': 'thread-1', 'detail': {'item_turns': [user_row()]}}
        projected = recorder.observe_event(event)
        assert projected['detail']['item_turns'][0]['promptTiming']['submittedAtMs'] == STAMP
        assert 'promptTiming' not in event['detail']['item_turns'][0]
        recorder.flush()
        original = recorder.store.detail(IDENTITY)
        for _ in range(1000):
            recorder.observe_event(event)
        recorder.flush()
        assert recorder.store.detail(IDENTITY) == original
        assert len(changed) == 2
        fork = recorder.observe_event({**event, 'thread_id': 'fork-thread'})
        assert 'promptTiming' not in fork['detail']['item_turns'][0]
        recorder.flush()
        assert recorder.store.detail(IDENTITY)['thread_id'] == 'thread-1'
        recorder.delete_thread('thread-1')
        recorder.flush()
        assert recorder.store.detail(IDENTITY) is None
    finally:
        recorder.close()
        recorder.close()


def test_incomplete_attempt_remains_unconfirmed_after_restart(recorder, tmp_path):
    recorder.begin(IDENTITY, 'doc', 'thread-1', STAMP)
    recorder.flush()
    detail = WebPromptTimingStore(tmp_path).detail(IDENTITY)
    assert detail['result'] == 'unconfirmed'
    assert [stage['name'] for stage in detail['stages']] == ['service_received']


def test_browser_sync_keeps_completed_evidence_over_stale_incomplete_snapshot(recorder):
    record = browser_record()
    record['browser'] = {'result': 'outcome_unknown', 'completed_at_ms': STAMP + 10, 'elapsed_ms': 20}
    recorder.store.sync_browser('doc-a', [record])
    recorder.store.sync_browser('doc-b', [browser_record()])
    assert recorder.store.detail(IDENTITY)['browser'] == record['browser']


@pytest.mark.parametrize('bad', [
    {'text': 'must not be persisted'}, {'result': 'succeeded'}, {'received_at_ms': STAMP},
    {'browser': {'elapsed_ms': float('nan')}}, {'browser': {'disconnects': -1}},
])
def test_sync_rejects_input_payload_and_service_claims(bad):
    with pytest.raises(WebRuntimeError):
        decode_browser_records({'records': [{**browser_record(), **bad}]})


def test_user_item_time_is_distinct_from_whole_turn_time():
    items = [dict(id=f'user-{i}', type='userMessage', clientId=f'focus-web:{uuid.uuid4()}',
                  content=[{'type': 'text', 'text': 'identical'}]) for i in range(2)]
    projected = project_turns([{'id': 'turn', 'startedAt': 123, 'items': items}])
    assert all(row['createdAt'] is None for row in projected if row['role'] == 'user')
    for item, stamp in zip(items, [123_000, 999_000]):
        row = project_transcript_item('turn', item, started_at_ms=stamp)[0]
        assert row['codexRecordedAtMs'] == stamp
        assert row['clientUserMessageId'] == item['clientId']
    assert 'codexRecordedAtMs' not in project_transcript_item('turn', items[0])[0]


class PromptTimingEffectTests(WebRuntimeControllerHarness):
    def test_corrupt_storage_does_not_change_effect_or_result(self):
        store = WebPromptTimingStore(pathlib.Path(self.temp_dir.name))
        store.path.write_bytes(b'corrupt database')
        recorder = WebPromptTimingRecorder(store, 'epoch')
        try:
            trace = recorder.begin(IDENTITY, 'tab-1', 'thread-1', STAMP)
            prepared = replace(self.prepare_web_prompt('tab-1', 'thread-1', text='one input', mutation_id=IDENTITY), timing=trace)
            result = self.controller.run_prepared_prompt(prepared)
            recorder.flush()
            assert result['status'] == 'succeeded'
            assert len(self.fake.started) == 1
            assert len(self.fake.steered) == 0
        finally:
            recorder.close()

    def test_transport_failure_keeps_unknown_result_and_stages(self):
        store = WebPromptTimingStore(pathlib.Path(self.temp_dir.name))
        recorder = WebPromptTimingRecorder(store, 'epoch')
        try:
            self.fake.start_error = CodexRpcTransportError('turn/start', {'code': -32000, 'message': 'lost'})
            trace = recorder.begin(IDENTITY, 'tab-1', 'thread-1', STAMP)
            prepared = replace(self.prepare_web_prompt('tab-1', 'thread-1', text='one input', mutation_id=IDENTITY), timing=trace)
            result = self.controller.run_prepared_prompt(prepared)
            recorder.flush()
            detail = store.detail(IDENTITY)
            assert detail['result'] == result['status'] == 'outcome_unknown'
            assert 'app_server_rpc_started' in [stage['name'] for stage in detail['stages']]
            assert 'app_server_rpc_returned' not in [stage['name'] for stage in detail['stages']]
        finally:
            recorder.close()

    def test_new_thread_first_prompt_keeps_exact_client_identity(self):
        store = WebPromptTimingStore(pathlib.Path(self.temp_dir.name))
        recorder = WebPromptTimingRecorder(store, 'epoch')
        try:
            trace = recorder.begin(IDENTITY, 'tab-1', '', STAMP)
            result = self.controller.start_thread('tab-1', text='first input', timing=trace)
            recorder.flush()
            assert result['accepted']
            assert self.fake.started[-1]['client_user_message_id'] == f'focus-web:{IDENTITY}'
            assert store.detail(IDENTITY)['thread_id'] == result['thread_id']
            assert store.detail(IDENTITY)['result'] == 'succeeded'
        finally:
            recorder.close()


class PromptTimingGatewayTests(WebGatewayHarness):
    async def test_authenticated_diagnostics_never_dispatch_effect_ports(self):
        await self._authenticate()
        document = await self._register_document(resume_client_id='time-a', incarnation_id='doc-a')
        headers = self._client_headers(document)
        before = copy.copy(self.calls)
        async with self.session.post(f'{self.endpoint}/api/prompt-timings', headers=headers,
                                     json={'records': [browser_record()]}) as response:
            assert response.status == 200
        async with self.session.get(f'{self.endpoint}/api/prompt-timings/{IDENTITY}', headers=headers) as response:
            detail = (await response.json())['record']
            assert detail['submitted_at_ms'] == STAMP
            assert detail['result'] == 'unconfirmed'
            assert detail['received_at_ms'] is None
        async with self.session.get(f'{self.endpoint}/api/threads/thread-1/prompt-timings', headers=headers) as response:
            assert len((await response.json())['records']) == 1
        assert self.calls == before
        async with self.session.get(f'{self.endpoint}/api/prompt-timings/{IDENTITY}') as response:
            assert response.status != 200
        async with self.session.delete(f'{self.endpoint}/api/threads/thread-1', headers=headers,
                                     json={'confirmation': 'thread-1'}) as response:
            assert response.status == 200
        self.gateway._prompt_timings.flush()
        assert self.gateway._prompt_timings.store.detail(IDENTITY) is None
