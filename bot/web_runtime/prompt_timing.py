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
from typing import Any

from bot.stores.web_prompt_timing_store import WebPromptTimingStore

logger = logging.getLogger(__name__)


class PromptTimingTrace:
    """Small bounded in-memory observations; mark never performs disk I/O."""

    def __init__(self, value: dict[str, Any], write: Callable[[dict[str, Any]], None]) -> None:
        self._value = {**value, 'turn_id': '', 'result': 'unconfirmed', 'reason_code': '', 'stages': []}
        self._write = write
        self._start = time.monotonic()
        self._lock = threading.RLock()
        self.accepted = False

    @property
    def submission_id(self) -> str:
        return self._value['submission_id']

    def belongs_to(self, thread_id: str) -> bool:
        with self._lock:
            return self._value['thread_id'] in ('', thread_id)

    def mark(self, name: str, *, thread_id: str = '', turn_id: str = '', result: str = '', reason: str = '') -> None:
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
            value['updated_at_ms'] = int(time.time() * 1000)
            if len(value['stages']) < 20 and not any(stage['name'] == name for stage in value['stages']):
                value['stages'].append({'name': name, 'at_ms': value['updated_at_ms'],
                                        'elapsed_ms': round((time.monotonic() - self._start) * 1000, 3)})
            self._write(copy.deepcopy(value))

    def summary(self) -> dict[str, Any]:
        return {'submissionId': self.submission_id, 'submittedAtMs': self._value['submitted_at_ms']}


def mark_prompt(trace: PromptTimingTrace | None, name: str, **kwargs: Any) -> None:
    if trace is not None:
        try:
            trace.mark(name, **kwargs)
        except Exception:
            logger.warning('Prompt observation unavailable; submission semantics unchanged', exc_info=True)


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
                 'epoch': self.epoch, 'observation_id': str(uuid.uuid4())}
        trace = PromptTimingTrace(value, lambda snapshot: self.enqueue(self._write, snapshot))
        with self._lock:
            if submission_id in self._traces:
                return None
            self._traces[submission_id] = trace
            while len(self._traces) > 256:
                self._traces.popitem(last=False)
        self.enqueue(self._receive, trace, value)
        mark_prompt(trace, 'service_received')
        return trace

    def _receive(self, trace: PromptTimingTrace, value: dict[str, Any]) -> None:
        trace.accepted = self.store.receive(value)

    def _write(self, snapshot: dict[str, Any]) -> None:
        updated = self.store.update(snapshot)
        if updated and self._changed and snapshot['stages'][-1]['name'] in {
            'service_received', 'app_server_rpc_started', 'codex_observed', 'settled'
        }:
            self._changed(snapshot['submission_id'], snapshot['thread_id'])

    def observe_event(self, event: dict[str, Any]) -> dict[str, Any]:
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
        self.enqueue(self.store.delete_thread, thread_id)
