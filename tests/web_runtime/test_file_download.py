"""Real HTTP coverage for session-authenticated server file downloads."""

import os
from unittest.mock import patch

from bot.focus_web_wire_catalog import FOCUS_WEB_RECORD_BY_NAME
from bot.web_runtime.file_download import inspect_file
from tests.web_runtime.gateway_harness import WebGatewayHarness


class FileDownloadTests(WebGatewayHarness):
    async def test_session_is_required_for_metadata_and_download(self):
        for route in ("info", "download"):
            async with self.session.get(
                f"{self.endpoint}/api/files/{route}", params={"path": str(self.root)},
            ) as response:
                self.assertEqual(response.status, 401)

    async def test_info_resolves_cwd_without_loading_content_or_runtime_dispatch(self):
        await self._authenticate()
        target = self.root / "报告 #1.txt"
        target.write_bytes(b"hello\x00world")
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("no full read")):
            async with self.session.get(
                f"{self.endpoint}/api/files/info",
                params={"path": target.name, "cwd": str(self.root)},
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                info = await response.json()
        self.assertEqual(info, {"path": str(target.resolve()), "name": target.name, "size": 11})
        self.assertEqual(set(info), set(FOCUS_WEB_RECORD_BY_NAME["file_info"].required_fields))
        self.assertEqual(self.calls, [])

    async def test_download_exact_binary_bytes_and_custom_unicode_name(self):
        await self._authenticate()
        target = self.root / "report.bin"
        data = bytes(range(256)) * 8192
        target.write_bytes(data)
        target.with_suffix(".bin.gz").write_bytes(b"unrelated compressed sibling")
        async with self.session.get(
            f"{self.endpoint}/api/files/download",
            params={"path": str(target), "filename": "我的文件.bin"},
            headers={"Accept-Encoding": "gzip, br"},
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
            self.assertNotIn("Content-Encoding", response.headers)
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertEqual(response.content_disposition.filename, "我的文件.bin")
            self.assertEqual(int(response.headers["Content-Length"]), len(data))
            self.assertEqual(await response.read(), data)

    async def test_ranges_and_empty_files(self):
        await self._authenticate()
        target = self.root / "range.dat"
        target.write_bytes(b"0123456789")
        for value, expected, status in (("bytes=3-5", b"345", 206), ("bytes=-2", b"89", 206), ("bytes=99-", b"", 416)):
            async with self.session.get(
                f"{self.endpoint}/api/files/download", params={"path": str(target)},
                headers={"Range": value},
            ) as response:
                self.assertEqual(response.status, status)
                self.assertEqual(await response.read(), expected)
                if status == 416:
                    self.assertNotIn("Content-Disposition", response.headers)
        target.write_bytes(b"")
        async with self.session.get(
            f"{self.endpoint}/api/files/download", params={"path": str(target)},
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), b"")

    async def test_errors_never_become_downloaded_error_files(self):
        await self._authenticate()
        for path, code, status in (
            (str(self.root / "missing.pdf"), "file_not_found", 404),
            (str(self.root), "file_not_regular", 400),
            ("relative.txt", "file_base_required", 400),
        ):
            async with self.session.get(
                f"{self.endpoint}/api/files/download", params={"path": path},
            ) as response:
                self.assertEqual(response.status, status)
                self.assertNotIn("Content-Disposition", response.headers)
                self.assertEqual((await response.json())["error"]["code"], code)

    async def test_invalid_query_is_rejected(self):
        await self._authenticate()
        for query in ({}, {"path": "\x00"}, {"path": "/tmp", "unknown": "x"}, [("path", "a"), ("path", "b")]):
            async with self.session.get(f"{self.endpoint}/api/files/info", params=query) as response:
                self.assertEqual(response.status, 400)
                self.assertEqual((await response.json())["error"]["code"], "invalid_file_request")

    async def test_file_removed_after_inspection_is_not_an_attachment(self):
        await self._authenticate()
        target = self.root / "gone.txt"
        target.write_text("content")

        def inspect_then_remove(path, cwd=""):
            info = inspect_file(path, cwd)
            target.unlink()
            return info

        with patch("bot.web_runtime.file_download.inspect_file", side_effect=inspect_then_remove):
            async with self.session.get(
                f"{self.endpoint}/api/files/download", params={"path": str(target)},
            ) as response:
                self.assertEqual(response.status, 404)
                self.assertNotIn("Content-Disposition", response.headers)

    async def test_unreadable_files_report_permission_error(self):
        await self._authenticate()
        target = self.root / "private.txt"
        target.write_text("content")
        with patch("bot.web_runtime.file_download.os.open", side_effect=PermissionError):
            async with self.session.get(
                f"{self.endpoint}/api/files/info", params={"path": str(target)},
            ) as response:
                self.assertEqual(response.status, 403)
                self.assertEqual((await response.json())["error"]["code"], "file_unreadable")

    async def test_symlinks_outside_cwd_are_allowed_but_special_files_are_not(self):
        if os.name == "nt":
            self.skipTest("POSIX symlink/FIFO fixture")
        await self._authenticate()
        target = self.root / "target.txt"
        target.write_text("content")
        cwd = self.root / "workspace"
        cwd.mkdir()
        (cwd / "link.txt").symlink_to(target)
        async with self.session.get(
            f"{self.endpoint}/api/files/info", params={"path": "link.txt", "cwd": str(cwd)},
        ) as response:
            self.assertEqual(await response.json(), {"path": str(target.resolve()), "name": "link.txt", "size": 7})
        fifo = cwd / "pipe"
        os.mkfifo(fifo)
        async with self.session.get(
            f"{self.endpoint}/api/files/info", params={"path": str(fifo)},
        ) as response:
            self.assertEqual(response.status, 400)
