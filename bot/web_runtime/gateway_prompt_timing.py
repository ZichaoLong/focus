"""Authenticated, payload-free evidence reads and browser observation sync."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import web

from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.gateway_request_decoder import decode_json_object
from bot.web_runtime.mutation_recovery import is_web_mutation_id
from bot.web_runtime.prompt_timing import PromptTimingTrace, WebPromptTimingRecorder

logger = logging.getLogger(__name__)

def valid_time(value: Any) -> bool:
    return type(value) is int and 0 < value <= 8_640_000_000_000_000


def decode_browser_records(body: dict[str, Any]) -> list[dict[str, Any]]:
    records = body.get('records')
    if set(body) != {'records'} or not isinstance(records, list) or len(records) > 32:
        raise WebRuntimeError('Invalid timing records.', code='invalid_prompt_timing')
    for record in records:
        if (not isinstance(record, dict) or set(record) != {'submission_id', 'thread_id', 'submitted_at_ms', 'browser'}
                or not is_web_mutation_id(record['submission_id']) or not valid_time(record['submitted_at_ms'])
                or not isinstance(record['thread_id'], str) or len(record['thread_id']) > 128):
            raise WebRuntimeError('Invalid timing identity.', code='invalid_prompt_timing')
        browser = record['browser']
        if not isinstance(browser, dict) or not set(browser) <= {'completed_at_ms', 'elapsed_ms', 'result', 'disconnects'}:
            raise WebRuntimeError('Invalid browser timing.', code='invalid_prompt_timing')
        for key, value in browser.items():
            if key == 'result':
                valid = isinstance(value, str) and value in ('succeeded', 'known_no_effect', 'outcome_unknown', 'pending')
            elif key == 'completed_at_ms':
                valid = valid_time(value)
            else:
                valid = type(value) in (int, float) and 0 <= value <= 86_400_000
            if not valid:
                raise WebRuntimeError('Invalid browser timing value.', code='invalid_prompt_timing')
    return records


class WebGatewayPromptTimingMixin:
    _prompt_timings: WebPromptTimingRecorder

    def _begin_prompt_timing(self, request: web.Request, client_id: str, thread_id: str,
                             mutation_id: str = '') -> PromptTimingTrace | None:
        identity = request.headers.get('X-Focus-Prompt-Id', '')
        stamp = request.headers.get('X-Focus-Submitted-At', '')
        if not identity and not stamp:
            return None
        if not is_web_mutation_id(identity) or (mutation_id and mutation_id != identity):
            raise WebRuntimeError('Invalid prompt timing identity.', code='invalid_prompt')
        try:
            submitted_at_ms = int(stamp)
            if not valid_time(submitted_at_ms) or str(submitted_at_ms) != stamp:
                raise ValueError('invalid timestamp')
        except ValueError as exc:
            raise WebRuntimeError('Invalid submission timestamp.', code='invalid_prompt') from exc
        try:
            return self._prompt_timings.begin(identity, client_id, thread_id, submitted_at_ms)
        except Exception:
            logger.warning('Prompt timing recorder unavailable; continuing submission', exc_info=True)
            return None

    async def _handle_prompt_timing(self, request: web.Request) -> web.Response:
        self._required_client_id(request)
        identity = request.match_info['submission_id']
        if not is_web_mutation_id(identity):
            raise WebRuntimeError('Invalid timing identity.', code='invalid_prompt_timing')
        try:
            result = await asyncio.to_thread(self._prompt_timings.detail, identity)
        except Exception as exc:
            raise WebRuntimeError('Timing storage unavailable.', code='prompt_timing_unavailable', status=503) from exc
        return web.json_response({'record': result}, headers={'Cache-Control': 'no-store'})

    async def _handle_prompt_timing_list(self, request: web.Request) -> web.Response:
        self._required_client_id(request)
        try:
            result = await asyncio.to_thread(self._prompt_timings.recent, request.match_info['thread_id'])
        except Exception as exc:
            raise WebRuntimeError('Timing storage unavailable.', code='prompt_timing_unavailable', status=503) from exc
        return web.json_response({'records': result}, headers={'Cache-Control': 'no-store'})

    async def _handle_prompt_timing_sync(self, request: web.Request) -> web.Response:
        client_id = self._required_client_id(request)
        records = decode_browser_records(await decode_json_object(request))
        async with self._client_operation(client_id):
            if self._required_client_id(request) != client_id:
                raise WebRuntimeError('Document replaced.', code='document_replaced', status=409)
            try:
                await asyncio.to_thread(self._prompt_timings.store.sync_browser, client_id, records)
            except Exception as exc:
                raise WebRuntimeError('Timing storage unavailable.', code='prompt_timing_unavailable', status=503) from exc
        return web.json_response({'accepted': True}, headers={'Cache-Control': 'no-store'})
