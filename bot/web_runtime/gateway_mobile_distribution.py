"""Same-origin Android channel preparation and digest-pinned downloads."""

import asyncio
import subprocess

from aiohttp import web

from bot.installation.mobile_distribution import CHANNELS, DistributionUnavailable, mobile_cache
from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.file_download import SingleFileResponse
from bot.web_runtime.gateway_request_decoder import decode_json_object


class WebGatewayMobileDistributionMixin:
    async def _handle_mobile_android_check(self, request: web.Request) -> web.Response:
        self._required_client_id(request)
        channel = request.match_info["channel"]
        if channel not in CHANNELS or request.query or await decode_json_object(request):
            raise WebRuntimeError("Invalid Android update check", code="invalid_mobile_update")
        try:
            status = await asyncio.to_thread(mobile_cache().check, channel)
        except DistributionUnavailable as exc:
            raise WebRuntimeError(str(exc), code="mobile_source_unavailable", status=503) from exc
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            raise WebRuntimeError("Cannot verify the mobile distribution", code="invalid_mobile_release", status=502) from exc
        return web.json_response(status, headers={"Cache-Control": "no-store"})

    async def _handle_mobile_android_apk(self, request: web.Request) -> web.StreamResponse:
        try:
            if request.query:
                raise ValueError("Invalid query")
            path = mobile_cache().apk(request.match_info["digest"])
        except DistributionUnavailable as exc:
            raise WebRuntimeError(str(exc), code="mobile_source_unavailable", status=503) from exc
        except (FileNotFoundError, ValueError) as exc:
            raise WebRuntimeError("Mobile package is unavailable", code="mobile_package_missing", status=404) from exc
        return SingleFileResponse(path, headers={
            "Content-Type": "application/vnd.android.package-archive",
            "Content-Disposition": 'attachment; filename="Focus-Mobile.apk"',
            "Cache-Control": "private, no-store",
        })
