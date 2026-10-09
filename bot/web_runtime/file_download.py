"""Session-authenticated single-file reads for downloads and on-demand previews.

See docs/contracts/focus-web-file-download.zh-CN.md for the download boundary.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import stat
from urllib.parse import quote

from aiohttp import web

from bot.web_runtime.contract import WebRuntimeError


def inspect_file(path: str, cwd: str = "") -> dict[str, str | int]:
    """Resolve a server path and check readability without loading its content."""
    try:
        target = pathlib.Path(path).expanduser()
        if not target.is_absolute():
            base = pathlib.Path(cwd).expanduser()
            if not cwd or not base.is_absolute():
                raise WebRuntimeError(
                    "A relative file path needs the conversation working directory.",
                    code="file_base_required", status=400,
                )
            target = base / target
        # Symlinks and files outside cwd are allowed by the instance trust model.
        name = target.name
        target = target.resolve(strict=True)
        if not stat.S_ISREG(target.stat().st_mode):
            raise WebRuntimeError(
                "Only individual regular files can be downloaded.",
                code="file_not_regular", status=400,
            )
        # O_NONBLOCK prevents a replacement FIFO from blocking this check.
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise WebRuntimeError(
                    "Only individual regular files can be downloaded.",
                    code="file_not_regular", status=400,
                )
        finally:
            os.close(fd)
        return {"path": str(target), "name": name, "size": info.st_size}
    except WebRuntimeError:
        raise
    except FileNotFoundError:
        raise WebRuntimeError("The file no longer exists.", code="file_not_found", status=404) from None
    except PermissionError:
        raise WebRuntimeError("Focus cannot read this file.", code="file_unreadable", status=403) from None
    except (OSError, ValueError, RuntimeError):
        raise WebRuntimeError("This file path is unavailable.", code="file_unavailable", status=400) from None


def _query(request: web.Request, *, download: bool) -> dict[str, str]:
    allowed = {"path", "filename"} if download else {"path", "cwd"}
    values = dict(request.query)
    if (
        set(values) - allowed
        or any(len(request.query.getall(key)) != 1 for key in values)
        or not values.get("path")
        or any("\0" in value for value in values.values())
    ):
        raise WebRuntimeError("Invalid file request.", code="invalid_file_request", status=400)
    return values


class SingleFileResponse(web.FileResponse):
    """Keep aiohttp's bounded transfer/range support, serving the exact file."""

    async def prepare(self, request: web.Request):
        # FileResponse normally negotiates a sibling .gz/.br static asset. A
        # download must never substitute that sibling for the requested bytes.
        headers = request.headers.copy()
        headers.popall("Accept-Encoding", None)
        return await super().prepare(request.clone(headers=headers))

    def set_status(self, status: int, reason: str | None = None) -> None:
        if status >= 400:
            # A file may disappear after inspection; do not save its error body
            # as a successful attachment in the native browser download flow.
            self.headers.pop("Content-Disposition", None)
        super().set_status(status, reason=reason)


class WebGatewayFileDownloadMixin:
    async def _handle_file_info(self, request: web.Request) -> web.Response:
        query = _query(request, download=False)
        info = await asyncio.to_thread(inspect_file, query["path"], query.get("cwd", ""))
        return web.json_response(info, headers={"Cache-Control": "no-store"})

    async def _handle_file_download(self, request: web.Request) -> web.StreamResponse:
        query = _query(request, download=True)
        info = await asyncio.to_thread(inspect_file, query["path"])
        filename = query.get("filename") or str(info["name"])
        # filename is a client-side save suggestion, never a filesystem target.
        filename = "".join(
            "-" if character in '/\\' or ord(character) < 32 or ord(character) == 127 else character
            for character in filename
        )
        return SingleFileResponse(
            str(info["path"]),
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
                "Cache-Control": "no-store",
            },
        )
