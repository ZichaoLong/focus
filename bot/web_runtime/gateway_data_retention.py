"""Authenticated access to the instance retention owner, outside RuntimeLoop."""
from __future__ import annotations

from aiohttp import web

from bot.data_retention_contract import DataRetentionPolicy
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.gateway_request_decoder import decode_json_object


class WebGatewayDataRetentionMixin:
    async def _retention_request(self, request, name, *args):
        client_id = self._required_client_id(request)
        callback = getattr(self._ports, name)
        if callback is None:
            raise WebRuntimeError('Data retention unavailable.', code='retention_unavailable', status=503)
        try:
            result = await self._document_request_to_thread(
                callback, request, client_id, *args, pass_client_id=False)
        except (ValueError, OSError) as exc:
            raise WebRuntimeError('Data retention storage unavailable.', code='retention_unavailable', status=503) from exc
        return web.json_response(result, headers={'Cache-Control': 'no-store'})

    async def _handle_data_retention_read(self, request: web.Request) -> web.Response:
        return await self._retention_request(request, 'data_retention_read')

    async def _handle_data_retention_update(self, request: web.Request) -> web.Response:
        body = await decode_json_object(request)
        try:
            if not body or not set(body) <= {'records_days', 'attachments_days'}:
                raise ValueError('Unknown retention setting')
            DataRetentionPolicy(**body)
        except (ValueError, TypeError) as exc:
            raise WebRuntimeError('Retention must be 7, 30 or 90 days.', code='invalid_retention') from exc
        return await self._retention_request(request, 'data_retention_update', body)

    async def _handle_data_prune(self, request: web.Request) -> web.Response:
        if await decode_json_object(request):
            raise WebRuntimeError('Cleanup takes no options.', code='invalid_retention')
        return await self._retention_request(request, 'data_prune')
