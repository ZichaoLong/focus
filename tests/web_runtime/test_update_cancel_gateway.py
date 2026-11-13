from unittest.mock import Mock

from bot.installation.update import UpdateError
from tests.web_runtime.gateway_harness import WebGatewayHarness


class UpdateCancelGatewayTests(WebGatewayHarness):
    async def test_cancel_requires_authentication_csrf_and_an_exact_operation_id(self):
        cancel = Mock(return_value={"state": "cancelling"})
        self.gateway._ports.update_cancel = cancel
        url = self.endpoint + "/api/update/cancel"
        operation_id = "a" * 32
        async with self.session.post(url, json={"operation_id": operation_id}) as response:
            self.assertEqual(response.status, 401)
        await self._authenticate()
        document = await self._register_document(resume_client_id="update", incarnation_id="cancel-document")
        headers = self._client_headers(document)
        without_csrf = self._client_headers(document, include_csrf=False)
        async with self.session.post(url, json={"operation_id": operation_id}, headers=without_csrf) as response:
            self.assertEqual(response.status, 403)
        for body in ({}, {"operation_id": "other.service"}, {"operation_id": " a"},
                     {"operation_id": operation_id, "target": "main"}, {"operation_id": 1}):
            async with self.session.post(url, json=body, headers=headers) as response:
                self.assertEqual(response.status, 400)
        cancel.assert_not_called()
        async with self.session.post(url, json={"operation_id": operation_id}, headers=headers) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), {"state": "cancelling"})
        cancel.assert_called_once_with(operation_id)
        cancel.side_effect = UpdateError("operation already applying")
        async with self.session.post(url, json={"operation_id": operation_id}, headers=headers) as response:
            self.assertEqual(response.status, 409)
            self.assertEqual((await response.json())["error"]["code"], "update_rejected")
