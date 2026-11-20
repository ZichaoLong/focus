import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';
import type { FocusUpdateStatus } from '../src/focus/types';

let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-update-cancel-browser-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => {
  await browser?.close(); await server?.close();
  rmSync(cacheDir, { recursive: true, force: true });
});

const cases = [
  { mode: 'normal', width: 1280 }, { mode: 'lost', width: 1280 },
  { mode: 'ready', width: 390 }, { mode: 'normal', width: 390 }, { mode: 'applying', width: 390 },
];
it.each(cases)('cancels preparation before checking another target: $mode at width $width', async ({ mode, width }) => {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width, height: 900 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [], posts: Array<{ path: string; body: Record<string, unknown> }> = [];
  const source = { url: 'https://example.com/focus.git', branch: 'main' };
  let status: FocusUpdateStatus = {
    source, operation_source: null, operation_id: '', target: '', state: 'idle',
    requested_commit: '', resolved_commit: '', message: '', error: '', preflight: {},
    updated_at: Date.now() / 1000, restart_required: false, installation_started: false,
    phase: 'idle', phase_started_at: Date.now() / 1000, last_progress_at: Date.now() / 1000, progress: null,
  };
  if (mode === 'ready') status = { ...status, target: 'main', operation_source: source,
    operation_id: 'd'.repeat(32), resolved_commit: 'e'.repeat(40), state: 'ready', phase: 'ready' };
  if (mode === 'applying') status = { ...status, target: 'main', operation_source: source,
    operation_id: 'c'.repeat(32), state: 'applying', phase: 'apply_install', installation_started: true, restart_required: true };
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/api/events?*', socket => {
    socket.onMessage(message => { if (message === 'ping') socket.send('pong'); });
    setTimeout(() => socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision: 0 })), 20);
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    const body = request.method() === 'POST' ? request.postDataJSON() ?? {} : {};
    if (request.method() === 'POST') posts.push({ path, body });
    let payload: unknown;
    if (path === '/api/client/register') payload = registration();
    else if (path === '/api/meta') payload = meta;
    else if (path === '/api/settings/next-turn') payload = { runtime_epoch: 'epoch-1', revision: 0, next_turn_settings: meta.next_turn_settings };
    else if (path === '/api/operator-status') payload = { status: 'ok', observed_at: 1, poll_after_seconds: 60, warnings: [], runtime_loop: {} };
    else if (path === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision: 0, scope: 'current', archived: false, limit: 100, truncated: false, threads: [] };
    else if (path === '/api/update') payload = status;
    else if (path === '/api/update/check') {
      status = { ...status, target: body.target, state: 'checking', phase: body.target === 'stable' ? 'release_download' : 'source_clone',
        operation_id: body.target === 'stable' ? 'a'.repeat(32) : 'b'.repeat(32), operation_source: body.target === 'main' ? source : null };
      payload = status;
    } else if (path === '/api/update/apply') {
      status = { ...status, state: 'applying', phase: 'apply_validate' };
      await route.abort('connectionreset'); return;
    } else if (path === '/api/update/cancel') {
      expect(body).toEqual({ operation_id: 'a'.repeat(32) });
      status = { ...status, state: 'cancelling', phase: 'cancelling' };
      if (mode === 'lost') { await route.abort('connectionreset'); return; }
      payload = status;
    } else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: path } }) });
      return;
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  try {
    await page.goto(url);
    const settings = page.getByRole('button', { name: width === 390 ? 'Session settings' : 'Settings', exact: true });
    await settings.click();
    await page.getByRole('tab', { name: 'Server update', exact: true }).click();
    const main = page.getByRole('button', { name: 'Check and prepare main', exact: true });
    const stable = page.getByRole('button', { name: 'Check and prepare stable', exact: true });
    if (mode === 'ready') {
      await page.getByRole('button', { name: 'Apply update and restart' }).click();
      const confirm = page.getByRole('dialog', { name: 'Apply this Focus update?', exact: true })
      await confirm.getByText(/main eeeeeeeeeeee/).waitFor();
      expect(await confirm.getByRole('textbox').count()).toBe(0);
      await confirm.getByRole('button', { name: 'Apply update and restart' }).click();
      await page.getByText('Applying update', { exact: true }).first().waitFor();
      expect(posts.filter(p => p.path === '/api/update/apply').map(p => p.body)).toEqual([
        { operation_id: 'd'.repeat(32), confirmation: 'd'.repeat(32) },
      ]);
      return;
    }
    if (mode === 'applying') {
      await page.getByText('Applying update', { exact: true }).first().waitFor();
      expect(await page.getByRole('button', { name: 'Cancel preparation', exact: true }).count()).toBe(0);
      expect(await main.isDisabled()).toBe(true);
      expect(await stable.isDisabled()).toBe(true);
      return;
    }
    await stable.click();
    const cancel = page.getByRole('button', { name: 'Cancel preparation', exact: true });
    await cancel.waitFor();
    expect(await main.isDisabled()).toBe(true);
    expect(await stable.isDisabled()).toBe(true);
    await cancel.click();
    const cancelling = page.getByRole('button', { name: 'Cancelling preparation', exact: true });
    await cancelling.waitFor();
    expect(await cancelling.isDisabled()).toBe(true);
    expect(await main.isDisabled()).toBe(true);
    expect(posts.filter(p => p.path === '/api/update/cancel')).toHaveLength(1);
    const dialog = page.getByRole('dialog', { name: 'Focus Web', exact: true });
    await page.screenshot({ path: join(tmpdir(), `focus-update-cancel-${width}.png`), fullPage: true });
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if (width === 390) await page.screenshot({ path: join(tmpdir(), 'focus-update-cancel-mobile.png'), fullPage: true });
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    await settings.click();
    await cancelling.waitFor();
    expect(await main.isDisabled()).toBe(true);
    status = { ...status, state: 'cancelled', phase: 'cancelled' };
    await expect.poll(() => main.isEnabled(), { timeout: 5000 }).toBe(true);
    await main.click();
    await cancel.waitFor();
    expect(posts.filter(p => p.path === '/api/update/check').map(p => p.body)).toEqual([
      { target: 'stable', commit: '' }, { target: 'main', commit: '' },
    ]);
    expect(posts.filter(p => p.path === '/api/update/cancel')).toHaveLength(1);
    expect(posts.filter(p => p.path === '/api/update/apply')).toEqual([]);
    expect(errors).toEqual([]);
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.stack : String(error)}\nBrowser errors: ${JSON.stringify(errors)}\nPage: ${(await page.locator('body').innerText()).slice(0, 3500)}`);
  } finally { await page.close(); }
}, 45_000);
