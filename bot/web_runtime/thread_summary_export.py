"""Complete Q&A Markdown export for one Focus Web thread."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from bot.adapters.base import ThreadItemsPage, ThreadSnapshot, ThreadTurnsPage
from bot.adapter_ingress_gate import (
    AdapterOutboundRequestBlocked,
    AdapterOutboundRequestEpochLost,
)
from bot.codex_protocol.client import (
    CodexRpcError,
    CodexRpcPreSendError,
    CodexRpcProtocolError,
    CodexRpcTransportError,
)
from bot.runtime_loop import RuntimeContextGuard
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.direct_thread_target_coordinator import (
    require_web_direct_thread_snapshot,
)
from bot.web_runtime.projection import (
    bounded_summary_prompt_text,
)
from bot.web_runtime.thread_export_selection import (
    EXPORT_TURN_PAGE_SIZE,
    SummaryExportSelection,
    decode_export_selection,
    export_qa,
    export_turn_identity,
    export_turn_items,
    require_exportable_turn,
)
from bot.web_runtime.writer_workspace_coordinator import (
    require_web_client_id,
    require_web_thread_id,
)


SUMMARY_EXPORT_TIMEOUT_SECONDS = 30.0
SUMMARY_EXPORT_PAGE_LIMIT = 100
SUMMARY_EXPORT_MAX_PAGES = 100
SUMMARY_EXPORT_MAX_OUTPUT_BYTES = 32 * 1024 * 1024
SUMMARY_EXPORT_OUTLINE_TITLE_LIMIT = 80
SUMMARY_EXPORT_FILENAME = "codex-conversation-summary.md"
_TITLE = "# Codex conversation summary"


@dataclass(frozen=True, slots=True)
class WebThreadSummaryExportPorts:
    """Generation-pinned read ports; the exporter retains no thread data."""

    read_thread: Callable[..., ThreadSnapshot]
    list_thread_turns: Callable[..., ThreadTurnsPage]
    list_thread_items: Callable[..., ThreadItemsPage]
    capture_connection_generation: Callable[[], int]
    run_if_connection_generation: Callable[[int, Callable[[], Any]], Any]


@dataclass(frozen=True, slots=True)
class WebThreadSummaryExportPreparation:
    client_id: str
    thread_id: str
    connection_generation: int
    deadline: float
    selection: SummaryExportSelection = SummaryExportSelection()
    cursor: str | None = None


def classify_thread_summary_export_error(exc: Exception) -> WebRuntimeError:
    """Map upstream failures without falling back to a full transcript read."""

    if isinstance(exc, WebRuntimeError):
        return exc
    details = {"fallback": "fcodex /export"}
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, CodexRpcPreSendError) and isinstance(exc.cause, TimeoutError)
    ):
        return WebRuntimeError(
            "The Q&A Markdown export did not finish within 30 seconds. "
            "No partial file was downloaded; use fcodex /export for the full record.",
            code="thread_summary_export_timeout",
            status=504,
            details=details,
        )
    if isinstance(exc, CodexRpcProtocolError):
        return WebRuntimeError(
            "Codex returned malformed summary history. No partial file was downloaded.",
            code="thread_summary_export_protocol_error",
            status=502,
            details=details,
        )
    if isinstance(exc, CodexRpcError) and exc.error.get("code") == -32601:
        return WebRuntimeError(
            "The connected Codex runtime does not provide the summary-history API "
            "required by browser export. "
            "Use fcodex /export for the full record.",
            code="thread_summary_export_upstream_unsupported",
            status=503,
            details=details,
        )
    if isinstance(
        exc,
        (
            AdapterOutboundRequestBlocked,
            AdapterOutboundRequestEpochLost,
            CodexRpcPreSendError,
            CodexRpcTransportError,
            CodexRpcError,
        ),
    ):
        return WebRuntimeError(
            "Q&A Markdown export is temporarily unavailable. "
            "No partial file was downloaded; use fcodex /export for the full record.",
            code="thread_summary_export_upstream_unavailable",
            status=503,
            details=details,
        )
    return WebRuntimeError(
        "Focus could not validate the Q&A Markdown export. "
        "No partial file was downloaded.",
        code="thread_summary_export_protocol_error",
        status=502,
        details=details,
    )


class WebThreadSummaryExportService:
    """Read and render whole or selected Q&A from persisted thread history."""

    def __init__(
        self,
        *,
        ports: WebThreadSummaryExportPorts,
        runtime_context_guard: RuntimeContextGuard,
        monotonic: Callable[[], float] = time.monotonic,
        timeout_seconds: float = SUMMARY_EXPORT_TIMEOUT_SECONDS,
        page_limit: int = SUMMARY_EXPORT_PAGE_LIMIT,
        max_pages: int = SUMMARY_EXPORT_MAX_PAGES,
        max_output_bytes: int = SUMMARY_EXPORT_MAX_OUTPUT_BYTES,
    ) -> None:
        if not isinstance(ports, WebThreadSummaryExportPorts):
            raise TypeError("Web thread summary export requires typed ports")
        if not callable(runtime_context_guard) or not callable(monotonic):
            raise TypeError("Web thread summary export requires guards and a clock")
        if float(timeout_seconds) <= 0:
            raise ValueError("summary export timeout must be positive")
        if int(page_limit) <= 0 or int(max_pages) <= 0:
            raise ValueError("summary export page limits must be positive")
        if int(max_output_bytes) <= 0:
            raise ValueError("summary export output limit must be positive")
        self._ports = ports
        self._runtime_context_guard = runtime_context_guard
        self._monotonic = monotonic
        self._timeout_seconds = float(timeout_seconds)
        self._page_limit = int(page_limit)
        self._max_pages = int(max_pages)
        self._max_output_bytes = int(max_output_bytes)

    def prepare(
        self,
        client_id: str,
        thread_id: str,
        *,
        selection: SummaryExportSelection = SummaryExportSelection(),
        cursor: str | None = None,
    ) -> WebThreadSummaryExportPreparation:
        """Freeze the target and backend generation without reading history."""

        self._runtime_context_guard()
        if not isinstance(selection, SummaryExportSelection):
            raise TypeError("typed summary export selection is required")
        decode_export_selection({"scope": selection.scope, "turn_ids": list(selection.turn_ids),
                                 "content": selection.content})
        if cursor is not None and (not isinstance(cursor, str) or not cursor
                                   or cursor != cursor.strip() or len(cursor) > 4096):
            raise WebRuntimeError("Invalid export directory cursor.", code="invalid_export_cursor")
        normalized_client_id = require_web_client_id(client_id)
        normalized_thread_id = require_web_thread_id(thread_id)
        try:
            connection_generation = self._ports.capture_connection_generation()
        except (AdapterOutboundRequestBlocked, AdapterOutboundRequestEpochLost) as exc:
            raise classify_thread_summary_export_error(exc) from exc
        return WebThreadSummaryExportPreparation(
            client_id=normalized_client_id,
            thread_id=normalized_thread_id,
            connection_generation=connection_generation,
            deadline=self._monotonic() + self._timeout_seconds,
            selection=selection,
            cursor=cursor,
        )

    def execute(self, prepared: WebThreadSummaryExportPreparation) -> bytes:
        """Read and render outside RuntimeLoop; either return all bytes or raise."""

        if not isinstance(prepared, WebThreadSummaryExportPreparation):
            raise TypeError("prepared Web thread summary export is required")
        try:
            return self._execute(prepared)
        except Exception as exc:
            error = classify_thread_summary_export_error(exc)
            if error is exc:
                raise
            raise error from exc

    def settle(
        self,
        prepared: WebThreadSummaryExportPreparation,
        markdown: bytes | dict[str, Any],
    ) -> bytes | dict[str, Any]:
        """Reject only a replaced app-server connection, not unrelated UI events."""

        self._runtime_context_guard()
        if not isinstance(prepared, WebThreadSummaryExportPreparation):
            raise TypeError("prepared Web thread summary export is required")
        if not isinstance(markdown, (bytes, dict)):
            raise TypeError("Web thread summary export must settle UTF-8 bytes")
        return self._ports.run_if_connection_generation(
            prepared.connection_generation,
            lambda: markdown,
        )

    def _snapshot(self, prepared: WebThreadSummaryExportPreparation) -> ThreadSnapshot:
        snapshot = self._ports.read_thread(
            prepared.thread_id,
            False,
            timeout=self._remaining(prepared.deadline),
            expected_connection_generation=prepared.connection_generation,
        )
        self._remaining(prepared.deadline)
        require_web_direct_thread_snapshot(
            snapshot,
            thread_id=prepared.thread_id,
            operation="export this conversation",
        )
        if snapshot.summary.ephemeral or snapshot.history_mode not in {
            "legacy",
            "paginated",
        }:
            raise WebRuntimeError(
                "This conversation has no verified persisted history to export.",
                code="thread_summary_export_unavailable",
                status=409,
                details={"thread_id": prepared.thread_id},
            )

        return snapshot

    def _execute(self, prepared: WebThreadSummaryExportPreparation) -> bytes:
        snapshot = self._snapshot(prepared)
        if prepared.selection.scope != "all" or prepared.selection.content == "prompts":
            return self._execute_selection(prepared, snapshot)

        output = bytearray(_TITLE.encode("utf-8"))
        cursor: str | None = None
        seen_cursors: set[str] = set()
        seen_turns: set[str] = set()
        outline_number = 0
        for _ in range(self._max_pages):
            page = self._turn_page(prepared, cursor, "asc", "summary", limit=self._page_limit)
            for turn in page.turns:
                identity, status = export_turn_identity(turn)
                if identity in seen_turns:
                    raise CodexRpcProtocolError("thread/turns/list", "Repeated turn during export")
                seen_turns.add(identity)
                if prepared.selection.content == "final_answers" and status != "completed":
                    continue
                if self._append_turn(output, turn, outline_number + 1, content=prepared.selection.content):
                    outline_number += 1
            self._remaining(prepared.deadline)
            cursor = self._next_cursor(page.next_cursor, cursor, seen_cursors)
            if cursor is None:
                break
        else:
            raise WebRuntimeError(
                "This conversation exceeds the browser export scan limit. No partial file was downloaded.",
                code="thread_summary_export_too_many_pages", status=413,
            )
        if prepared.selection.content == "final_answers" and not outline_number:
            raise self._missing_content()
        self._append_bytes(output, b"\n")
        return bytes(output)

    def execute_turns(self, prepared: WebThreadSummaryExportPreparation) -> dict[str, Any]:
        """Read one bounded directory page, independently of the chat window."""

        try:
            self._snapshot(prepared)
            page = self._turn_page(prepared, prepared.cursor, "desc", "summary")
            rows = []
            # The adapter normalizes every page to chronological order.
            for turn in reversed(page.turns):
                identity, status = export_turn_identity(turn)
                prompts, answer = export_qa(turn)
                if not prompts:
                    continue
                title, _ = bounded_summary_prompt_text(prompts[0] or "User prompt", limit=160)
                reply, _ = bounded_summary_prompt_text((answer or "") if status == "completed" else "", limit=240)
                rows.append({"turn_id": identity, "status": status,
                             "prompt": title, "answer": reply})
            self._next_cursor(page.next_cursor, prepared.cursor, set())
            return {"thread_id": prepared.thread_id, "turns": rows, "next_cursor": page.next_cursor}
        except Exception as exc:
            error = classify_thread_summary_export_error(exc)
            if error is exc:
                raise
            raise error from exc

    def _turn_page(
        self, prepared: WebThreadSummaryExportPreparation, cursor: str | None,
        direction: str, view: str, *, limit: int | None = None,
    ) -> ThreadTurnsPage:
        limit = limit or min(self._page_limit, EXPORT_TURN_PAGE_SIZE)
        page = self._ports.list_thread_turns(
            prepared.thread_id, cursor=cursor, limit=limit,
            sort_direction=direction, items_view=view,
            timeout=self._remaining(prepared.deadline),
            expected_connection_generation=prepared.connection_generation,
        )
        self._remaining(prepared.deadline)
        if not isinstance(page, ThreadTurnsPage) or len(page.turns) > limit:
            raise CodexRpcProtocolError("thread/turns/list", "Invalid export directory page")
        identities = [export_turn_identity(turn)[0] for turn in page.turns]
        if len(set(identities)) != len(identities):
            raise CodexRpcProtocolError("thread/turns/list", "Duplicate turn in export page")
        return page

    @staticmethod
    def _next_cursor(value: object, current: str | None, seen: set[str]) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value or value != value.strip():
            raise CodexRpcProtocolError("thread/turns/list", "Invalid export cursor")
        if value == current or value in seen:
            raise WebRuntimeError("Export history cursor did not advance. No partial file was downloaded.",
                                  code="thread_summary_export_cursor_loop", status=502)
        seen.add(value)
        return value

    def _execute_selection(
        self, prepared: WebThreadSummaryExportPreparation, snapshot: ThreadSnapshot,
    ) -> bytes:
        output = bytearray(_TITLE.encode("utf-8"))
        remaining = set(prepared.selection.turn_ids)
        all_turns = prepared.selection.scope == "all"
        latest = prepared.selection.scope == "last_turn"
        direction = "desc" if latest else "asc"
        cursor: str | None = None
        seen: set[str] = set()
        seen_turns: set[str] = set()
        count = 0
        page_limit = self._page_limit if snapshot.history_mode == "paginated" else min(self._page_limit, EXPORT_TURN_PAGE_SIZE)
        for _ in range(self._max_pages):
            page = self._turn_page(prepared, cursor, direction, "summary", limit=page_limit)
            next_cursor = self._next_cursor(page.next_cursor, cursor, seen)
            ordered = list(reversed(page.turns)) if latest else page.turns
            candidates = []
            for turn in ordered:
                identity, _status = export_turn_identity(turn)
                if identity in seen_turns:
                    raise CodexRpcProtocolError("thread/turns/list", "Repeated turn during export")
                seen_turns.add(identity)
                has_prompt = any(item.get("type") == "userMessage" for item in export_turn_items(turn))
                if ((latest or all_turns) and has_prompt) or identity in remaining:
                    candidates.append(turn)
                    if latest:
                        break
            if candidates and snapshot.history_mode == "legacy":
                # Legacy history has no item paging: hydrate only a matching,
                # bounded turn page using the exact upstream cursor and width.
                full = self._turn_page(prepared, cursor, direction, "full", limit=page_limit)
                by_id = {export_turn_identity(turn)[0]: turn for turn in full.turns}
                try:
                    candidates = [by_id[turn["id"]] for turn in candidates]
                except KeyError as exc:
                    raise self._missing_turns() from exc
            for turn in candidates:
                if snapshot.history_mode == "paginated":
                    turn = self._complete_turn(prepared, turn)
                if not all_turns:
                    require_exportable_turn(turn, prepared.selection.content)
                if self._append_turn(output, turn, count + 1, include_followups=True,
                                     content=prepared.selection.content):
                    count += 1
                remaining.discard(turn["id"])
            self._remaining(prepared.deadline)
            if count and ((all_turns and next_cursor is None) or latest or (not all_turns and not remaining)):
                self._append_bytes(output, b"\n")
                return bytes(output)
            if next_cursor is None:
                if all_turns:
                    raise self._missing_content()
                raise self._missing_turns()
            cursor = next_cursor
        raise WebRuntimeError("The chosen turns exceed the browser export scan limit. No partial file was downloaded.",
                              code="thread_summary_export_too_many_pages", status=413)

    def _complete_turn(
        self, prepared: WebThreadSummaryExportPreparation, turn: dict[str, Any],
    ) -> dict[str, Any]:
        identity, status = export_turn_identity(turn)
        if status != "completed" and prepared.selection.content != "prompts":
            require_exportable_turn(turn, prepared.selection.content)
        cursor: str | None = None
        seen: set[str] = set()
        seen_items: set[str] = set()
        # Retain only Q&A items, never tools/reasoning from the source pages.
        items: list[dict[str, Any]] = []
        content_bytes = 0
        for _ in range(self._max_pages):
            page = self._ports.list_thread_items(
                prepared.thread_id, turn_id=identity, cursor=cursor,
                limit=self._page_limit, sort_direction="asc",
                timeout=self._remaining(prepared.deadline),
                expected_connection_generation=prepared.connection_generation,
            )
            self._remaining(prepared.deadline)
            if not isinstance(page, ThreadItemsPage) or len(page.items) > self._page_limit:
                raise CodexRpcProtocolError("thread/items/list", "Invalid export item page")
            for entry in page.items:
                item = entry.item
                item_id = item.get("id")
                if entry.turn_id != identity or not isinstance(item_id, str) or not item_id or item_id in seen_items:
                    raise CodexRpcProtocolError("thread/items/list", "Export item identity mismatch")
                seen_items.add(item_id)
                if item.get("type") == "userMessage" or (
                    prepared.selection.content != "prompts" and item.get("type") == "agentMessage"
                ):
                    export_qa({"items": [item]}, include_followups=True)
                    if item.get("type") == "userMessage":
                        texts = [part["text"] for part in item["content"] if part.get("type") == "text"]
                        retained = {"id": item_id, "type": "userMessage",
                                    "content": [{"type": "text", "text": text} for text in texts]}
                    elif item.get("phase") == "final_answer":
                        texts = [item["text"]]
                        retained = {"id": item_id, "type": "agentMessage", "text": item["text"], "phase": item.get("phase")}
                    else:
                        continue
                    content_bytes += sum(len(text.encode("utf-8")) for text in texts)
                    if content_bytes > self._max_output_bytes:
                        raise WebRuntimeError("The chosen turn exceeds the export size limit. No partial file was downloaded.",
                                              code="thread_summary_export_too_large", status=413)
                    items.append(retained)
            cursor = self._next_cursor(page.next_cursor, cursor, seen)
            if cursor is None:
                return {**turn, "items": items}
        raise WebRuntimeError("The chosen turn exceeds the browser export scan limit. No partial file was downloaded.",
                              code="thread_summary_export_too_many_pages", status=413)

    @staticmethod
    def _missing_content() -> WebRuntimeError:
        return WebRuntimeError("There is no content of the chosen kind to export.",
                               code="thread_summary_export_missing_content", status=409)

    @staticmethod
    def _missing_turns() -> WebRuntimeError:
        return WebRuntimeError("The chosen turns are missing or this conversation has no question to export. "
                               "Refresh the selection; no partial file was downloaded.",
                               code="thread_summary_export_missing_turn", status=409)

    def _append_turn(
        self,
        output: bytearray,
        turn: object,
        outline_number: int,
        *,
        include_followups: bool = False,
        content: str = "qa",
    ) -> bool:
        prompts, assistant_text = export_qa(turn, include_followups=include_followups)
        user_text = "\n\n".join(prompts) if prompts else None
        if export_turn_identity(turn)[1] != "completed":
            assistant_text = None
        if content == "final_answers":
            user_text = None
        elif content == "prompts":
            assistant_text = None
            user_text = user_text or None
        if user_text is None and assistant_text is None:
            return False
        title_source = user_text or (
            "User prompt" if user_text is not None else "Assistant response"
        )
        title, _truncated = bounded_summary_prompt_text(
            title_source,
            limit=SUMMARY_EXPORT_OUTLINE_TITLE_LIMIT,
        )
        self._append_bytes(
            output,
            f"\n\n## {outline_number}. {title}".encode("utf-8"),
        )
        if user_text is not None:
            self._append_section(output, "User", user_text)
        if assistant_text is not None:
            self._append_section(output, "Assistant", assistant_text)
        return True

    def _append_section(self, output: bytearray, role: str, text: str) -> None:
        section = f"\n\n### {role}"
        if text:
            section += f"\n\n{text}"
        self._append_bytes(output, section.encode("utf-8"))

    def _append_bytes(self, output: bytearray, content: bytes) -> None:
        if len(output) + len(content) > self._max_output_bytes:
            raise WebRuntimeError(
                "The Q&A Markdown export exceeds 32 MiB. "
                "No partial file was downloaded; use fcodex /export for the full record.",
                code="thread_summary_export_too_large",
                status=413,
            )
        output.extend(content)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise TimeoutError("thread summary export exceeded its deadline")
        return remaining
