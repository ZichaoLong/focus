"""Thin authenticated HTTP handlers for bounded thread inspection."""

from __future__ import annotations

from typing import Any

from aiohttp import web

from bot.web_runtime import gateway_request_decoder as request_decoder
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.thread_inspection_wire import encode_thread_inspection_json
from bot.web_runtime.transcript_budget import TAIL_CONTEXT_BYTES, TAIL_CONTEXT_SOURCE_READS


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
        folded_version = request.headers.get("X-Focus-Folded-Tools")
        def allowance(header: str, maximum: int) -> int:
            raw = request.headers.get(header, str(maximum))
            if not raw.isascii() or not raw.isdecimal() or len(raw) > 6 or not 1 <= int(raw) <= maximum:
                raise WebRuntimeError("Invalid fill budget.", code="invalid_transcript_query", status=400)
            return int(raw)

        byte_limit = allowance("X-Focus-Fill-Bytes", TAIL_CONTEXT_BYTES) if fill else 0
        if fill and folded_version in {"1", "2"}:
            query["folded_tools_version"] = int(folded_version)
            if "X-Focus-Fill-Reads" in request.headers:
                query["fill_reads"] = allowance("X-Focus-Fill-Reads", TAIL_CONTEXT_SOURCE_READS)
        if request.headers.get("X-Focus-Reading-Window") == "1":
            query["include_reading_mark"] = True
        page = await self._staged_document_request_to_thread(
            self._ports.prepare_transcript_window, request, client_id,
            request.match_info["thread_id"], **query,
        )
        record_mark = page.pop("reading_mark", None)
        reads = page.pop("fill_reads", None)
        response = self._json_response(page)
        if fill and reads is not None:
            response.headers["X-Focus-Fill-Reads"] = str(reads)
            response.headers["X-Focus-Fill-Bytes"] = str(len(response.body))
        if record_mark:
            response.headers["X-Focus-Reading-Mark"] = record_mark
        # Cap the actual serialized mobile/browser response, including timing
        # enrichment and JSON escaping. Leave the cursor available for manual use.
        if fill and len(response.body) > byte_limit:
            raise WebRuntimeError("Load this history page manually.", code="transcript_fill_limit", status=409)
        return response

    async def _handle_mobile_record_status(self, request: web.Request) -> web.Response:
        client = self._required_client_id(request)
        body = await request_decoder.decode_json_object(request)
        session = self._request_admission.session(request)
        if body.get("scope") != session.mobile_read_scope:
            raise WebRuntimeError("Mobile record scope changed.", code="record_scope_changed", status=409)
        threads = body.get("threads")
        if (set(body) != {"scope", "threads"} or request.query or not isinstance(threads, list)
                or not 1 <= len(threads) <= 32
                or any(not isinstance(t, str) or not t.isprintable() or not 1 <= len(t) <= 256 for t in threads)
                or len(set(threads)) != len(threads)):
            raise WebRuntimeError("Invalid mobile record query.", code="invalid_record_query", status=400)
        if self._ports.mobile_record_states is None:
            raise WebRuntimeError("Mobile record verification unavailable.", code="record_status_unavailable", status=503)
        states = await self._document_request_to_thread(
            self._ports.mobile_record_states, request, client, threads, pass_client_id=False,
        )
        self._required_client_id(request)
        return self._json_response({"scope": session.mobile_read_scope, "states": states}, headers={"Cache-Control": "no-store"})

    async def _handle_mobile_records(self, request: web.Request) -> web.Response:
        client_id = self._required_client_id(request)
        query = request_decoder.decode_transcript_query(request.query)
        if request.query.keys() - {"cursor"}:
            raise WebRuntimeError("Invalid mobile record page.", code="invalid_transcript_query", status=400)
        page = await self._staged_document_request_to_thread(
            self._ports.prepare_transcript_window, request, client_id,
            request.match_info["thread_id"], cursor=query.get("cursor"), view="mobile_records",
            execute=self._ports.run_prepared_thread_read,
        )
        session = self._request_admission.session(request)
        # Non-authorizing, session-specific equality proof. A proxy label can be shared.
        return self._json_response({**page, "scope": session.mobile_read_scope}, headers={"Cache-Control": "no-store"})

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
