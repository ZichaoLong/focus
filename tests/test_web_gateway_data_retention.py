import asyncio
import threading

from bot.data_retention import DataRetentionService
from bot.data_retention_contract import DataPruneResult
from bot.stores.data_retention_store import DataRetentionStore
from tests.web_runtime.gateway_harness import WebGatewayHarness


class DataRetentionGatewayTests(WebGatewayHarness):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.owner = DataRetentionService(DataRetentionStore(self.root), {'test': lambda *_: DataPruneResult(2, 10)})
        self.gateway._ports.data_retention_read = self.owner.policy
        self.gateway._ports.data_retention_update = self.owner.update
        self.gateway._ports.data_prune = self.owner.prune

    async def test_authenticated_partial_settings_and_cleanup_require_csrf(self):
        async with self.session.get(f'{self.endpoint}/api/settings/data-retention') as response:
            assert response.status == 401
        await self._authenticate()
        document = await self._register_document(resume_client_id='retention', incarnation_id='doc')
        headers = self._client_headers(document)
        async with self.session.get(f'{self.endpoint}/api/settings/data-retention', headers=headers) as response:
            assert response.status == 200
            assert await response.json() == {'records_days': 30, 'attachments_days': 30}
        for changes in ({'records_days': True}, {'records_days': '7'}, {'records_days': 14}, {'extra': 7}, {}):
            async with self.session.post(f'{self.endpoint}/api/settings/data-retention', headers=headers, json=changes) as response:
                assert response.status == 400
        async with self.session.post(f'{self.endpoint}/api/settings/data-retention', headers=headers, json={'records_days': 90}) as response:
            assert response.status == 200
            assert await response.json() == {'records_days': 90, 'attachments_days': 30}
        no_csrf = {key: value for key, value in headers.items() if key != 'X-Focus-Web-Csrf'}
        async with self.session.post(f'{self.endpoint}/api/data/prune', headers=no_csrf, json={}) as response:
            assert response.status == 403
        async with self.session.post(f'{self.endpoint}/api/data/prune', headers=headers, json={}) as response:
            assert response.status == 200
            result = await response.json()
            assert result['records'] == 2 and result['errors'] == {}
        assert self.calls == []

    async def test_cleanup_runs_outside_gateway_loop_and_holds_document_operation(self):
        await self._authenticate()
        document = await self._register_document(resume_client_id='retention', incarnation_id='doc')
        headers = self._client_headers(document)
        entered, release = threading.Event(), threading.Event()
        def prune():
            entered.set()
            assert release.wait(5)
            return self.owner.prune()
        self.gateway._ports.data_prune = prune
        pending = asyncio.create_task(self.session.post(f'{self.endpoint}/api/data/prune', headers=headers, json={}))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            # Another document's read remains responsive during disk maintenance.
            other = await self._register_document(resume_client_id='other', incarnation_id='other-doc')
            async with self.session.get(f'{self.endpoint}/api/settings/data-retention', headers=self._client_headers(other)) as response:
                assert response.status == 200
        finally:
            release.set()
            response = await pending
            await response.read()
            response.release()
