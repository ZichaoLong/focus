from __future__ import annotations

import gzip

from tests.web_runtime.gateway_harness import WebGatewayHarness


class StaticAssetDeliveryTests(WebGatewayHarness):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.asset = self.root / 'static' / 'assets' / 'app-123.js'
        self.asset.parent.mkdir()
        self.source = b'console.log("Focus static asset");\n' * 1000
        self.compressed = gzip.compress(self.source, mtime=0)
        self.asset.write_bytes(self.source)
        self.asset.with_suffix('.js.gz').write_bytes(self.compressed)
        self.url = f'{self.endpoint}/assets/{self.asset.name}'

    async def test_gzip_negotiation_preserves_source_type_and_cache_policy(self):
        for accepted, compressed in (
            ('gzip, deflate, br', True),
            ('GZIP; q=0.5', True),
            ('*', True),
            ('', False),
            ('identity', False),
            ('br', False),
            ('gzip;q=0, *;q=1', False),
            ('gzip;q=0.4, identity;q=1', False),
            ('xgzip', False),
            ('gzip;q=invalid', False),
        ):
            with self.subTest(accepted=accepted):
                async with self.session.get(
                    self.url, headers={'Accept-Encoding': accepted}, auto_decompress=False,
                ) as response:
                    self.assertEqual(response.status, 200)
                    body = await response.read()
                    self.assertEqual(body, self.compressed if compressed else self.source)
                    self.assertEqual(response.headers.get('Content-Encoding'), 'gzip' if compressed else None)
                    self.assertIn('javascript', response.headers['Content-Type'])
                    self.assertEqual(response.headers['Vary'], 'Accept-Encoding')
                    self.assertEqual(response.headers['Cache-Control'], 'public, max-age=31536000, immutable')
                    self.assertEqual(int(response.headers['Content-Length']), len(body))
                    self.assertIn('Content-Security-Policy', response.headers)
                    if compressed:
                        self.assertEqual(gzip.decompress(body), self.source)

    async def test_validators_and_head_use_the_selected_representation(self):
        etags = {}
        for coding, body in (('identity', self.source), ('gzip', self.compressed)):
            headers = {'Accept-Encoding': coding}
            async with self.session.get(self.url, headers=headers, auto_decompress=False) as response:
                etags[coding] = response.headers['ETag']
                self.assertEqual(await response.read(), body)
            async with self.session.get(
                self.url, headers={**headers, 'If-None-Match': etags[coding]},
            ) as response:
                self.assertEqual(response.status, 304)
                self.assertEqual(response.headers['Vary'], 'Accept-Encoding')
                self.assertEqual(response.headers['ETag'], etags[coding])
                self.assertEqual(await response.read(), b'')
            async with self.session.head(self.url, headers=headers) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(int(response.headers['Content-Length']), len(body))
                self.assertEqual(response.headers['ETag'], etags[coding])
                self.assertEqual(await response.read(), b'')
        self.assertNotEqual(etags['identity'], etags['gzip'])
        async with self.session.get(
            self.url, headers={'Accept-Encoding': 'gzip', 'If-None-Match': etags['identity']},
            auto_decompress=False,
        ) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(await response.read(), self.compressed)

    async def test_ranges_and_missing_compressed_siblings_keep_file_response_behavior(self):
        async with self.session.get(
            self.url, headers={'Accept-Encoding': 'gzip', 'Range': 'bytes=0-31'},
            auto_decompress=False,
        ) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.headers['Content-Range'], f'bytes 0-31/{len(self.compressed)}')
            self.assertEqual(await response.read(), self.compressed[:32])
        self.asset.with_suffix('.js.gz').unlink()
        async with self.session.get(self.url, headers={'Accept-Encoding': 'gzip'}) as response:
            self.assertEqual(response.status, 200)
            self.assertNotIn('Content-Encoding', response.headers)
            self.assertEqual(await response.read(), self.source)

    async def test_entry_document_remains_no_store_with_compression_and_spa_fallback(self):
        index = self.root / 'static' / 'index.html'
        body = index.read_bytes()
        index.with_suffix('.html.gz').write_bytes(gzip.compress(body, mtime=0))
        for path in ('/', '/index.html', '/conversation'):
            async with self.session.get(
                f'{self.endpoint}{path}', headers={'Accept-Encoding': 'gzip'},
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers['Content-Encoding'], 'gzip')
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn('text/html', response.headers['Content-Type'])
                self.assertEqual(await response.read(), body)
