import type { ServerResponse } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { afterAll, beforeAll, expect, it } from 'vitest';

const cacheDir = mkdtempSync(join(tmpdir(), 'focus-apk-progress-'));
const size = 64 * 1024;
let browser: Browser, server: ViteDevServer, origin: string;
let acceptTransfer: (response: ServerResponse) => void;
beforeAll(async () => {
  server = await createServer({
    cacheDir, logLevel: 'error', server: { host: '127.0.0.1', port: 0 },
    optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    plugins: [{ name: 'apk-test-stream', configureServer(dev) {
      dev.middlewares.use('/api/mobile/android/apk/', (_request, response) => {
        response.writeHead(200, { 'Content-Length': size });
        response.flushHeaders();
        acceptTransfer(response);
      });
    } }],
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  origin = 'http://127.0.0.1:' + address.port;
  browser = await chromium.launch({ executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE });
}, 60_000);
afterAll(async () => {
  await browser?.close(); await server?.close();
  rmSync(cacheDir, { recursive: true, force: true });
});

it('shows acknowledged bytes on both APK paths, clears failed transfers and verifies before handoff', async () => {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width: 390, height: 844 } });
  try {
    await page.addInitScript(() => {
      const id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
      window.__focusMobile = { version: 1, instance: id, ticket: id, features: ['android-update'] };
      let bytes = 0;
      window.prompt = (op = '', data = '') => {
        const action = op.split('/').pop();
        if (action === 'apk-info') return JSON.stringify({ version: '1', version_code: 1, sha256: 'a'.repeat(64) });
        if (action === 'apk-begin') bytes = 0;
        if (action === 'apk-write') bytes += atob(data).length;
        if (action === 'apk-save' || action === 'apk-finish' || action === 'apk-abort') {
          const status = document.querySelector('.mobile-release [role="status"]')?.textContent;
          document.documentElement.dataset.handoff = [action, bytes, status].join('|');
        }
        return 'ok';
      };
    });
    let ready!: () => void;
    const checked = new Promise<void>(resolve => { ready = resolve; });
    await page.route('**/test-channel', async route => {
      await checked;
      await route.fulfill({ json: { checked_at: 1, stale: false, release: {
        package: 'org.focus.mobile', version: '2', version_code: 2, source_revision: 'c'.repeat(40),
        sha256: 'b'.repeat(64), certificate_sha256: 'd'.repeat(64), size,
      } } });
    });
    await page.goto(origin + '/test/fixtures/android-download.html');
    await page.getByRole('button', { name: 'Check client update' }).click();
    await page.getByText('Checking for an update and preparing the APK…').waitFor();
    ready();

    for (const action of ['interrupt', 'save', 'install']) {
      const opened = new Promise<ServerResponse>(resolve => { acceptTransfer = resolve; });
      await page.getByRole('button', { name: action === 'save' ? 'Save APK' : 'Download and install' }).click();
      const stream = await opened;
      const bar = page.getByRole('progressbar');
      expect(await bar.getAttribute('value')).toBe('0');
      stream.write(Buffer.alloc(size / 4));
      await page.getByText('Downloading APK · 25% (16.0 KiB / 64.0 KiB)').waitFor();
      expect(await bar.getAttribute('value')).toBe(String(size / 4));
      if (action === 'interrupt') stream.destroy();
      else stream.end(Buffer.alloc(size * 3 / 4));
      const handoff = action === 'interrupt' ? 'apk-abort|16384|'
        : (action === 'save' ? 'apk-save' : 'apk-finish') + '|65536|Verifying the APK…';
      await expect.poll(() => page.locator('html').getAttribute('data-handoff')).toBe(handoff);
      await bar.waitFor({ state: 'detached' });
      if (action === 'save') await page.getByText('APK saved.').waitFor();
    }
  } finally { await page.close(); }
}, 60_000);
