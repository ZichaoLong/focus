"""Complete Q&A Markdown export for one Focus Web thread."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from bot.adapters.base import ThreadSnapshot, ThreadTurnsPage
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
from bot.web_runtime.projection import project_user_prompt_text
from bot.web_runtime.writer_workspace_coordinator import (
    require_web_client_id,
    require_web_thread_id,
)


SUMMARY_EXPORT_TIMEOUT_SECONDS = 30.0
SUMMARY_EXPORT_PAGE_LIMIT = 100
SUMMARY_EXPORT_MAX_PAGES = 100
SUMMARY_EXPORT_MAX_OUTPUT_BYTES = 32 * 1024 * 1024
SUMMARY_EXPORT_FILENAME = "codex-conversation-summary.md"
_TITLE = "# Codex conversation summary"


@dataclass(frozen=True, slots=True)
class WebThreadSummaryExportPorts:
    """Generation-pinned read ports; the exporter retains no thread data."""

    read_thread: Callable[..., ThreadSnapshot]
    list_thread_turns: Callable[..., ThreadTurnsPage]
    capture_connection_generation: Callable[[], int]
    run_if_connection_generation: Callable[[int, Callable[[], Any]], Any]


@dataclass(frozen=True, slots=True)
class WebThreadSummaryExportPreparation:
    client_id: str
    thread_id: str
    connection_generation: int
    deadline: float


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
    """Render each first text prompt and final reply without raw transcript items."""

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
    ) -> WebThreadSummaryExportPreparation:
        """Freeze the target and backend generation without reading history."""

        self._runtime_context_guard()
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
        markdown: bytes,
    ) -> bytes:
        """Reject only a replaced app-server connection, not unrelated UI events."""

        self._runtime_context_guard()
        if not isinstance(prepared, WebThreadSummaryExportPreparation):
            raise TypeError("prepared Web thread summary export is required")
        if not isinstance(markdown, bytes):
            raise TypeError("Web thread summary export must settle UTF-8 bytes")
        return self._ports.run_if_connection_generation(
            prepared.connection_generation,
            lambda: markdown,
        )

    def _execute(self, prepared: WebThreadSummaryExportPreparation) -> bytes:
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

        output = bytearray(_TITLE.encode("utf-8"))
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            page_count += 1
            page = self._ports.list_thread_turns(
                prepared.thread_id,
                cursor=cursor,
                limit=self._page_limit,
                sort_direction="asc",
                items_view="summary",
                timeout=self._remaining(prepared.deadline),
                expected_connection_generation=prepared.connection_generation,
            )
            self._remaining(prepared.deadline)
            if not isinstance(page, ThreadTurnsPage):
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex returned an invalid summary turn page",
                )
            if len(page.turns) > self._page_limit:
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex exceeded the requested summary turn page size",
                )
            for turn in page.turns:
                self._append_turn(output, turn)
            self._remaining(prepared.deadline)

            next_cursor = page.next_cursor
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor.strip():
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex returned an invalid summary turn cursor",
                )
            if next_cursor in seen_cursors or next_cursor == cursor:
                raise WebRuntimeError(
                    "Codex returned a non-progressing summary cursor. "
                    "No partial file was downloaded.",
                    code="thread_summary_export_cursor_loop",
                    status=502,
                    details={"thread_id": prepared.thread_id},
                )
            if page_count >= self._max_pages:
                raise WebRuntimeError(
                    "This conversation exceeds the browser export scan limit "
                    f"of {self._max_pages:,} history pages. "
                    "No partial file was downloaded; use fcodex /export for the full record.",
                    code="thread_summary_export_too_many_pages",
                    status=413,
                    details={"thread_id": prepared.thread_id},
                )
            if cursor is not None:
                seen_cursors.add(cursor)
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        self._append_bytes(output, b"\n")
        return bytes(output)

    def _append_turn(self, output: bytearray, turn: object) -> None:
        if not isinstance(turn, dict):
            raise CodexRpcProtocolError(
                "thread/turns/list",
                "Codex summary history contains a non-object turn",
            )
        items = turn.get("items")
        if not isinstance(items, list):
            raise CodexRpcProtocolError(
                "thread/turns/list",
                "Codex summary history contains a turn without items",
            )

        user_item: dict[str, Any] | None = None
        assistant_item: dict[str, Any] | None = None
        for item in items:
            if not isinstance(item, dict):
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex summary history contains a non-object item",
                )
            item_type = item.get("type")
            if item_type == "userMessage" and user_item is None:
                user_item = item
            elif item_type == "agentMessage":
                phase = item.get("phase")
                if phase not in (None, "final_answer", "commentary"):
                    raise CodexRpcProtocolError(
                        "thread/turns/list",
                        "Codex summary history contains an unknown agent message phase",
                    )
                if phase != "commentary":
                    assistant_item = item

        if user_item is not None:
            self._append_section(output, "User", self._user_text(user_item))
        if assistant_item is not None:
            raw_text = assistant_item.get("text")
            if not isinstance(raw_text, str):
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex summary history contains an invalid final answer",
                )
            text = raw_text.strip()
            if text:
                self._append_section(output, "Assistant", text)

    @staticmethod
    def _user_text(item: dict[str, Any]) -> str:
        content = item.get("content")
        if not isinstance(content, list):
            raise CodexRpcProtocolError(
                "thread/turns/list",
                "Codex summary history contains invalid user content",
            )
        parts: list[str] = []
        for entry in content:
            if not isinstance(entry, dict):
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex summary history contains invalid user content",
                )
            if entry.get("type") != "text":
                continue
            text = entry.get("text")
            if not isinstance(text, str):
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex summary history contains invalid user text",
                )
            try:
                text = project_user_prompt_text(
                    text,
                    reject_malformed_focus_envelope=True,
                )
            except ValueError as exc:
                raise CodexRpcProtocolError(
                    "thread/turns/list",
                    "Codex summary history contains a malformed Focus attachment prompt",
                ) from exc
            if normalized := text.strip():
                parts.append(normalized)
        return "\n\n".join(parts)

    def _append_section(self, output: bytearray, role: str, text: str) -> None:
        section = f"\n\n## {role}"
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
