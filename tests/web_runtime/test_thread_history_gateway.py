"""Gateway admission regressions for bounded thread-history reads."""

from bot.web_runtime.contract import WebRuntimeError
from tests.web_runtime.gateway_harness import WebGatewayHarness


def _raise_summary_export_too_large() -> bytes:
    raise WebRuntimeError(
        "No partial file was downloaded.",
        code="thread_summary_export_too_large",
        status=413,
    )


def _raise_thread_data_export_too_large() -> bytes:
    raise WebRuntimeError(
        "No partial file was downloaded.",
        code="thread_data_export_too_large",
        status=413,
    )


class ThreadHistoryGatewayTests(WebGatewayHarness):
    async def test_thread_data_export_downloads_one_complete_jsonl_response(
        self,
    ) -> None:
        await self._authenticate()
        document = await self._register_document(
            resume_client_id="data-export-client",
            incarnation_id="data-export-document",
        )
        prepared_calls: list[tuple[str, str]] = []

        def prepare(client_id: str, thread_id: str):
            prepared_calls.append((client_id, thread_id))
            return object()

        data = (
            b'{"threadId":"thread-1","turnId":"turn-1",'
            b'"item":{"id":"item-1","type":"commandExecution"}}\n'
        )
        self.gateway._ports.prepare_export_thread_data = prepare
        self.gateway._ports.run_prepared_thread_data_export = lambda _prepared: data
        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/export-data",
            headers=self._client_headers(
                document,
                include_origin=False,
                include_csrf=False,
            ),
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), data)
            self.assertEqual(response.content_type, "application/x-ndjson")
            self.assertEqual(response.charset, "utf-8")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(
                response.headers["Content-Disposition"],
                'attachment; filename="codex-thread-data.jsonl"',
            )
        self.assertEqual(prepared_calls, [(document["client_id"], "thread-1")])

    async def test_thread_data_export_failure_never_starts_a_partial_download(
        self,
    ) -> None:
        await self._authenticate()
        document = await self._register_document(
            resume_client_id="data-export-failure-client",
            incarnation_id="data-export-failure-document",
        )
        self.gateway._ports.run_prepared_thread_data_export = lambda _prepared: (
            _raise_thread_data_export_too_large()
        )
        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/export-data",
            headers=self._client_headers(
                document,
                include_origin=False,
                include_csrf=False,
            ),
        ) as response:
            self.assertEqual(response.status, 413)
            self.assertNotIn("Content-Disposition", response.headers)
            payload = await response.json()
        self.assertEqual(payload["error"]["code"], "thread_data_export_too_large")

    async def test_summary_export_downloads_one_complete_markdown_response(
        self,
    ) -> None:
        await self._authenticate()
        document = await self._register_document(
            resume_client_id="summary-export-client",
            incarnation_id="summary-export-document",
        )
        prepared_calls: list[tuple[str, str]] = []

        def prepare(client_id: str, thread_id: str):
            prepared_calls.append((client_id, thread_id))
            return object()

        markdown = "# Codex conversation summary\n\n## User\n\n你好\n".encode()
        self.gateway._ports.prepare_export_thread_summary = prepare
        self.gateway._ports.run_prepared_thread_summary_export = (
            lambda _prepared: markdown
        )
        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/export-summary",
            headers=self._client_headers(
                document,
                include_origin=False,
                include_csrf=False,
            ),
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), markdown)
            self.assertEqual(response.content_type, "text/markdown")
            self.assertEqual(response.charset, "utf-8")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(
                response.headers["Content-Disposition"],
                'attachment; filename="codex-conversation-summary.md"',
            )
        self.assertEqual(prepared_calls, [(document["client_id"], "thread-1")])

    async def test_summary_export_failure_never_starts_a_partial_download(self) -> None:
        await self._authenticate()
        document = await self._register_document(
            resume_client_id="summary-export-failure-client",
            incarnation_id="summary-export-failure-document",
        )
        self.gateway._ports.run_prepared_thread_summary_export = lambda _prepared: (
            _raise_summary_export_too_large()
        )
        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/export-summary",
            headers=self._client_headers(
                document,
                include_origin=False,
                include_csrf=False,
            ),
        ) as response:
            self.assertEqual(response.status, 413)
            self.assertNotIn("Content-Disposition", response.headers)
            payload = await response.json()
        self.assertEqual(payload["error"]["code"], "thread_summary_export_too_large")

    async def test_history_page_admits_only_exact_items_view(self) -> None:
        await self._authenticate()
        document = await self._register_document(
            resume_client_id="history-view-client",
            incarnation_id="history-view-document",
        )
        headers = self._client_headers(document)

        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/turns"
            "?cursor=cursor-1&items_view=summary",
            headers=headers,
        ) as response:
            self.assertEqual(response.status, 200)
            payload = await response.json()
        self.assertEqual(payload["cursor"], "cursor-1")
        self.assertEqual(payload["items_view"], "summary")
        self.assertEqual(payload["turn_limit"], 10)

        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/turns?items_view=summary",
            headers=headers,
        ) as response:
            self.assertEqual(response.status, 200)
            payload = await response.json()
        self.assertEqual(payload["cursor"], "")
        self.assertEqual(payload["items_view"], "summary")

        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/turns?cursor=cursor-2",
            headers=headers,
        ) as response:
            self.assertEqual(response.status, 200)
            payload = await response.json()
        self.assertEqual(payload["items_view"], "full")

        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/turns"
            "?cursor=cursor-20&items_view=summary&turn_limit=20",
            headers=headers,
        ) as response:
            self.assertEqual(response.status, 200)
            payload = await response.json()
        self.assertEqual(payload["turn_limit"], 20)

        calls = 0

        def count_history_calls(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            return {}

        self.gateway._ports.prepare_list_older_turns = count_history_calls
        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1/turns"
            "?cursor=cursor-3&items_view=compact",
            headers=headers,
        ) as response:
            self.assertEqual(response.status, 400)
            payload = await response.json()
        self.assertEqual(payload["error"]["code"], "invalid_items_view")
        self.assertEqual(calls, 0)

    async def test_recent_and_history_turn_limit_fail_closed(self) -> None:
        await self._authenticate()
        document = await self._register_document(
            resume_client_id="turn-limit-client",
            incarnation_id="turn-limit-document",
        )
        headers = self._client_headers(document)

        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1?turn_limit=5",
            headers=headers,
        ) as response:
            self.assertEqual(response.status, 200)
            payload = await response.json()
        self.assertEqual(payload["turn_limit"], 5)

        async with self.session.get(
            f"{self.endpoint}/api/threads/thread-1?turn_limit=10",
            headers=headers,
        ) as response:
            self.assertEqual(response.status, 200)
            payload = await response.json()
        self.assertEqual(payload["turn_limit"], 10)

        for query in (
            "turn_limit=",
            "turn_limit=40",
            "turn_limit=%2010%20",
            "turn_limit=5&turn_limit=20",
        ):
            async with self.session.get(
                f"{self.endpoint}/api/threads/thread-1/turns?items_view=summary&{query}",
                headers=headers,
            ) as response:
                self.assertEqual(response.status, 400, query)
                payload = await response.json()
            self.assertEqual(payload["error"]["code"], "invalid_turn_limit", query)
