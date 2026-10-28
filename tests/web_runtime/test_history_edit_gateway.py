from tests.web_runtime.gateway_harness import WebGatewayHarness


class HistoryEditGatewayTests(WebGatewayHarness):
    async def test_preparation_and_native_revert_use_separate_exact_requests(self):
        await self._authenticate()
        document = await self._register_document(resume_client_id="edit", incarnation_id="edit-document")
        headers = self._client_headers(document)
        root = f"{self.endpoint}/api/threads/source-id"
        for body in ({}, {"turn_id": " t"}, {"turn_id": "t", "item_id": "i"}, {"turn_id": 99}):
            async with self.session.post(root + "/revert", json=body, headers=headers) as response:
                self.assertEqual(response.status, 400)
        async with self.session.post(root + "/fork", json={"turn_id": "t", "item_id": "i"}, headers=headers) as response:
            self.assertEqual(response.status, 400)
        async with self.session.get(root + "/history-prompt", params={"turn_id": "t"}, headers=headers) as response:
            self.assertEqual(response.status, 400)
        self.assertEqual(self.calls, [])
        target = {"turn_id": "real-turn", "item_id": "real-item"}
        async with self.session.get(root + "/history-prompt", params=target, headers=headers) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["text"], "original")
        self.assertEqual(self.calls, [("history_edit_prompt", (document["client_id"], "source-id"), target)])
        async with self.session.post(root + "/revert", json={"turn_id": "real-turn"}, headers=headers) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.json(), {"accepted": True, "thread_id": "source-id"})
        self.assertEqual(self.calls[-1], ("revert", (document["client_id"], "source-id"), {"turn_id": "real-turn"}))
