from unittest.mock import Mock

from tests.web_runtime.gateway_harness import WebGatewayHarness


class BatchUpdateGatewayTests(WebGatewayHarness):
    async def test_status_and_preparation_require_the_current_document(self):
        read = self.gateway._ports.update_installation = Mock(return_value={"installation_id": "a" * 32})
        prepare = self.gateway._ports.update_prepare_latest = Mock(return_value={"outcome": "current"})
        base = self.endpoint + "/api/update/"
        body = dict(installation_id="a" * 32, target="installed", previous_operation_id="", request_id="b" * 32)
        async with self.session.get(base + "installation") as response:
            self.assertEqual(response.status, 401)
        await self._authenticate()
        async with self.session.get(base + "installation") as response:
            self.assertGreaterEqual(response.status, 400)
        doc = await self._register_document(resume_client_id="", incarnation_id="batch")
        headers = self._client_headers(doc)
        async with self.session.get(base + "installation", headers=headers) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        for invalid in (self._client_headers(doc, include_csrf=False), {**headers, "Origin": "https://other.test"},
                        {**headers, "X-Focus-Web-Document": "wrong"}):
            async with self.session.post(base + "prepare-latest", json=body, headers=invalid) as response:
                self.assertGreaterEqual(response.status, 400)
        for change in (dict(target=[]), dict(target="other"), dict(previous_operation_id="a"), dict(request_id=""),
                       dict(installation_id=None), dict(url="https://other.test")):
            async with self.session.post(base + "prepare-latest", json={**body, **change}, headers=headers) as response:
                self.assertEqual(response.status, 400)
        prepare.assert_not_called()
        async with self.session.post(base + "prepare-latest", json=body, headers=headers) as response:
            self.assertEqual(response.status, 200)
        read.assert_called_once_with()
        prepare.assert_called_once_with("a" * 32, "installed", "", "b" * 32)
