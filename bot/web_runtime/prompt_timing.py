"""Passive prompt observations, isolated from effect/result authority."""

from __future__ import annotations

import copy
import logging
import queue
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bot.stores.web_prompt_timing_store import WebPromptTimingStore

logger = logging.getLogger(__name__)


class PromptTimingTrace:
    """Small bounded in-memory observations; mark never performs disk I/O."""

    def __init__(self, value: dict[str, Any], write: Callable[[dict[str, Any], bool], None],
                 lock: threading.RLock) -> None:
        self._value = {**value, 'turn_id': '', 'result': 'unconfirmed', 'reason_code': '', 'stages': []}
        self._write = write
        self._start = time.monotonic()
        self._lock = lock
        self._rpc_started_at: float | None = None
        self._output_turn_id = ''
        self.accepted = False

    @property
    def submission_id(self) -> str:
        return self._value['submission_id']

    def belongs_to(self, thread_id: str) -> bool:
        with self._lock:
            return self._value['thread_id'] in ('', thread_id)

    def mark(self, name: str, *, thread_id: str = '', turn_id: str = '', result: str = '', reason: str = '',
             input_mode: str = '') -> None:
        with self._lock:
            value = self._value
            if thread_id and not self.belongs_to(thread_id):
                return
            if (any(stage['name'] == name for stage in value['stages'])
                    and (not result or result == value['result'])
                    and (not thread_id or thread_id == value['thread_id'])):
                return
            if thread_id:
                value['thread_id'] = thread_id
            if turn_id:
                value['turn_id'] = turn_id
            if result and value['result'] != 'succeeded':
                value['result'] = result
            if reason:
                value['reason_code'] = reason[:128]
            if name == 'app_server_rpc_started':
                self._rpc_started_at = time.monotonic()
                if input_mode == 'steer' and value['first_output']['status'] == 'pending':
                    value['first_output'] = {'status': 'unassociated', 'reason_code': 'steered_input'}
            if name == 'settled' and result == 'known_no_effect' and value['first_output']['status'] == 'pending':
                value['first_output'] = {'status': 'not_observed', 'reason_code': 'submission_no_effect'}
            value['updated_at_ms'] = int(time.time() * 1000)
            if len(value['stages']) < 20 and not any(stage['name'] == name for stage in value['stages']):
                value['stages'].append({'name': name, 'at_ms': value['updated_at_ms'],
                                        'elapsed_ms': round((time.monotonic() - self._start) * 1000, 3)})
            self._write(copy.deepcopy(value), name in {
                'service_received', 'app_server_rpc_started', 'codex_observed', 'settled',
            })

    def finish_output(self, status: str, reason: str) -> None:
        with self._lock:
            if self._value['first_output']['status'] != 'pending':
                return
            self._value['first_output'] = {'status': status, 'reason_code': reason}
            self._value['updated_at_ms'] = int(time.time() * 1000)
            self._write(copy.deepcopy(self._value), True)

    def bind_output(self, turn_id: str, started_at: float) -> bool:
        with self._lock:
            if self._value['first_output']['status'] != 'pending':
                return False
            if self._rpc_started_at is None or self._rpc_started_at > started_at:
                self.finish_output('unassociated', 'turn_started_before_submission')
                return False
            self._output_turn_id = turn_id
            return True

    def observe_output(self, turn_id: str, output: dict[str, Any]) -> None:
        with self._lock:
            if self._output_turn_id != turn_id or self._value['first_output']['status'] != 'pending':
                return
            self._value['first_output'] = {
                'status': 'observed', 'at_ms': output['at_ms'],
                'elapsed_ms': round(max(0, output['monotonic'] - self._start) * 1000, 3),
                'turn_id': turn_id, 'item_id': output['item_id'], 'kind': output['kind'],
            }
            self._value['updated_at_ms'] = int(time.time() * 1000)
            self._write(copy.deepcopy(self._value), True)

    def summary(self) -> dict[str, Any]:
        return {'submissionId': self.submission_id, 'submittedAtMs': self._value['submitted_at_ms']}


def mark_prompt(trace: PromptTimingTrace | None, name: str, **kwargs: Any) -> None:
    if trace is not None:
        try:
            trace.mark(name, **kwargs)
        except Exception:
            logger.warning('Prompt observation unavailable; submission semantics unchanged', exc_info=True)


@dataclass
class _OutputTurn:
    started_at: float
    first_input_item_id: str = ''
    submission_id: str = ''
    first_output: dict[str, Any] | None = None


class WebPromptTimingRecorder:
    """One bounded disk writer; corruption/overload degrades diagnostics only."""

    def __init__(self, store: WebPromptTimingStore, epoch: str,
                 changed: Callable[[str, str], None] | None = None) -> None:
        self.store = store
        self.epoch = epoch
        self._changed = changed
        self._queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...]] | None] = queue.Queue(512)
        self._traces: OrderedDict[str, PromptTimingTrace] = OrderedDict()
        self._observed: OrderedDict[tuple[str, str, str], None] = OrderedDict()
        self._output_turns: OrderedDict[tuple[str, str], _OutputTurn] = OrderedDict()
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._closed = False

    def enqueue(self, callback: Callable[..., Any], *args: Any) -> None:
        with self._lock:
            if self._closed:
                return
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name='web-prompt-evidence', daemon=True)
                self._worker.start()
            try:
                self._queue.put_nowait((callback, args))
            except queue.Full:
                logger.warning('Prompt timing observation queue full; diagnostic evidence incomplete')

    def _run(self) -> None:
        while (work := self._queue.get()) is not None:
            try:
                work[0](*work[1])
            except Exception:
                logger.warning('Prompt timing storage unavailable; submission semantics unchanged', exc_info=True)
            finally:
                self._queue.task_done()
        self._queue.task_done()

    def flush(self) -> None:
        self._queue.join()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._interrupt_outputs('service_stopped')
            self._closed = True
            worker = self._worker
        if worker is not None:
            # Never block shutdown on an overloaded diagnostics queue.
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    pass
                self._queue.put_nowait(None)
            worker.join(timeout=5)

    def begin(self, submission_id: str, client_id: str, thread_id: str, submitted_at_ms: int) -> PromptTimingTrace | None:
        value = {'submission_id': submission_id, 'client_id': client_id, 'thread_id': thread_id,
                 'submitted_at_ms': submitted_at_ms, 'received_at_ms': int(time.time() * 1000),
                 'epoch': self.epoch, 'observation_id': str(uuid.uuid4()),
                 'first_output': {'status': 'pending', 'reason_code': ''}}
        trace = PromptTimingTrace(value, lambda snapshot, notify: self.enqueue(self._write, snapshot, notify), self._lock)
        with self._lock:
            if submission_id in self._traces:
                return None
            self._traces[submission_id] = trace
            while len(self._traces) > 256:
                _, evicted = self._traces.popitem(last=False)
                evicted.finish_output('interrupted', 'observation_evicted')
        self.enqueue(self._receive, trace, value)
        mark_prompt(trace, 'service_received')
        return trace

    def _receive(self, trace: PromptTimingTrace, value: dict[str, Any]) -> None:
        trace.accepted = self.store.receive(value)

    def _write(self, snapshot: dict[str, Any], notify: bool) -> None:
        updated = self.store.update(snapshot)
        if updated and self._changed and notify:
            self._changed(snapshot['submission_id'], snapshot['thread_id'])

    def prune(self, before: float):
        # Active traces remain protected while writes drain outside RuntimeLoop.
        with self._lock:
            protected = tuple(key for key, trace in self._traces.items()
                              if trace._value['result'] == 'unconfirmed'
                              or trace._value['first_output']['status'] == 'pending')
        return self.store.prune(before, protected_ids=protected)

    def detail(self, submission_id: str) -> dict[str, Any] | None:
        record = self.store.detail(submission_id)
        return self._read_observation(record) if record else None

    def recent(self, thread_id: str) -> list[dict[str, Any]]:
        return [self._read_observation(record) for record in self.store.recent(thread_id)]

    def _read_observation(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            trace = self._traces.get(record['submission_id'])
            if record['first_output']['status'] == 'pending' and (
                self._closed or record['epoch'] != self.epoch or trace is None or not trace.accepted
            ):
                record['first_output'] = {'status': 'interrupted', 'reason_code': 'observation_unavailable'}
            elif record['first_output']['status'] == 'pending' and trace and record['result'] == 'succeeded' and not trace._output_turn_id:
                record['first_output'] = {'status': 'unassociated', 'reason_code': 'initial_input_not_observed'}
        return record

    def _interrupt_outputs(self, reason: str, thread_id: str = '') -> None:
        for trace in self._traces.values():
            if not thread_id or trace.belongs_to(thread_id):
                trace.finish_output('interrupted', reason)
        self._output_turns = OrderedDict((key, value) for key, value in self._output_turns.items()
                                         if thread_id and key[0] != thread_id)

    def observe_notification(self, method: str, params: dict[str, Any]) -> None:
        """Record first live content before projection can coalesce notifications."""
        thread_id = str(params.get('threadId') or '')
        if not thread_id:
            return
        with self._lock:
            if self._closed:
                return
            if method in {'thread/closed', 'thread/reverted', 'thread/archived', 'thread/deleted'} or (
                method == 'thread/status/changed' and (params.get('status') or {}).get('type') == 'notLoaded'
            ):
                self._interrupt_outputs(method, thread_id)
                return
            turn = params.get('turn') or {}
            turn_id = str(turn.get('id') or '') if method in {'turn/started', 'turn/completed'} else str(params.get('turnId') or '')
            if not turn_id:
                return
            key = (thread_id, turn_id)
            if method == 'turn/started' and key not in self._output_turns:
                if not any(trace.belongs_to(thread_id) and trace._rpc_started_at is not None
                           and trace._value['first_output']['status'] == 'pending' for trace in self._traces.values()):
                    return
                self._output_turns[key] = _OutputTurn(time.monotonic())
                while len(self._output_turns) > 256:
                    _, evicted = self._output_turns.popitem(last=False)
                    trace = self._traces.get(evicted.submission_id)
                    if trace:
                        trace.finish_output('interrupted', 'turn_observation_evicted')
            observation = self._output_turns.get(key)
            if method in {'item/started', 'item/completed'}:
                self._observe_item(thread_id, turn_id, observation, params.get('item') or {})
            elif method in {'turn/started', 'turn/completed'}:
                for item in turn.get('items') or []:
                    self._observe_item(thread_id, turn_id, observation, item)
                if method == 'turn/completed':
                    for trace in self._traces.values():
                        if trace.belongs_to(thread_id) and trace._output_turn_id == turn_id:
                            trace.finish_output('not_observed', 'turn_ended_without_output')
                    self._output_turns.pop(key, None)
            elif method in {'item/agentMessage/delta', 'item/reasoning/summaryTextDelta', 'item/reasoning/textDelta'}:
                if isinstance(params.get('delta'), str) and params['delta']:
                    kind = 'text' if method == 'item/agentMessage/delta' else 'thinking'
                    self._observe_output(turn_id, observation, str(params.get('itemId') or ''), kind)

    def _observe_item(self, thread_id: str, turn_id: str, observation: _OutputTurn | None, item: dict[str, Any]) -> None:
        item_id = str(item.get('id') or '')
        if not item_id:
            return
        if item.get('type') == 'userMessage':
            if observation and not observation.first_input_item_id:
                observation.first_input_item_id = item_id
            client_id = str(item.get('clientId') or '')
            trace = self._traces.get(client_id.removeprefix('focus-web:')) if client_id.startswith('focus-web:') else None
            if trace is None or not trace.belongs_to(thread_id):
                return
            if observation is None:
                trace.finish_output('unassociated', 'not_observed_initial_input')
            elif observation.first_input_item_id != item_id:
                trace.finish_output('unassociated', 'additional_turn_input')
            elif observation.first_output is not None and not observation.submission_id:
                trace.finish_output('unassociated', 'output_preceded_input')
            elif trace.bind_output(turn_id, observation.started_at):
                observation.submission_id = trace.submission_id
                if observation.first_output:
                    trace.observe_output(turn_id, observation.first_output)
        elif item.get('type') == 'agentMessage' and isinstance(item.get('text'), str) and item['text']:
            self._observe_output(turn_id, observation, item_id, 'text')
        elif item.get('type') == 'reasoning' and any(
            isinstance(part, str) and part for field in ('summary', 'content') for part in (item.get(field) or [])
        ):
            self._observe_output(turn_id, observation, item_id, 'thinking')

    def _observe_output(self, turn_id: str, observation: _OutputTurn | None, item_id: str, kind: str) -> None:
        if observation is None or observation.first_output is not None or not item_id:
            return
        observation.first_output = {'at_ms': int(time.time() * 1000), 'monotonic': time.monotonic(),
                                    'item_id': item_id, 'kind': kind}
        trace = self._traces.get(observation.submission_id)
        if trace:
            trace.observe_output(turn_id, observation.first_output)

    def observe_event(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get('type') == 'backend_disconnected':
            with self._lock:
                self._interrupt_outputs('app_server_disconnected')
        detail = event.get('detail') or {}
        rows = detail.get('item_turns', detail.get('turns', []))
        users = [row for row in rows if row.get('role') == 'user']
        if not users:
            return event
        detail = dict(detail)
        event = {**event, 'detail': detail}
        rows = [dict(row) if row.get('role') == 'user' else row for row in rows]
        detail['item_turns' if 'item_turns' in detail else 'turns'] = rows
        fresh = []
        for row in rows:
            if row.get('role') != 'user':
                continue
            identity = str(row.get('clientUserMessageId') or '').removeprefix('focus-web:')
            with self._lock:
                trace = self._traces.get(identity)
                key = (event.get('thread_id', ''), row.get('rawTurnId', ''), row.get('itemId', ''))
                if identity and key not in self._observed:
                    fresh.append(row)
                    self._observed[key] = None
                    while len(self._observed) > 512:
                        self._observed.popitem(last=False)
            if trace and trace.belongs_to(event.get('thread_id', '')):
                if trace.accepted:
                    row['promptTiming'] = trace.summary()
                mark_prompt(trace, 'codex_observed', thread_id=event.get('thread_id', ''),
                           turn_id=row.get('rawTurnId', ''), result='succeeded')
        if fresh:
            self.enqueue(self.store.attach, event.get('thread_id', ''), copy.deepcopy(fresh))
        return event

    def enrich(self, payload: dict[str, Any]) -> dict[str, Any]:
        thread_id = payload.get('thread_id') or (payload.get('thread') or {}).get('id')
        rows = payload.get('turns')
        if thread_id and isinstance(rows, list):
            try:
                self.store.attach(thread_id, rows)
            except Exception:
                logger.warning('Prompt time summary unavailable', exc_info=True)
        return payload

    def delete_thread(self, thread_id: str) -> None:
        with self._lock:
            self._traces = OrderedDict((key, trace) for key, trace in self._traces.items()
                                       if trace._value['thread_id'] != thread_id)
            self._output_turns = OrderedDict((key, value) for key, value in self._output_turns.items() if key[0] != thread_id)
        self.enqueue(self.store.delete_thread, thread_id)
