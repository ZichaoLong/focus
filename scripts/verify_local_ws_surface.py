#!/usr/bin/env python3
"""Probe a local Codex websocket surface with minimal read-only JSON-RPC."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

CLIENT_INFO = {
    "clientInfo": {"name": "feishu-codex-local-ws-probe", "version": "1.0"},
    "capabilities": {"experimentalApi": True},
}


def _build_headers(token: str) -> dict[str, str] | None:
    normalized = str(token or "").strip()
    if not normalized:
        return None
    return {"Authorization": f"Bearer {normalized}"}


def _load_token_from_file(path: str) -> str:
    token_path = Path(path).expanduser()
    return token_path.read_text(encoding="utf-8").strip()


def _read_token(args: argparse.Namespace) -> str:
    if args.token:
        return str(args.token).strip()
    if args.token_file:
        return _load_token_from_file(args.token_file)
    if args.token_env:
        return str(os.environ.get(args.token_env, "")).strip()
    return ""


def _rpc_call(ws: Any, *, request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    ws.send(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            ensure_ascii=False,
        )
    )
    while True:
        raw = ws.recv()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(raw)
        if payload.get("id") == request_id:
            return payload


def probe_surface(*, url: str, token: str, open_timeout: float) -> dict[str, Any]:
    headers = _build_headers(token)
    result: dict[str, Any] = {
        "url": url,
        "auth": "bearer" if headers else "none",
        "status": "",
    }
    try:
        connect_kwargs: dict[str, Any] = {
            "open_timeout": open_timeout,
            "max_size": None,
            "proxy": None,
        }
        if headers:
            connect_kwargs["additional_headers"] = headers
        with connect(url, **connect_kwargs) as ws:
            initialize = _rpc_call(
                ws,
                request_id=1,
                method="initialize",
                params=CLIENT_INFO,
            )
            if "error" in initialize:
                result["status"] = "rpc_error"
                result["step"] = "initialize"
                result["error"] = initialize["error"]
                return result

            models = _rpc_call(
                ws,
                request_id=2,
                method="model/list",
                params={},
            )
            if "error" in models:
                result["status"] = "rpc_error"
                result["step"] = "model/list"
                result["error"] = models["error"]
                return result

            data = models.get("result", {}).get("data") or []
            sample_models = [
                str(item.get("model"))
                for item in data[:3]
                if isinstance(item, dict) and item.get("model")
            ]
            result["status"] = "ok"
            result["model_count"] = len(data)
            result["sample_models"] = sample_models
            return result
    except InvalidStatus as exc:
        response = exc.args[0] if exc.args else None
        status_code = getattr(response, "status_code", None)
        result["status"] = "unauthorized" if status_code == 401 else "connect_failed"
        if status_code is not None:
            result["http_status"] = status_code
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        return result
    except Exception as exc:
        result["status"] = "connect_failed"
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        return result


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe a local app-server or fcodex proxy with minimal read-only "
            "JSON-RPC (initialize + model/list)."
        )
    )
    parser.add_argument("--url", required=True, help="Websocket URL, for example ws://127.0.0.1:45885")
    parser.add_argument(
        "--surface",
        choices=("app-server", "proxy"),
        default="app-server",
        help="Label only, used in output",
    )
    token_group = parser.add_mutually_exclusive_group()
    token_group.add_argument("--token", default="", help="Bearer token value")
    token_group.add_argument("--token-file", default="", help="Path to a bearer token file")
    token_group.add_argument("--token-env", default="", help="Environment variable that holds the bearer token")
    parser.add_argument(
        "--expect",
        choices=("ok", "unauthorized", "connect_failed", "rpc_error"),
        default="",
        help="Fail with exit code 1 if the final status differs",
    )
    parser.add_argument("--open-timeout", type=float, default=3.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    token = _read_token(args)
    result = probe_surface(
        url=args.url,
        token=token,
        open_timeout=args.open_timeout,
    )
    result["surface"] = args.surface
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.expect and result["status"] != args.expect:
        print(
            f"expected status {args.expect!r}, got {result['status']!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
