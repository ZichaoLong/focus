import asyncio
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, CookieJar

from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.summary_pdf import SummaryPdfJobs
from tests.web_runtime.gateway_harness import WebGatewayHarness


class PdfGatewayTests(WebGatewayHarness):
    async def test_preview_is_immutable_session_bound_and_idempotent(self):
        await self._authenticate()
        doc = await self._register_document(incarnation_id="print-source", resume_client_id="print")
        export = self.endpoint + "/api/threads/thread-1/export-summary"
        selection = {"scope": "selected", "content": "final_answers", "turn_ids": ["chosen"]}
        headers = self._client_headers(doc)
        self.gateway._ports.run_prepared_thread_summary_export = lambda _: b"Authorized answer"
        async with self.session.post(export, headers=headers, json=selection) as response:
            self.assertEqual(response.status, 200)
            self.assertNotIn("X-Focus-Pdf-Preview", response.headers)
        async with self.session.post(export, headers={**headers, "X-Focus-Print-Preview": "1"}, json=selection) as response:
            token = response.headers["X-Focus-Pdf-Preview"]
            self.assertEqual(await response.read(), b"Authorized answer")
        self.gateway._ports.run_prepared_thread_summary_export = lambda _: b"Different selection"
        calls = []

        async def render(job, source, output, work):
            calls.append((source, job.title))
            output.write_bytes(b"%PDF-mocked")
            job.engine = "basic"

        self.gateway._pdf_jobs._render = render
        self.gateway._pdf_jobs.lock_path = self.root / "pdf.lock"
        url = self.endpoint + "/api/pdf-previews/" + token + "/jobs/" + "a" * 32
        body = {"title": "Edited title", "lang": "zh-CN"}
        standalone = {"Origin": self.endpoint, "X-Focus-Web-Csrf": doc["csrf_token"]}
        async with self.session.post(url, headers={"Origin": self.endpoint}, json=body) as denied:
            self.assertEqual(denied.status, 403)
        for _ in range(2):
            async with self.session.post(url, headers=standalone, json=body) as started:
                self.assertEqual(started.status, 200)
        async with asyncio.timeout(5):
            while True:
                async with self.session.get(url) as response:
                    state = await response.json()
                    if state["phase"] == "ready":
                        self.assertEqual(state["engine"], "basic")
                        break
                await asyncio.sleep(.01)
        async with self.session.get(url + "/file") as download:
            self.assertEqual(download.content_type, "application/pdf")
            self.assertEqual(download.headers["Cache-Control"], "no-store")
            self.assertEqual(await download.read(), b"%PDF-mocked")
        async with self.session.post(url, headers=standalone, json={**body, "title": "Other"}) as response:
            self.assertEqual(response.status, 409)
        self.assertEqual(calls, [(b"Authorized answer", "Edited title")])
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as second:
            await self._authenticate_with(second)
            other = await self._register_document(session=second, incarnation_id="second")
            async with second.get(url + "/file") as response:
                self.assertEqual(response.status, 404)
            async with second.post(url[:-32] + "b" * 32, headers=self._client_headers(other), json=body) as response:
                self.assertEqual(response.status, 410)


class PdfJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_render_across_instances_and_expired_files_are_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = pathlib.Path(temp)
            managers = [SummaryPdfJobs(folder, lock_path=folder / "shared.lock") for _ in range(2)]
            first_started, release = asyncio.Event(), asyncio.Event()
            history = []

            async def render(job, source, output, work):
                history.append(source)
                first_started.set()
                await release.wait()
                output.write_bytes(b"%PDF-test")
                job.engine = "basic"

            try:
                for manager in managers:
                    manager._render = render
                body = {"title": "Title", "lang": "en"}
                p, q = (manager.remember("s", bytes([i])) for i, manager in enumerate(managers))
                first = managers[0].start("s", p, "a"*32, body)
                await asyncio.wait_for(first_started.wait(), 2)
                second = managers[1].start("s", q, "b"*32, body)
                tasks = [first.task, second.task]
                await asyncio.sleep(.05)
                self.assertEqual(history, [b"\0"])
                self.assertEqual(second.phase, "queued")
                self.assertIs(managers[0].start("s", p, "a"*32, body), first)
                release.set()
                await asyncio.wait_for(asyncio.gather(*tasks), 3)
                self.assertEqual(history, [b"\0", b"\1"])
                output = first.output
                self.assertTrue(output.is_file())
                first.expires = 0
                with self.assertRaises(WebRuntimeError):
                    managers[0].get("s", p, "a"*32)
                self.assertFalse(output.exists())
                managers[0].previews[p].expires = 0
                with self.assertRaises(WebRuntimeError):
                    managers[0].start("s", p, "c"*32, body)
            finally:
                release.set()
                await asyncio.gather(*(manager.close() for manager in managers))

    async def test_failure_removes_partial_output_and_shutdown_releases_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            manager = SummaryPdfJobs(root, lock_path=root / "pdf.lock")
            async def fail(job, source, output, work):
                output.write_bytes(b"partial")
                raise TimeoutError
            with patch.object(manager, "_render", fail):
                p = manager.remember("owner", b"source")
                job = manager.start("owner", p, "b"*32, {"title": "Title", "lang": "en"})
                await job.task
                self.assertEqual((job.phase, job.error), ("failed", "timeout"))
                self.assertFalse(list(pathlib.Path(manager._files.name).glob("*.pdf")))
                await manager.close()
