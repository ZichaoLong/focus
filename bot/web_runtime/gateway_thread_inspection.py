"""Thin authenticated HTTP handlers for bounded thread inspection."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from bot.web_runtime import gateway_request_decoder as request_decoder
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.thread_inspection_wire import encode_thread_inspection_json


_TAIL_CONTEXT_PAGE_BYTES = 128 * 1024


def _inspection_json_response(payload: Any) -> web.Response:
    return web.Response(
        body=encode_thread_inspection_json(payload),
        content_type="application/json",
        charset="utf-8",
    )


class WebGatewayThreadInspectionMixin:
    """Route admitted inspection reads through the Gateway document barrier."""

    _ports: Any

    async def _handle_thread_transcript(self, request: web.Request) -> web.Response:
        client_id = self._required_client_id(request)
        query = request_decoder.decode_transcript_query(request.query)
        fill = query.pop("fill", None)
        response = self._json_response(await self._staged_document_request_to_thread(
            self._ports.prepare_transcript_window, request, client_id,
            request.match_info["thread_id"], **query,
        ))
        # Cap the actual serialized mobile/browser response, including timing
        # enrichment and JSON escaping. Leave the cursor available for manual use.
        if fill and len(response.body) > _TAIL_CONTEXT_PAGE_BYTES:
            raise WebRuntimeError("Load this history page manually.", code="transcript_fill_limit", status=409)
        return response

    async def _handle_thread_tool_detail(self, request: web.Request) -> web.Response:
        client_id = self._required_client_id(request)
        view, change_index, cursor = request_decoder.decode_tool_detail_query(
            request.query
        )
        return _inspection_json_response(
            await self._staged_document_request_to_thread(
                self._ports.prepare_tool_detail,
                request,
                client_id,
                request.match_info["thread_id"],
                request.match_info["turn_id"],
                request.match_info["item_id"],
                view=view,
                change_index=change_index,
                cursor=cursor,
            )
        )

    async def _handle_thread_conversation_search(
        self,
        request: web.Request,
    ) -> web.Response:
        client_id = self._required_client_id(request)
        query, cursor = request_decoder.decode_conversation_search_query(request.query)
        return _inspection_json_response(
            await self._staged_document_request_to_thread(
                self._ports.prepare_conversation_search,
                request,
                client_id,
                request.match_info["thread_id"],
                query=query,
                cursor=cursor,
            )
        )
