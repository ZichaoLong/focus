import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
let server: ViteDevServer;
let browser: Browser;
let url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-notices-browser-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/test/fixtures/fork-notices.html`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => {
  await browser?.close(); await server?.close();
  rmSync(cacheDir, { recursive: true, force: true });
});
it('presents a persistent success note with working copy and dismissal actions', async () => {
  const page = await browser.newPage();
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto(url);
  const note = page.getByTestId('fork-note');
  await note.waitFor();
  expect(await note.getAttribute('class')).toContain('ui-banner--info');
  expect(await note.innerText()).toContain('本次未在全局列表中找到');
  await note.getByRole('button', { name: '复制线程 ID' }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('branch-exact-id');
  expect(await page.locator('.ui-banner--danger').count()).toBe(0);
  await note.getByRole('button', { name: '知道了' }).click();
  await note.waitFor({ state: 'detached' });
  expect(errors).toEqual([]);
  await page.close();
}, 30_000);
