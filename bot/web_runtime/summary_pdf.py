"""Session-bound immutable print previews and bounded, reconnectable PDF work."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import secrets
import shutil
import signal
import sys
import tempfile
import time
from dataclasses import dataclass, field
from importlib.util import find_spec

from bot.file_lock import FileLockBusyError, acquire_file_lock, open_lock_file
from bot.platform_paths import default_data_root
from bot.web_runtime.contract import WebRuntimeError

_PREVIEW_TTL = 60 * 60
_RESULT_TTL = 15 * 60
_MAX_RESULT = 96 * 1024 * 1024
_RETAINED_BYTES = 128 * 1024 * 1024
_RENDER_TIMEOUT = 240


@dataclass
class _Preview:
    owner: str
    source: bytes
    expires: float


@dataclass
class _Job:
    preview: str
    owner: str
    title: str
    lang: str
    phase: str = "queued"
    engine: str = ""
    done: int = 0
    total: int = 0
    warnings: list[dict] = field(default_factory=list)
    error: str = ""
    size: int = 0
    output: pathlib.Path | None = None
    task: asyncio.Task | None = None
    expires: float = float("inf")

    def status(self) -> dict:
        result = {"phase": self.phase, "done": self.done, "total": self.total, "warnings": self.warnings}
        if self.engine:
            result["engine"] = self.engine
        if self.error:
            result["error"] = self.error
        return result


def bundled_node() -> pathlib.Path:
    spec = find_spec("nodejs_wheel")
    if spec is None or not spec.origin:
        raise RuntimeError("The installed PDF runtime is missing")
    return pathlib.Path(spec.origin).parent / ("node.exe" if os.name == "nt" else "bin/node")


def installed_browser() -> str:
    for name in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser", "msedge"):
        if path := shutil.which(name):
            return path
    if sys.platform == "darwin":
        path = pathlib.Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
        if path.is_file():
            return str(path)
    if os.name == "nt":
        for root in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if folder := os.environ.get(root):
                for binary in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
                    if (path := pathlib.Path(folder) / binary).is_file():
                        return str(path)
    return ""


class SummaryPdfJobs:
    def __init__(self, assets: pathlib.Path, *, lock_path: pathlib.Path | None = None):
        self.assets = assets
        self.lock_path = lock_path or default_data_root() / "summary-pdf.lock"
        self.previews: dict[str, _Preview] = {}
        self.jobs: dict[str, _Job] = {}
        self._files: tempfile.TemporaryDirectory | None = None
        self._queue: asyncio.Lock | None = None
        self._timer: asyncio.TimerHandle | None = None
        self._bad_browser: tuple[str, int] | None = None
        self._retry_at = 0.0

    def remember(self, owner: str, source: bytes) -> str:
        self._expire()
        while self.previews and (len(self.previews) >= 32 or
                                 sum(len(p.source) for p in self.previews.values()) + len(source) > 96 * 1024 * 1024):
            del self.previews[next(iter(self.previews))]
        token = secrets.token_hex(16)
        self.previews[token] = _Preview(owner, source, time.monotonic() + _PREVIEW_TTL)
        self._schedule()
        return token

    def _schedule(self) -> None:
        if self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(60, self._tick)

    def _tick(self) -> None:
        self._timer = None
        self._expire()
        if self.previews or self.jobs:
            self._schedule()

    def _expire(self) -> None:
        now = time.monotonic()
        for key, p in tuple(self.previews.items()):
            if p.expires <= now:
                del self.previews[key]
        for key, job in tuple(self.jobs.items()):
            if job.expires <= now:
                if job.output:
                    try:
                        job.output.unlink(missing_ok=True)
                    except PermissionError:
                        # On Windows an open download can keep the file until the next sweep.
                        continue
                del self.jobs[key]

    def get(self, owner: str, preview: str, key: str) -> _Job:
        self._expire()
        job = self.jobs.get(key)
        if not job or job.expires <= time.monotonic() or (job.owner, job.preview) != (owner, preview):
            raise WebRuntimeError("This PDF job has expired.", code="pdf_job_missing", status=404)
        return job

    def start(self, owner: str, preview: str, key: str, body: dict) -> _Job:
        self._expire()
        title, lang = body.get("title"), body.get("lang")
        if (set(body) != {"title", "lang"} or not re.fullmatch(r"[0-9a-f]{32}", key)
                or not isinstance(title, str) or not title.strip() or len(title) > 4096
                or not isinstance(lang, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,35}", lang)):
            raise WebRuntimeError("Invalid PDF request.", code="invalid_pdf_request", status=400)
        if key in self.jobs:
            job = self.get(owner, preview, key)
            if (title, lang) != (job.title, job.lang):
                raise WebRuntimeError("PDF request has changed.", code="pdf_job_conflict", status=409)
            return job
        saved = self.previews.get(preview)
        if not saved or saved.owner != owner:
            raise WebRuntimeError("Open a new print preview.", code="pdf_preview_expired", status=410)
        if sum(job.task is not None for job in self.jobs.values()) >= 8:
            raise WebRuntimeError("PDF queue is full.", code="pdf_queue_full", status=429)
        if len(self.jobs) >= 16:
            completed = next((k for k, job in self.jobs.items() if job.task is None), None)
            if completed:
                self.jobs[completed].expires = 0
                self._expire()
            if len(self.jobs) >= 16:
                raise WebRuntimeError("PDF queue is full.", code="pdf_queue_full", status=429)
        job = self.jobs[key] = _Job(preview, owner, title, lang)
        job.task = asyncio.create_task(self._run(job, key, saved.source))
        self._schedule()
        return job

    async def _run(self, job: _Job, key: str, source: bytes) -> None:
        try:
            if self._queue is None:
                self._queue = asyncio.Lock()
            async with self._queue:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                with open_lock_file(self.lock_path) as lock:
                    while True:
                        try:
                            acquire_file_lock(lock, blocking=False)
                            break
                        except FileLockBusyError:
                            await asyncio.sleep(.5)
                    if self._files is None:
                        self._files = tempfile.TemporaryDirectory(prefix="focus-pdf-")
                    output = pathlib.Path(self._files.name) / (key + ".pdf")
                    with tempfile.TemporaryDirectory(dir=self._files.name) as work:
                        await self._render(job, source, output, pathlib.Path(work))
                    job.size = output.stat().st_size
                    if not (0 < job.size <= _MAX_RESULT):
                        raise ValueError("PDF output size")
                    retained = sum(other.size for other in self.jobs.values() if other.output is not None)
                    for other in self.jobs.values():
                        if retained + job.size <= _RETAINED_BYTES:
                            break
                        if other.output is not None:
                            other.expires = 0
                            retained -= other.size
                    self._expire()
                    job.output = output
                    job.phase = "ready"
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            job.phase = "failed"
            job.error = "timeout" if isinstance(exc, TimeoutError) else "render"
        finally:
            if job.output is None and self._files is not None:
                (pathlib.Path(self._files.name) / (key + ".pdf")).unlink(missing_ok=True)
            job.task = None
            job.expires = time.monotonic() + _RESULT_TTL

    async def _render(self, job: _Job, source: bytes, output: pathlib.Path, work: pathlib.Path) -> None:
        browser = installed_browser()
        identity = None
        if browser:
            try:
                identity = (browser, os.stat(browser).st_mtime_ns)
            except OSError:
                browser = ""
        browser_failed = bool(identity and identity == self._bad_browser and time.monotonic() < self._retry_at)
        if browser_failed:
            browser = ""
        job.phase = "preparing"
        payload = json.dumps({"markdown": source.decode(), "title": job.title, "lang": job.lang,
                              "output": str(output), "profile": str(work / "profile"), "browser": browser,
                              "browserFailed": browser_failed},
                             ensure_ascii=False).encode()
        env = {name: os.environ[name] for name in ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT",
               "LOCALAPPDATA", "LANG", "LD_LIBRARY_PATH") if name in os.environ}
        proc = await asyncio.create_subprocess_exec(
            str(bundled_node()), "--max-old-space-size=384", str(self.assets / "render.mjs"), cwd=work, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=os.name == "posix", limit=256 * 1024,
        )
        try:
            async with asyncio.timeout(_RENDER_TIMEOUT):
                proc.stdin.write(payload)
                await proc.stdin.drain()
                proc.stdin.close()
                async for line in proc.stdout:
                    if not line.startswith(b'{"phase":'):
                        continue
                    event = json.loads(line)
                    phase = event["phase"]
                    if phase == "browser_unavailable":
                        self._bad_browser, self._retry_at = identity, time.monotonic() + 60
                    elif phase in {"formulas", "browser", "layout"}:
                        job.phase = phase
                        job.done, job.total = event.get("done", 0), event.get("total", 0)
                    elif phase == "complete":
                        job.engine = event["engine"]
                        job.warnings = event["warnings"]
                if await proc.wait() or not job.engine:
                    raise RuntimeError("PDF worker failed")
        finally:
            if proc.returncode is None:
                try:
                    if os.name == "posix":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                except ProcessLookupError:
                    pass
                await proc.wait()

    async def close(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        tasks = [job.task for job in self.jobs.values() if job.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.jobs.clear()
        self.previews.clear()
        if self._files is not None:
            self._files.cleanup()
            self._files = None
        self._queue = None
