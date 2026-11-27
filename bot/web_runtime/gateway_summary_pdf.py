"""Authenticated PDF work on an already authorized, immutable preview."""

from aiohttp import web

from bot.web_runtime.contract import WebRuntimeError
from bot.web_runtime.gateway_request_decoder import decode_json_object
from bot.web_runtime.summary_pdf import SummaryPdfJobs


class WebGatewaySummaryPdfMixin:
    _pdf_jobs: SummaryPdfJobs

    def _pdf_job_key(self, request: web.Request) -> tuple[str, str, str]:
        return (self._request_admission.session(request).mobile_read_scope,
                request.match_info["preview_id"], request.match_info["job_id"])

    async def _handle_pdf_job_start(self, request: web.Request) -> web.Response:
        body = await decode_json_object(request)
        job = self._pdf_jobs.start(*self._pdf_job_key(request), body)
        return self._json_response(job.status(), headers={"Cache-Control": "no-store"})

    async def _handle_pdf_job_status(self, request: web.Request) -> web.Response:
        job = self._pdf_jobs.get(*self._pdf_job_key(request))
        return self._json_response(job.status(), headers={"Cache-Control": "no-store"})

    async def _handle_pdf_job_file(self, request: web.Request) -> web.FileResponse:
        job = self._pdf_jobs.get(*self._pdf_job_key(request))
        if job.phase != "ready" or job.output is None:
            raise WebRuntimeError("PDF is not ready.", code="pdf_not_ready", status=409)
        return web.FileResponse(job.output, headers={
            "Content-Type": "application/pdf", "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="Focus.pdf"',
        })
