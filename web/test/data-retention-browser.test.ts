import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';

let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-retention-browser-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] }, server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/`;
  browser = await chromium.launch({ headless: true, ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

it.each([1280, 390])('updates independent periods, cleans expired data and fits width %s', async width => {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width, height: 900 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [], writes: unknown[] = [];
  let policy = { records_days: 30, attachments_days: 30 }, cleanups = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/api/events?*', socket => {
    socket.onMessage(message => { if (message === 'ping') socket.send('pong'); });
    setTimeout(() => socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision: 0 })), 20);
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    let payload: unknown;
    if (path === '/api/client/register') payload = registration();
    else if (path === '/api/meta') payload = { ...meta, writer_profile: { selected_thread_id: '', working_dir: '/work', scope_generation: 1 } };
    else if (path === '/api/settings/next-turn') payload = { runtime_epoch: 'epoch-1', revision: 0, next_turn_settings: meta.next_turn_settings };
    else if (path === '/api/operator-status') payload = { status: 'ok', observed_at: 1, poll_after_seconds: 60, warnings: [], runtime_loop: {} };
    else if (path === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision: 0, scope: new URL(request.url()).searchParams.get('scope') ?? 'global', archived: false, limit: 100, truncated: false, threads: [] };
    else if (path === '/api/settings/data-retention') {
      if (request.method() === 'POST') { const body = request.postDataJSON(); writes.push(body); policy = { ...policy, ...body }; }
      payload = policy;
    } else if (path === '/api/data/prune') {
      expect(request.postDataJSON()).toEqual({});
      cleanups += 1;
      payload = { policy, results: { test: { records: 3, bytes_freed: 5 } }, errors: {}, records: 3, bytes_freed: 5 };
    } else { await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: path } }) }); return; }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  try {
    await page.goto(url);
    await page.getByRole('button', { name: /settings/i }).first().click();
    const records = page.getByLabel('Focus record retention', { exact: true });
    const attachments = page.getByLabel('Attachment retention', { exact: true });
    await records.waitFor();
    await records.selectOption('7');
    await page.waitForFunction(() => !(document.querySelector('#retention-attachments_days') as HTMLSelectElement)?.disabled);
    await attachments.selectOption('90');
    await page.waitForFunction(() => !(document.querySelector('#retention-records_days') as HTMLSelectElement)?.disabled);
    expect(writes).toEqual([{ records_days: 7 }, { attachments_days: 90 }]);
    expect(await records.inputValue()).toBe('7');
    expect(await attachments.inputValue()).toBe('90');
    await page.evaluate(() => {
      const key = 'kimi-web.draft.expired';
      localStorage.setItem(key, 'old draft');
      const metadata = JSON.parse(localStorage.getItem('focus-web.data-retention.v1') ?? '{"drafts":{},"history":{}}');
      metadata.drafts[key] = Date.now() - 8 * 86_400_000;
      localStorage.setItem('focus-web.data-retention.v1', JSON.stringify(metadata));
      localStorage.setItem('kimi-web.color-scheme', 'dark');
    });
    await page.getByRole('button', { name: 'Clean expired data now', exact: true }).click();
    await page.getByRole('status').filter({ hasText: 'Cleaned 3 server items and 1 browser items.' }).waitFor();
    expect(cleanups).toBe(1);
    expect(await page.evaluate(() => localStorage.getItem('kimi-web.draft.expired'))).toBeNull();
    expect(await page.evaluate(() => localStorage.getItem('kimi-web.color-scheme'))).toBe('dark');
    const bounds = await page.locator('.retention-settings').boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    if (process.env.FOCUS_RETENTION_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.FOCUS_RETENTION_SCREENSHOT_DIR}/retention-${width}.png` });
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 60_000);
