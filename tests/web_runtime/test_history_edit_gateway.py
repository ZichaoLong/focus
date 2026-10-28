from tests.web_runtime.gateway_harness import WebGatewayHarness


class HistoryEditGatewayTests(WebGatewayHarness):
    async def test_edit_target_is_closed_and_uses_exact_ids(self):
        await self._authenticate()
        document = await self._register_document(resume_client_id="edit", incarnation_id="edit-document")
        headers = self._client_headers(document)
        path = f"{self.endpoint}/api/threads/source-id/fork"
        for body in ({"turn_id":"t"}, {"turn_id":"t","item_id":" i"},
                     {"turn_id":"t","item_id":"i","text":"untrusted preview"},
                     {"turn_id":99,"item_id":"i"}):
            async with self.session.post(path, json=body, headers=headers) as response:
                self.assertEqual(response.status, 400)
        self.assertEqual(self.calls, [])
        async with self.session.post(path, json={"turn_id":"real-turn","item_id":"real-item"}, headers=headers) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(self.calls, [("fork", (document["client_id"], "source-id"), {"turn_id":"real-turn","item_id":"real-item"})])
