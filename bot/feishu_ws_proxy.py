"""
Feishu/Lark websocket proxy policy.

Only the public Feishu websocket ingress is controlled here. Local loopback
websockets used by Codex app-server and fcodex keep their own explicit
``proxy=None`` behavior.
"""

from __future__ import annotations

import inspect
import logging
from typing import Callable

logger = logging.getLogger(__name__)

FEISHU_WS_PROXY_ENV = "env"
FEISHU_WS_PROXY_DISABLED = "disabled"
DEFAULT_FEISHU_WS_PROXY = FEISHU_WS_PROXY_ENV

_SUPPORTED_MODES = {FEISHU_WS_PROXY_ENV, FEISHU_WS_PROXY_DISABLED}


def normalize_feishu_ws_proxy_mode(value: object) -> str:
    mode = str(value or DEFAULT_FEISHU_WS_PROXY).strip().lower()
    if not mode:
        return DEFAULT_FEISHU_WS_PROXY
    if mode not in _SUPPORTED_MODES:
        raise ValueError("feishu_ws_proxy 仅支持 env 或 disabled")
    return mode


def configure_feishu_ws_proxy(mode: object) -> str:
    """Apply the process-local Feishu websocket proxy policy.

    The Lark SDK currently disables websockets' environment proxy discovery by
    returning ``{"proxy": None}`` from its private helper. For Feishu's public
    websocket endpoint, ``env`` restores the normal websockets behavior by
    returning no explicit proxy argument.
    """

    normalized = normalize_feishu_ws_proxy_mode(mode)
    try:
        import lark_oapi.ws.client as ws_client
    except Exception:
        logger.warning("无法加载 lark_oapi.ws.client，无法配置飞书 WebSocket 代理策略", exc_info=True)
        if normalized == FEISHU_WS_PROXY_ENV:
            raise RuntimeError("无法配置 feishu_ws_proxy=env：lark_oapi.ws.client 不可用")
        return normalized

    if not hasattr(ws_client, "_ws_connect_kwargs") or not hasattr(ws_client, "websockets"):
        message = "当前 lark_oapi 版本不暴露 WebSocket proxy hook，无法配置飞书 WebSocket 代理策略"
        logger.warning(message)
        if normalized == FEISHU_WS_PROXY_ENV:
            raise RuntimeError(f"无法配置 feishu_ws_proxy=env：{message}")
        return normalized

    def _env_ws_connect_kwargs() -> dict:
        return {}

    def _disabled_ws_connect_kwargs() -> dict:
        params = inspect.signature(ws_client.websockets.connect).parameters
        if "proxy" in params:
            return {"proxy": None}
        return {}

    replacement: Callable[[], dict]
    if normalized == FEISHU_WS_PROXY_ENV:
        replacement = _env_ws_connect_kwargs
    else:
        replacement = _disabled_ws_connect_kwargs
    ws_client._ws_connect_kwargs = replacement
    logger.info("Feishu WebSocket proxy mode: %s", normalized)
    return normalized
