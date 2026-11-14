"""Precompressed public Web assets.

See docs/contracts/focus-web-wire.zh-CN.md#静态资源交付.
"""

from __future__ import annotations

from aiohttp import web


def _accepts_gzip(value: str) -> bool:
    qualities: dict[str, float] = {}
    for item in value.lower().split(','):
        coding, *parameters = item.split(';')
        quality = 1.0
        for parameter in parameters:
            key, _, raw = parameter.strip().partition('=')
            if key.strip() != 'q':
                continue
            try:
                quality = float(raw)
            except ValueError:
                quality = 0.0
            if not 0 <= quality <= 1:
                quality = 0.0
        qualities[coding.strip()] = quality
    gzip_quality = qualities.get('gzip', qualities.get('*', 0.0))
    return gzip_quality > 0 and gzip_quality >= qualities.get('identity', 0.0)


class StaticAssetResponse(web.FileResponse):
    """Keep aiohttp's file transfer, validators and ranges with gzip negotiation."""

    async def prepare(self, request: web.Request):
        # FileResponse recognizes encoding names by substring, including q=0.
        # Normalize only our supported coding before its native sibling lookup.
        headers = request.headers.copy()
        accepted = ','.join(headers.getall('Accept-Encoding', []))
        headers['Accept-Encoding'] = 'gzip' if _accepts_gzip(accepted) else ''
        # Identity and 304 responses also vary, not just compressed 200s.
        self.headers['Vary'] = 'Accept-Encoding'
        return await super().prepare(request.clone(headers=headers))
