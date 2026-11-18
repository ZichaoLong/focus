"""Own the Lark SDK event loop and prove its callback producer has stopped.

The SDK's blocking start and module-local loop are adapted here only. See
docs/contracts/system-config.zh-CN.md for frontend activation semantics.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from bot.feishu_ws_proxy import configure_feishu_ws_proxy


logger = logging.getLogger(__name__)
_SDK_OWNER = threading.Lock()


class _EndpointRequests:
    """Bound the SDK's otherwise unbounded synchronous discovery request."""

    def __init__(self, requests: Any, timeout: float) -> None:
        self._requests = requests
        self._timeout = timeout

    def post(self, *args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", self._timeout)
        return self._requests.post(*args, **kwargs)


class FeishuTransport:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        event_handler: Any,
        proxy_mode: str,
        timeout: float,
    ) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._event_handler = event_handler
        self._proxy_mode = proxy_mode
        self._timeout = timeout
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._state = "stopped"
        self._error = ""
        self._cleanup_error: BaseException | None = None
        self._initialized = False
        self._cleaning = False

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {"state": self._state, "error": self._error}

    def _set_state(self, state: str, error: str = "") -> None:
        with self._lock:
            self._state, self._error = state, error

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Feishu transport has already been started")
        if not _SDK_OWNER.acquire(blocking=False):
            raise RuntimeError("one process can host only one Feishu SDK loop")
        self._set_state("connecting")
        self._thread = threading.Thread(
            target=self._run, name="focus-feishu", daemon=True
        )
        try:
            self._thread.start()
        except BaseException:
            self._thread = None
            _SDK_OWNER.release()
            raise
        if not self._ready.wait(timeout=10):
            raise RuntimeError("Feishu transport initialization timed out")
        if not self._initialized:
            raise RuntimeError(
                "Feishu transport initialization failed: " + self.snapshot()["error"]
            )

    def stop(self) -> None:
        self._stopping.set()
        thread, loop = self._thread, self._loop
        if thread is None:
            return
        if thread is threading.current_thread():
            raise RuntimeError("Feishu transport cannot join itself")
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._cancel_tasks)
            except RuntimeError:
                if not loop.is_closed():
                    raise
        thread.join(timeout=2 * self._timeout + 10)
        if thread.is_alive():
            raise RuntimeError(
                "Feishu callback producer did not stop; authority retained"
            )
        if self._cleanup_error is not None:
            raise RuntimeError(
                "Feishu transport cleanup failed"
            ) from self._cleanup_error

    def _cancel_tasks(self, *, cleanup: bool = False) -> None:
        if self._cleaning and not cleanup:
            return
        if self._loop is not None:
            for task in asyncio.all_tasks(self._loop):
                task.cancel()

    def _run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
        except Exception as exc:
            self._set_state("failed", type(exc).__name__)
            _SDK_OWNER.release()
            self._ready.set()
            return
        self._loop = loop
        client = None
        sdk = None
        previous_loop = previous_requests = None
        try:
            asyncio.set_event_loop(loop)
            import lark_oapi.ws.client as sdk

            previous_loop, previous_requests = sdk.loop, sdk.requests
            sdk.loop = loop
            sdk.requests = _EndpointRequests(previous_requests, self._timeout)
            configure_feishu_ws_proxy(self._proxy_mode)
            transport = self

            class ManagedClient(sdk.Client):
                async def _connect(self) -> None:
                    await super()._connect()
                    if not transport._stopping.is_set():
                        transport._set_state("connected")

                async def _receive_message_loop(self) -> None:
                    try:
                        await super()._receive_message_loop()
                    except Exception as exc:
                        transport._set_state("failed", type(exc).__name__)

            client = ManagedClient(
                self._app_id, self._app_secret, event_handler=self._event_handler
            )
            client.on_reconnecting = lambda: self._set_state("reconnecting")
            self._initialized = True
            self._ready.set()
            if not self._stopping.is_set():
                # SDK 1.7.1 start() runs connect, reconnect and the permanent
                # wait in separate run_until_complete calls. Cancellation in
                # that gap can miss the successor task. Keep the same SDK
                # protocol under one owned task for its entire lifetime.
                async def serve() -> None:
                    try:
                        await client._connect()
                    except sdk.ClientException:
                        raise
                    except Exception:
                        await client._disconnect()
                        await client._reconnect()
                    if self._stopping.is_set():
                        return
                    loop.create_task(client._ping_loop())
                    await asyncio.Future()

                loop.run_until_complete(serve())
        except asyncio.CancelledError:
            if not self._stopping.is_set():
                self._set_state("failed", "Feishu SDK loop was cancelled")
        except Exception as exc:
            # Platform failure is observable independently of core readiness.
            # Never include SDK exceptions containing credentials in status.
            self._set_state("failed", type(exc).__name__)
            logger.error("Feishu transport failed (%s)", type(exc).__name__)
        finally:
            self._cleaning = True
            self._ready.set()
            try:
                if client is not None:
                    client._auto_reconnect = False
                self._cancel_tasks(cleanup=True)
                pending = asyncio.all_tasks(loop)
                if pending:
                    _, remaining = loop.run_until_complete(
                        asyncio.wait(pending, timeout=self._timeout)
                    )
                    if remaining:
                        raise RuntimeError("Feishu SDK tasks did not stop")
                if client is not None:
                    loop.run_until_complete(
                        asyncio.wait_for(client._disconnect(), self._timeout)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
            except BaseException as exc:
                self._cleanup_error = exc
            finally:
                loop.close()
                if sdk is not None and previous_loop is not None:
                    sdk.loop, sdk.requests = previous_loop, previous_requests
                _SDK_OWNER.release()
            if self._stopping.is_set() and self._cleanup_error is None:
                self._set_state("stopped")
