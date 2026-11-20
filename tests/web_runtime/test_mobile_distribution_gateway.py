from pathlib import Path
from unittest.mock import patch

from bot.installation.mobile_distribution import MobileDistribution
from tests.web_runtime.gateway_harness import WebGatewayHarness


class AndroidDistributionGatewayTests(WebGatewayHarness):
    async def test_channel_admission_and_authenticated_digest_download(self):
        root = Path(self.temp_dir.name)
        cache = MobileDistribution("unused", root)
        digest = "a" * 64
        (root / (digest + ".apk")).write_bytes(b"signed fixture")
        check = self.endpoint + "/api/mobile/android/main/check"
        apk = self.endpoint + "/api/mobile/android/apk/" + digest
        with patch("bot.web_runtime.gateway_mobile_distribution.mobile_cache", return_value=cache), \
                patch.object(cache, "check", return_value={"release": None, "checked_at": 0, "stale": False}) as sync:
            async with self.session.get(apk) as response:
                self.assertEqual(response.status, 401)
            await self._authenticate()
            doc = await self._register_document(incarnation_id="update-page")
            headers = self._client_headers(doc)
            for bad in ({"Origin": self.endpoint}, self._client_headers(doc, include_csrf=False),
                        {**headers, "Origin": "https://another.example"}):
                async with self.session.post(check, headers=bad, json={}) as response:
                    self.assertGreaterEqual(response.status, 400)
            async with self.session.post(check, json={"url": "https://elsewhere"}, headers=headers) as response:
                self.assertEqual(response.status, 400)
            sync.assert_not_called()
            async with self.session.post(check, headers=headers, json={}) as response:
                self.assertEqual(response.status, 200)
                self.assertIsNone((await response.json())["release"])
            sync.assert_called_once_with("main")
            async with self.session.get(apk) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.content_type, "application/vnd.android.package-archive")
                self.assertEqual(await response.read(), b"signed fixture")
            async with self.session.get(apk + "?url=other") as response:
                self.assertEqual(response.status, 404)
