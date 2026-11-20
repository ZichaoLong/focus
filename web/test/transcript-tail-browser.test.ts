import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';
import { snapshot, thread } from './focus_client/support';
import type { ChatTurn } from '../src/types';

let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-transcript-tail-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Expected a local browser-test address');
  url = 'http://127.0.0.1:' + address.port + '/?thread=thread-1';
  browser = await chromium.launch({ headless: true, executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

function reply(id: string, text: string): ChatTurn {
  return { id: 'turn-1:item:' + id + ':0', rawTurnId: 'turn-1', itemId: id, role: 'assistant', no: 0,
    text, blocks: [{ kind: 'text', text }], reply: { state: 'complete' } };
}
function tools(start: number, count: number): ChatTurn[] {
  return Array.from({ length: count }, (_, i) => {
    const id = 'tool-' + (start + i);
    const tool = { id, name: 'Shell', arg: 'sample', status: 'ok' as const, output: [] };
    return { ...reply(id, ''), contentDeferred: true, tools: [tool], blocks: [{ kind: 'tool', tool }] };
  });
}
type Fixture = { page: Page; reads: string[] };
async function fixture(width: number, prosePage: number, run: (f: Fixture) => Promise<void>, holdFill?: Promise<void>) {
  const page = await browser.newPage({ viewport: { width, height: width < 500 ? 844 : 880 }, hasTouch: width < 500 });
  page.setDefaultTimeout(12_000);
  const reads: string[] = [], errors: string[] = [];
  page.on('pageerror', err => errors.push(err.message));
  const source = { ...thread(), name: 'Folded tools', title: 'Folded tools', source: 'cli', ephemeral: false,
    session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  await page.routeWebSocket('**/api/events?*', socket => {
    socket.onMessage(msg => { if (msg === 'ping') socket.send('pong'); });
    setTimeout(() => socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision: 1 })), 10);
  });
  await page.route('**/api/**', async route => {
    const { pathname, searchParams: query } = new URL(route.request().url());
    let payload: unknown;
    if (pathname === '/api/client/register') payload = registration();
    else if (pathname === '/api/meta') payload = { ...meta, revision: 1, writer_profile: { ...meta.writer_profile, selected_thread_id: 'thread-1' } };
    else if (pathname === '/api/settings/next-turn') payload = { runtime_epoch: 'epoch-1', revision: 1, next_turn_settings: meta.next_turn_settings };
    else if (pathname === '/api/operator-status') payload = { status: 'ok', observed_at: 1, poll_after_seconds: 60, warnings: [], runtime_loop: {} };
    else if (pathname === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision: 1, scope: query.get('scope') ?? 'global',
      archived: false, limit: 100, truncated: false, threads: [source] };
    else if (pathname.endsWith('/transcript')) {
      let rows: ChatTurn[] = [], older: string | null = null;
      const view = query.get('view') ?? 'transcript', cursor = Number(query.get('cursor'));
      if (view === 'transcript') {
        const fill = query.has('fill');
        reads.push(cursor ? (fill ? 'fill-' : 'older-') + cursor : 'head');
        if (fill && holdFill) await holdFill;
        if (!cursor) rows = [...tools(1, 17), reply('middle', reads.length === 1 ? 'First read.' : 'Confirmed latest.'), ...tools(18, 22)];
        else if (cursor === prosePage) rows = [reply('earlier', 'Previous discussion.\n\n'.repeat(60))];
        else rows = tools(-40 * cursor, 40);
        older = cursor < prosePage ? String(cursor + 1) : null;
      }
      payload = { runtime_epoch: 'epoch-1', revision: 1, thread_id: source.id, turn_id: null, view, target_pending: false,
        turns: rows, older_cursor: older, newer_cursor: cursor ? 'forward-' + cursor : null, full_text: null };
    } else if (/\/api\/threads\/thread-1(?:\/open)?$/.test(pathname)) {
      payload = { ...snapshot('none', 'thread-1', 1), revision: 1, thread: source, active_turn_context: null };
    } else return route.fulfill({ status: 404, json: { error: { code: 'unavailable', message: pathname } } });
    await route.fulfill({ json: payload });
  });
  try {
    await page.goto(url);
    await page.locator('.md').getByText('First read.', { exact: true }).waitFor({ timeout: 30_000 });
    await page.evaluate(() => document.fonts.ready);
    await run({ page, reads });
    expect(errors).toEqual([]);
  } catch (error) {
    throw new Error(String(error) + '\nBody reads: ' + JSON.stringify(reads) + '\nBrowser errors: ' + JSON.stringify(errors)
      + '\nPage: ' + (await page.locator('body').innerText()).slice(0, 600), { cause: error });
  } finally { await page.close(); }
}
async function gap(page: Page) {
  return page.locator('.panes').evaluate(pane => pane.getBoundingClientRect().bottom
    - pane.querySelector('[data-transcript-end]')!.getBoundingClientRect().top);
}
async function swipeEarlier(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 250, y: 240 }] });
  for (const y of [265, 295, 330]) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 250, y }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await cdp.detach();
}

it.each([1280, 390])('retains previously read folded history and refreshes the tail at width %s', async width => {
  await fixture(width, 2, async ({ page, reads }) => {
    if (width < 500) {
      await page.locator('.reading-mode-entry:visible').click();
      await swipeEarlier(page);
    } else {
      await page.locator('.panes').hover();
      await page.mouse.wheel(0, -90);
    }
    await expect.poll(() => page.locator('.transcript-row').count()).toBe(80);
    expect(await gap(page)).toBeGreaterThan(96);
    expect(reads).toEqual(['head', 'older-1']);
    await page.locator('.top-sentinel-btn').click();
    await page.locator('[data-turn-id*=":earlier:"]').first().waitFor({ state: 'attached' });
    await page.locator('.newmsg-pill').click();
    await page.getByText('Confirmed latest.', { exact: true }).first().waitFor();
    await expect.poll(() => gap(page)).toBeLessThanOrEqual(32);
    expect(await page.locator('.transcript-row').count()).toBe(81);
    expect(await page.locator('.tool-group-head[aria-expanded="true"]').count()).toBe(0);
    expect(reads).toEqual(['head', 'older-1', 'older-2', 'head']);
  });
}, 45_000);

it.each([2, 4])('stops filling on visible prose or at the request limit (prose page %s)', async prosePage => {
  await fixture(390, prosePage, async ({ page, reads }) => {
    await page.locator('.top-sentinel-btn').click();
    await page.locator('.newmsg-pill').click();
    await expect.poll(() => page.locator('.transcript-row').count()).toBe(prosePage === 2 ? 81 : 160);
    await page.locator('.panes.is-following').waitFor();
    if (prosePage === 2) {
      await expect.poll(() => gap(page)).toBeLessThanOrEqual(32);
      expect(reads).toEqual(['head', 'older-1', 'head', 'fill-2']);
    } else {
      expect(await gap(page)).toBeGreaterThan(96);
      await page.locator('.reading-mode-entry:visible').click();
      await page.locator('.top-sentinel-btn').click();
      await expect.poll(() => page.locator('.transcript-row').count()).toBe(161);
      expect(reads).toEqual(['head', 'older-1', 'head', 'fill-2', 'fill-3', 'older-4']);
    }
  });
}, 45_000);

it('leaves a small gap without requesting an extra page', async () => {
  await fixture(1280, 3, async ({ page, reads }) => {
    await page.locator('.top-sentinel-btn').click();
    await page.locator('.newmsg-pill').waitFor();
    await page.setViewportSize({ width: 1280, height: Math.round(880 - await gap(page) + 60) });
    await expect.poll(() => gap(page)).toBeLessThan(96);
    expect(await gap(page)).toBeGreaterThan(32);
    await page.locator('.newmsg-pill').click();
    await page.getByText('Confirmed latest.', { exact: true }).first().waitFor();
    await page.locator('.panes.is-following').waitFor();
    expect(reads).toEqual(['head', 'older-1', 'head']);
  });
}, 45_000);

it.each(['wheel', 'host-pause'])('retires an in-flight optional page on %s', async action => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  try {
    await fixture(1280, 3, async ({ page, reads }) => {
      await page.locator('.top-sentinel-btn').click();
      await page.locator('.newmsg-pill').click();
      await expect.poll(() => reads.at(-1)).toBe('fill-2');
      if (action === 'wheel') {
        await page.locator('.panes').hover();
        await page.mouse.wheel(0, -65);
      } else await page.evaluate(() => window.dispatchEvent(new Event('focus-host-pause')));
      await page.locator('.top-sentinel-btn:enabled').waitFor();
      release();
      expect(await page.locator('.transcript-row').count()).toBe(80);
      await page.locator('.top-sentinel-btn').click();
      await expect.poll(() => page.locator('.transcript-row').count()).toBe(120);
      expect(reads).toEqual(['head', 'older-1', 'head', 'fill-2', 'older-2']);
    }, pending);
  } finally { release(); }
}, 45_000);
