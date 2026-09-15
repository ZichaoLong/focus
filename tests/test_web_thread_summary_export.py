import unittest

from bot.adapters.base import ThreadSnapshot, ThreadSummary, ThreadTurnsPage
from bot.adapter_ingress_gate import AdapterOutboundRequestBlocked
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.thread_summary_export import (
    WebThreadSummaryExportPorts,
    WebThreadSummaryExportService,
)
from bot.web_runtime.thread_read_projection import project_thread_action_capabilities


def _snapshot(
    *, ephemeral: bool = False, history_mode: str = "paginated"
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
        )
    )


class ThreadSummaryExportTests(unittest.TestCase):
    def test_export_capability_is_read_only_and_requires_persisted_root_history(self) -> None:
        summary = _snapshot().summary
        available = project_thread_action_capabilities(
            "client-1",
            summary,
            interaction_lease=None,
            document_connected=False,
            archived=True,
        )
        self.assertTrue(available["export"])

        summary.ephemeral = True
        unavailable = project_thread_action_capabilities(
            "client-1",
            summary,
            interaction_lease=None,
            document_connected=True,
        )
        self.assertFalse(unavailable["export"])

        summary.ephemeral = False
        summary.history_mode = None
        without_history = project_thread_action_capabilities(
            "client-1",
            summary,
            interaction_lease=None,
            document_connected=True,
        )
        self.assertFalse(without_history["export"])

        summary.history_mode = "paginated"
        summary.source = "subAgent"
        summary.subagent_kind = "threadSpawn"
        child = project_thread_action_capabilities(
            "client-1",
            summary,
            interaction_lease=None,
            document_connected=True,
        )
        self.assertFalse(child["export"])

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

        def list_turns(thread_id, **kwargs):
            calls.append((thread_id, dict(kwargs)))
            return pages[kwargs["cursor"]]

        generation_checks = []

        def run_if_generation(generation, callback):
            generation_checks.append(generation)
            return callback()

        service = WebThreadSummaryExportService(
            ports=WebThreadSummaryExportPorts(
                read_thread=read_thread or (lambda *_args, **_kwargs: _snapshot()),
                list_thread_turns=list_turns,
                capture_connection_generation=capture_generation,
                run_if_connection_generation=run_if_generation,
            ),
            runtime_context_guard=lambda: None,
            monotonic=clock,
            timeout_seconds=30,
            page_limit=page_limit,
            max_pages=max_pages,
            max_output_bytes=max_output_bytes,
        )
        return service, calls, generation_checks

    def test_exports_all_pages_in_order_with_only_prompts_and_final_answers(
        self,
    ) -> None:
        pages = {
            None: ThreadTurnsPage(
                turns=[
                    {
                        "id": "turn-1",
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "\n".join(
                                            [
                                                "[[focus.attachments.v1]]",
                                                '[{"path":"secret attachment path"}]',
                                                "[[/focus.attachments.v1]]",
                                                "secret attachment instructions",
                                                "[[focus.user_request]]",
                                                " First prompt ",
                                            ]
                                        ),
                                    },
                                    {"type": "image", "url": "secret-image"},
                                ],
                            },
                            {
                                "type": "hookPrompt",
                                "fragments": [{"text": "secret hook prompt"}],
                            },
                            {"type": "reasoning", "content": ["secret reasoning"]},
                            {
                                "type": "commandExecution",
                                "output": "secret tool output",
                            },
                            {
                                "type": "agentMessage",
                                "phase": "commentary",
                                "text": "secret commentary",
                            },
                            {
                                "type": "agentMessage",
                                "phase": "final_answer",
                                "text": " Answer one ",
                            },
                        ],
                    },
                    {
                        "id": "turn-2",
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "Still running"}],
                            },
                            {
                                "type": "agentMessage",
                                "phase": "commentary",
                                "text": "not final",
                            },
                        ],
                    },
                ],
                next_cursor="page-2",
            ),
            "page-2": ThreadTurnsPage(
                turns=[
                    {
                        "id": "turn-3",
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [
                                    {"type": "text", "text": "Second"},
                                    {"type": "text", "text": "paragraph"},
                                ],
                            },
                            {"type": "agentMessage", "text": "Legacy final"},
                        ],
                    }
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
        markdown = service.execute(prepared)
        self.assertEqual(service.settle(prepared, markdown), markdown)

        self.assertEqual(
            markdown.decode(),
            "# Codex conversation summary"
            "\n\n## User\n\nFirst prompt"
            "\n\n## Assistant\n\nAnswer one"
            "\n\n## User\n\nStill running"
            "\n\n## User\n\nSecond\n\nparagraph"
            "\n\n## Assistant\n\nLegacy final\n",
        )
        self.assertNotIn(b"secret", markdown)
        self.assertEqual(len(read_calls), 1)
        self.assertEqual(read_calls[0][0:2], ("thread-1", False))
        self.assertEqual(read_calls[0][2]["expected_connection_generation"], 7)
        self.assertEqual([call[1]["cursor"] for call in calls], [None, "page-2"])
        for _thread_id, kwargs in calls:
            self.assertEqual(kwargs["items_view"], "summary")
            self.assertEqual(kwargs["sort_direction"], "asc")
            self.assertEqual(kwargs["limit"], 2)
            self.assertEqual(kwargs["expected_connection_generation"], 7)
        self.assertEqual(generation_checks, [7])

    def test_rejects_a_cursor_loop_without_returning_bytes(self) -> None:
        pages = {
            None: ThreadTurnsPage(turns=[], next_cursor="again"),
            "again": ThreadTurnsPage(turns=[], next_cursor="again"),
        }
        service, _calls, _checks = self._service(pages)
        prepared = service.prepare("client-1", "thread-1")
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(prepared)
        self.assertEqual(raised.exception.code, "thread_summary_export_cursor_loop")

    def test_rejects_more_pages_instead_of_truncating(self) -> None:
        pages = {None: ThreadTurnsPage(turns=[], next_cursor="more")}
        service, _calls, _checks = self._service(pages, max_pages=1)
        prepared = service.prepare("client-1", "thread-1")
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(prepared)
        self.assertEqual(raised.exception.code, "thread_summary_export_too_many_pages")

    def test_rejects_oversize_markdown_instead_of_truncating(self) -> None:
        pages = {
            None: ThreadTurnsPage(
                turns=[
                    {
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [{"type": "text", "text": "large prompt"}],
                            }
                        ]
                    }
                ]
            )
        }
        service, _calls, _checks = self._service(pages, max_output_bytes=30)
        prepared = service.prepare("client-1", "thread-1")
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(prepared)
        self.assertEqual(raised.exception.code, "thread_summary_export_too_large")

    def test_rejects_malformed_focus_attachment_envelope_without_leaking_it(
        self,
    ) -> None:
        pages = {
            None: ThreadTurnsPage(
                turns=[
                    {
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "[[focus.attachments.v1]]\nsecret path",
                                    }
                                ],
                            }
                        ]
                    }
                ]
            )
        }
        service, _calls, _checks = self._service(pages)
        prepared = service.prepare("client-1", "thread-1")
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(prepared)
        self.assertEqual(
            raised.exception.code,
            "thread_summary_export_protocol_error",
        )

    def test_rejects_deadline_and_unpersisted_history_without_fallback(self) -> None:
        now = [0.0]

        def read_thread(*_args, **_kwargs):
            now[0] = 31.0
            return _snapshot()

        service, _calls, _checks = self._service(
            {},
            clock=lambda: now[0],
            read_thread=read_thread,
        )
        prepared = service.prepare("client-1", "thread-1")
        with self.assertRaises(WebRuntimeError) as raised:
            service.execute(prepared)
        self.assertEqual(raised.exception.code, "thread_summary_export_timeout")

        unavailable, _calls, _checks = self._service(
            {},
            read_thread=lambda *_args, **_kwargs: _snapshot(ephemeral=True),
        )
        prepared = unavailable.prepare("client-1", "thread-1")
        with self.assertRaises(WebRuntimeError) as raised:
            unavailable.execute(prepared)
        self.assertEqual(raised.exception.code, "thread_summary_export_unavailable")

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
            "thread_summary_export_upstream_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
