import json
import unittest

from bot.adapters.base import (
    ThreadItemEntry,
    ThreadItemsPage,
    ThreadSnapshot,
    ThreadSummary,
)
from bot.adapter_ingress_gate import AdapterOutboundRequestBlocked
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.thread_data_export import (
    WebThreadDataExportPorts,
    WebThreadDataExportService,
)


def _snapshot(
    *,
    ephemeral: bool = False,
    history_mode: str = "paginated",
    subagent_kind: str | None = None,
) -> ThreadSnapshot:
    return ThreadSnapshot(
        summary=ThreadSummary(
            thread_id="thread-1",
            cwd="/work",
            name="Conversation",
            preview="Prompt",
            created_at=1,
            updated_at=2,
            source="appServer",
            status="idle",
            ephemeral=ephemeral,
            history_mode=history_mode,
            subagent_kind=subagent_kind,
        )
    )


class ThreadDataExportTests(unittest.TestCase):
    def _service(
        self,
        pages,
        *,
        clock=lambda: 0.0,
        read_thread=None,
        capture_generation=lambda: 7,
        page_limit: int = 2,
        max_pages: int = 10,
        max_output_bytes: int = 1024 * 1024,
    ):
        calls = []

        def list_items(thread_id, **kwargs):
            calls.append((thread_id, dict(kwargs)))
            return pages[kwargs["cursor"]]

        generation_checks = []

        def run_if_generation(generation, callback):
            generation_checks.append(generation)
            return callback()

        service = WebThreadDataExportService(
            ports=WebThreadDataExportPorts(
                read_thread=read_thread or (lambda *_args, **_kwargs: _snapshot()),
                list_thread_items=list_items,
                capture_connection_generation=capture_generation,
                run_if_connection_generation=run_if_generation,
            ),
            runtime_context_guard=lambda: None,
            monotonic=clock,
            timeout_seconds=120,
            page_limit=page_limit,
            max_pages=max_pages,
            max_output_bytes=max_output_bytes,
        )
        return service, calls, generation_checks

    def test_exports_all_item_pages_in_order_without_projecting_unknown_fields(
        self,
    ) -> None:
        tool_item = {
            "id": "item-1",
            "type": "commandExecution",
            "command": "printf hello",
            "aggregatedOutput": "完整工具输出\n",
            "exitCode": 0,
            "futureField": {"nested": [1, True, None]},
        }
        pages = {
            None: ThreadItemsPage(
                items=[ThreadItemEntry(turn_id="turn-1", item=tool_item)],
                next_cursor="page-2",
            ),
            "page-2": ThreadItemsPage(
                items=[
                    ThreadItemEntry(
                        turn_id="turn-2",
                        item={
                            "id": "item-2",
                            "type": "agentMessage",
                            "text": "最终回答",
                            "phase": "final_answer",
                        },
                    )
                ]
            ),
        }
        read_calls = []

        def read_thread(thread_id, include_turns, **kwargs):
            read_calls.append((thread_id, include_turns, dict(kwargs)))
            return _snapshot()

        service, calls, generation_checks = self._service(
            pages,
            read_thread=read_thread,
        )

        prepared = service.prepare("client-1", "thread-1")
        data = service.execute(prepared)
        self.assertEqual(service.settle(prepared, data), data)

        records = [json.loads(line) for line in data.splitlines()]
        self.assertEqual(
            records,
            [
                {"threadId": "thread-1", "turnId": "turn-1", "item": tool_item},
                {
                    "threadId": "thread-1",
                    "turnId": "turn-2",
                    "item": pages["page-2"].items[0].item,
                },
            ],
        )
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(len(read_calls), 1)
        self.assertEqual(read_calls[0][0:2], ("thread-1", False))
        self.assertEqual(read_calls[0][2]["expected_connection_generation"], 7)
        self.assertEqual([call[1]["cursor"] for call in calls], [None, "page-2"])
        for thread_id, kwargs in calls:
            self.assertEqual(thread_id, "thread-1")
            self.assertEqual(kwargs["sort_direction"], "asc")
            self.assertEqual(kwargs["limit"], 2)
            self.assertEqual(kwargs["expected_connection_generation"], 7)
        self.assertEqual(generation_checks, [7])

    def test_rejects_cursor_loop_and_page_limit_instead_of_truncating(self) -> None:
        looping = {
            None: ThreadItemsPage(next_cursor="again"),
            "again": ThreadItemsPage(next_cursor="again"),
        }
        service, _calls, _checks = self._service(looping)
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(service.prepare("client-1", "thread-1"))
        self.assertEqual(raised.exception.code, "thread_data_export_cursor_loop")

        service, _calls, _checks = self._service(
            {None: ThreadItemsPage(next_cursor="more")},
            max_pages=1,
        )
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(service.prepare("client-1", "thread-1"))
        self.assertEqual(raised.exception.code, "thread_data_export_too_many_pages")

    def test_rejects_oversize_output_instead_of_returning_partial_jsonl(self) -> None:
        pages = {
            None: ThreadItemsPage(
                items=[
                    ThreadItemEntry(
                        turn_id="turn-1",
                        item={"id": "item-1", "type": "agentMessage", "text": "large"},
                    )
                ]
            )
        }
        service, _calls, _checks = self._service(pages, max_output_bytes=20)
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(service.prepare("client-1", "thread-1"))
        self.assertEqual(raised.exception.code, "thread_data_export_too_large")

    def test_rejects_malformed_entries_as_upstream_protocol_errors(self) -> None:
        pages = {
            None: ThreadItemsPage(
                items=[
                    ThreadItemEntry(
                        turn_id="turn-1",
                        item={"id": "item-1", "type": "agentMessage", "bad": object()},
                    )
                ]
            )
        }
        service, _calls, _checks = self._service(pages)
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(service.prepare("client-1", "thread-1"))
        self.assertEqual(raised.exception.code, "thread_data_export_protocol_error")

    def test_rejects_deadline_and_non_paginated_history(self) -> None:
        now = [0.0]

        def read_thread(*_args, **_kwargs):
            now[0] = 121.0
            return _snapshot()

        service, _calls, _checks = self._service(
            {},
            clock=lambda: now[0],
            read_thread=read_thread,
        )
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(service.prepare("client-1", "thread-1"))
        self.assertEqual(raised.exception.code, "thread_data_export_timeout")

        for snapshot in (_snapshot(ephemeral=True), _snapshot(history_mode="legacy")):
            with self.subTest(snapshot=snapshot):
                service, _calls, _checks = self._service(
                    {},
                    read_thread=lambda *_args, _snapshot=snapshot, **_kwargs: _snapshot,
                )
                with self.assertRaises(WebRuntimeError) as raised:
                    service.execute(service.prepare("client-1", "thread-1"))
                self.assertEqual(
                    raised.exception.code, "thread_data_export_unavailable"
                )

        service, calls, _checks = self._service(
            {},
            read_thread=lambda *_args, **_kwargs: _snapshot(
                subagent_kind="threadSpawn"
            ),
        )
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(service.prepare("client-1", "thread-1"))
        self.assertEqual(raised.exception.code, "subagent_detail_only")
        self.assertEqual(calls, [])

    def test_prepare_reports_backend_replacement_as_temporarily_unavailable(
        self,
    ) -> None:
        def blocked_generation() -> int:
            raise AdapterOutboundRequestBlocked("backend reset")

        service, _calls, _checks = self._service(
            {},
            capture_generation=blocked_generation,
        )
        with self.assertRaises(WebRuntimeError) as raised:
            service.prepare("client-1", "thread-1")
        self.assertEqual(
            raised.exception.code,
            "thread_data_export_upstream_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
