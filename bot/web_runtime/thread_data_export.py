"""Complete app-server item export for one Focus Web thread."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from bot.adapters.base import ThreadItemEntry, ThreadItemsPage, ThreadSnapshot
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
from bot.web_runtime.writer_workspace_coordinator import (
    require_web_client_id,
    require_web_thread_id,
)


THREAD_DATA_EXPORT_TIMEOUT_SECONDS = 120.0
THREAD_DATA_EXPORT_PAGE_LIMIT = 100
THREAD_DATA_EXPORT_MAX_PAGES = 1_000
THREAD_DATA_EXPORT_MAX_OUTPUT_BYTES = 256 * 1024 * 1024
THREAD_DATA_EXPORT_FILENAME = "codex-thread-data.jsonl"


@dataclass(frozen=True, slots=True)
class WebThreadDataExportPorts:
    """Generation-pinned read ports; the exporter retains no thread data."""

    read_thread: Callable[..., ThreadSnapshot]
    list_thread_items: Callable[..., ThreadItemsPage]
    capture_connection_generation: Callable[[], int]
    run_if_connection_generation: Callable[[int, Callable[[], Any]], Any]


@dataclass(frozen=True, slots=True)
class WebThreadDataExportPreparation:
    client_id: str
    thread_id: str
    connection_generation: int
    deadline: float


def classify_thread_data_export_error(exc: Exception) -> WebRuntimeError:
    """Map upstream failures without returning a partial JSONL document."""

    if isinstance(exc, WebRuntimeError):
        return exc
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, CodexRpcPreSendError) and isinstance(exc.cause, TimeoutError)
    ):
        return WebRuntimeError(
            "The thread data export did not finish within 120 seconds. "
            "No partial file was downloaded.",
            code="thread_data_export_timeout",
            status=504,
        )
    if isinstance(exc, CodexRpcProtocolError):
        return WebRuntimeError(
            "Codex returned malformed thread item data. "
            "No partial file was downloaded.",
            code="thread_data_export_protocol_error",
            status=502,
        )
    if isinstance(exc, CodexRpcError) and exc.error.get("code") == -32601:
        return WebRuntimeError(
            "The connected Codex runtime does not provide the thread-item API "
            "required by this export.",
            code="thread_data_export_upstream_unsupported",
            status=503,
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
            "Thread data export is temporarily unavailable. "
            "No partial file was downloaded.",
            code="thread_data_export_upstream_unavailable",
            status=503,
        )
    return WebRuntimeError(
        "Focus could not validate the thread data export. "
        "No partial file was downloaded.",
        code="thread_data_export_protocol_error",
        status=502,
    )


class WebThreadDataExportService:
    """Serialize every stored item returned by app-server as UTF-8 JSONL."""

    def __init__(
        self,
        *,
        ports: WebThreadDataExportPorts,
        runtime_context_guard: RuntimeContextGuard,
        monotonic: Callable[[], float] = time.monotonic,
        timeout_seconds: float = THREAD_DATA_EXPORT_TIMEOUT_SECONDS,
        page_limit: int = THREAD_DATA_EXPORT_PAGE_LIMIT,
        max_pages: int = THREAD_DATA_EXPORT_MAX_PAGES,
        max_output_bytes: int = THREAD_DATA_EXPORT_MAX_OUTPUT_BYTES,
    ) -> None:
        if not isinstance(ports, WebThreadDataExportPorts):
            raise TypeError("Web thread data export requires typed ports")
        if not callable(runtime_context_guard) or not callable(monotonic):
            raise TypeError("Web thread data export requires guards and a clock")
        if float(timeout_seconds) <= 0:
            raise ValueError("thread data export timeout must be positive")
        if int(page_limit) <= 0 or int(max_pages) <= 0:
            raise ValueError("thread data export page limits must be positive")
        if int(max_output_bytes) <= 0:
            raise ValueError("thread data export output limit must be positive")
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
    ) -> WebThreadDataExportPreparation:
        """Freeze the target and backend generation without reading history."""

        self._runtime_context_guard()
        normalized_client_id = require_web_client_id(client_id)
        normalized_thread_id = require_web_thread_id(thread_id)
        try:
            connection_generation = self._ports.capture_connection_generation()
        except (AdapterOutboundRequestBlocked, AdapterOutboundRequestEpochLost) as exc:
            raise classify_thread_data_export_error(exc) from exc
        return WebThreadDataExportPreparation(
            client_id=normalized_client_id,
            thread_id=normalized_thread_id,
            connection_generation=connection_generation,
            deadline=self._monotonic() + self._timeout_seconds,
        )

    def execute(self, prepared: WebThreadDataExportPreparation) -> bytes:
        """Read and encode off-loop; either return all bytes or raise."""

        if not isinstance(prepared, WebThreadDataExportPreparation):
            raise TypeError("prepared Web thread data export is required")
        try:
            return self._execute(prepared)
        except Exception as exc:
            error = classify_thread_data_export_error(exc)
            if error is exc:
                raise
            raise error from exc

    def settle(
        self,
        prepared: WebThreadDataExportPreparation,
        data: bytes,
    ) -> bytes:
        """Reject only a replaced app-server connection."""

        self._runtime_context_guard()
        if not isinstance(prepared, WebThreadDataExportPreparation):
            raise TypeError("prepared Web thread data export is required")
        if not isinstance(data, bytes):
            raise TypeError("Web thread data export must settle UTF-8 bytes")
        return self._ports.run_if_connection_generation(
            prepared.connection_generation,
            lambda: data,
        )

    def _execute(self, prepared: WebThreadDataExportPreparation) -> bytes:
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
            operation="export this thread's data",
        )
        if snapshot.summary.ephemeral or snapshot.history_mode != "paginated":
            raise WebRuntimeError(
                "This thread has no verified paginated item data to export.",
                code="thread_data_export_unavailable",
                status=409,
                details={"thread_id": prepared.thread_id},
            )

        output = bytearray()
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            page_count += 1
            page = self._ports.list_thread_items(
                prepared.thread_id,
                cursor=cursor,
                limit=self._page_limit,
                sort_direction="asc",
                timeout=self._remaining(prepared.deadline),
                expected_connection_generation=prepared.connection_generation,
            )
            self._remaining(prepared.deadline)
            if not isinstance(page, ThreadItemsPage):
                raise CodexRpcProtocolError(
                    "thread/items/list",
                    "Codex returned an invalid thread item page",
                )
            if len(page.items) > self._page_limit:
                raise CodexRpcProtocolError(
                    "thread/items/list",
                    "Codex exceeded the requested thread item page size",
                )
            for entry in page.items:
                self._append_entry(output, prepared.thread_id, entry)
            self._remaining(prepared.deadline)

            next_cursor = page.next_cursor
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor.strip():
                raise CodexRpcProtocolError(
                    "thread/items/list",
                    "Codex returned an invalid thread item cursor",
                )
            if next_cursor in seen_cursors or next_cursor == cursor:
                raise WebRuntimeError(
                    "Codex returned a non-progressing thread item cursor. "
                    "No partial file was downloaded.",
                    code="thread_data_export_cursor_loop",
                    status=502,
                    details={"thread_id": prepared.thread_id},
                )
            if page_count >= self._max_pages:
                raise WebRuntimeError(
                    "This thread exceeds the browser data export scan limit "
                    f"of {self._max_pages:,} item pages. "
                    "No partial file was downloaded.",
                    code="thread_data_export_too_many_pages",
                    status=413,
                    details={"thread_id": prepared.thread_id},
                )
            if cursor is not None:
                seen_cursors.add(cursor)
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        return bytes(output)

    def _append_entry(
        self,
        output: bytearray,
        thread_id: str,
        entry: object,
    ) -> None:
        if not isinstance(entry, ThreadItemEntry):
            raise CodexRpcProtocolError(
                "thread/items/list",
                "Codex returned an invalid thread item entry",
            )
        if not entry.turn_id or entry.turn_id != entry.turn_id.strip():
            raise CodexRpcProtocolError(
                "thread/items/list",
                "Codex returned an invalid thread item turn id",
            )
        item = entry.item
        if not isinstance(item, dict):
            raise CodexRpcProtocolError(
                "thread/items/list",
                "Codex returned a non-object thread item",
            )
        for field in ("id", "type"):
            value = item.get(field)
            if not isinstance(value, str) or not value or value != value.strip():
                raise CodexRpcProtocolError(
                    "thread/items/list",
                    f"Codex returned a thread item with an invalid {field}",
                )
        try:
            line = (
                json.dumps(
                    {
                        "threadId": thread_id,
                        "turnId": entry.turn_id,
                        "item": item,
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode("utf-8")
                + b"\n"
            )
        except (TypeError, ValueError, UnicodeError) as exc:
            raise CodexRpcProtocolError(
                "thread/items/list",
                "Codex returned a thread item that cannot be encoded as JSON",
            ) from exc
        if len(output) + len(line) > self._max_output_bytes:
            raise WebRuntimeError(
                "The thread data export exceeds 256 MiB. "
                "No partial file was downloaded.",
                code="thread_data_export_too_large",
                status=413,
            )
        output.extend(line)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise TimeoutError("thread data export exceeded its deadline")
        return remaining
