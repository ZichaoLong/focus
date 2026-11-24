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
type Fixture = { page: Page; reads: string[]; pings(): number; update(row: ChatTurn): void; disconnect(): void; refuseNextCursor(): void };
type FixtureOptions = {
  onFill?(cursor: number): Promise<void> | void;
  pages?: ChatTurn[][];
  mobileTabs?: boolean;
  running?: boolean;
  fromProfile?: boolean;
  height?: number;
  compactPages?: boolean;
};
async function fixture(width: number, prosePage: number, run: (f: Fixture) => Promise<void>,
  { onFill, pages, mobileTabs, running, fromProfile, height, compactPages }: FixtureOptions = {}) {
  const page = await browser.newPage({ viewport: { width, height: height ?? (width < 500 ? 844 : 880) }, hasTouch: width < 500 });
  page.setDefaultTimeout(12_000);
  const reads: string[] = [], errors: string[] = [];
  let update: (row: ChatTurn) => void, revision = 1;
  let closeSocket: () => void, refuseFill = false, cursorBase = 0, pings = 0;
  page.on('pageerror', err => errors.push(err.message));
  if (mobileTabs) await page.addInitScript(() => {
    window.__focusMobile = { version: 1, instance: '7ebb390f-2699-49de-ab09-95c6c5f53b76',
      ticket: crypto.randomUUID(), features: ['tabs', 'resume', 'wake'] };
    window.prompt = () => 'ok';
  });
  const source = { ...thread(), name: 'Folded tools', title: 'Folded tools', source: 'cli', ephemeral: false,
    session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  await page.routeWebSocket('**/api/events?*', socket => {
    update = row => socket.send(JSON.stringify({ type: 'thread_delta', runtime_epoch: 'epoch-1', revision: ++revision,
      thread_id: source.id, reason: 'item/completed', detail: { method: 'item/completed', turn_id: 'turn-1', item_turns: [row] } }));
    closeSocket = () => socket.close({ code: 1011, reason: 'Test reconnect' });
    socket.onMessage(msg => { if (msg === 'ping') { pings++; socket.send('pong'); } });
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
      let toolPages: { turn_id: string; cursor: string; items: string[][] }[] | undefined;
      const view = query.get('view') ?? 'transcript', wireCursor = query.get('cursor');
      const cursor = wireCursor ? Number(wireCursor) - cursorBase : 0;
      const anchor = query.get('item_id');
      if (anchor) {
        reads.push('anchor-' + anchor);
        rows = [reply(anchor, 'Previous discussion.\n\n'.repeat(60))];
      } else if (view === 'transcript') {
        const fill = query.has('fill');
        reads.push(wireCursor ? (fill ? 'fill-' : 'older-') + wireCursor : 'head');
        if (fill) await onFill?.(cursor);
        if (fill && refuseFill) {
          refuseFill = false;
          cursorBase += 10;
          return route.fulfill({ status: 409, json: { error: { code: 'stale_thread_read', message: 'Read superseded' } } });
        }
        if (compactPages && fill) {
          expect(route.request().headers()['x-focus-folded-tools']).toBe('1');
          rows = [reply('earlier', 'Previous discussion.\n\n'.repeat(60))];
          toolPages = [[1, 20], [21, 40]].map(([start, size]) => ({
            turn_id: 'turn-1', cursor: 'members-' + start,
            items: tools(start!, size!).map(row => [row.itemId!, 'ok']),
          }));
        } else if (compactPages && wireCursor?.startsWith('members-')) {
          const start = Number(wireCursor.slice(8));
          rows = tools(start, start === 1 ? 20 : 40);
        } else if (pages) rows = pages[cursor]!;
        else if (!cursor) rows = [...tools(1, 17), reply('middle', reads.length === 1 ? 'First read.' : 'Confirmed latest.'), ...tools(18, 22)];
        else if (cursor === prosePage) rows = [reply('earlier', 'Previous discussion.\n\n'.repeat(60))];
        else rows = tools(-40 * cursor, 40);
        older = cursor < prosePage ? String(cursorBase + cursor + 1) : null;
      }
      payload = { runtime_epoch: 'epoch-1', revision: 1, thread_id: source.id, turn_id: query.get('turn_id'), view, target_pending: false,
        turns: rows, ...(toolPages ? { tool_pages: toolPages } : {}), older_cursor: older, newer_cursor: anchor ? 'after-anchor' : cursor ? 'forward-' + cursor : null, full_text: null };
    } else if (/\/api\/threads\/thread-1(?:\/open)?$/.test(pathname)) {
      const unknown = { value: '', source: 'unknown' };
      payload = { ...snapshot('none', 'thread-1', 1), revision: 1, thread: source,
        active_turn_id: running ? 'turn-1' : '', active_turn_status: running ? 'inProgress' : '',
        active_turn_context: running ? { turn_id: 'turn-1', initiator: { kind: 'fcodex', binding_id: '' }, feishu_audience: [],
          settings: { model: unknown, reasoning_effort: unknown, approval_policy: unknown, permissions_profile_id: unknown } } : null };
    } else return route.fulfill({ status: 404, json: { error: { code: 'unavailable', message: pathname } } });
    await route.fulfill({ json: payload });
  });
  try {
    await page.goto(fromProfile ? new URL('/?focusApp=1', url).href : url);
    const first = pages ? page.locator('.tool-group-head').first() : page.locator('.md').getByText('First read.', { exact: true });
    await first.waitFor({ timeout: 30_000 });
    await page.evaluate(() => document.fonts.ready);
    await run({ page, reads, update: row => update(row), pings: () => pings, disconnect: () => closeSocket(), refuseNextCursor: () => { refuseFill = true; } });
    expect(errors).toEqual([]);
  } catch (error) {
    const viewport = await page.locator('.panes').evaluateAll(panes => panes.map(pane => ({
      following: pane.classList.contains('is-following'), top: pane.scrollTop,
      range: pane.scrollHeight - pane.clientHeight,
      end: pane.querySelector('[data-transcript-end]')?.getBoundingClientRect().top,
      bottom: pane.getBoundingClientRect().bottom,
    })));
    throw new Error(String(error) + '\nBody reads: ' + JSON.stringify(reads) + '\nBrowser errors: ' + JSON.stringify(errors)
      + '\nViewport: ' + JSON.stringify(viewport) + '\nPage: ' + (await page.locator('body').innerText()).slice(0, 600), { cause: error });
  } finally { await page.close(); }
}
async function gap(page: Page) {
  return page.locator('.panes').evaluate(pane => pane.getBoundingClientRect().bottom
    - pane.querySelector('[data-transcript-end]')!.getBoundingClientRect().top);
}
async function expectVisibleTail(page: Page) {
  await page.locator('.panes.is-following').waitFor();
  await expect.poll(async () => Math.abs(await gap(page)), { timeout: 5_000 }).toBeLessThanOrEqual(32);
}
async function swipeEarlier(page: Page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: 250, y: 240 }] });
  for (const y of [265, 295, 330]) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: 250, y }] });
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
  await cdp.detach();
}

it.each(['server selection', 'healthy socket', 'reconnect before resume', 'reconnect after resume', 'historical reader'])(
  'returns from the launcher with a short running transcript (%s)', async scenario => {
    const pages = [[reply('progress', '正在复核这一步的数值，并与已有的实验记录对照。'.repeat(4)), ...tools(1, 37)],
      [reply('earlier', 'Previous discussion.\n\n'.repeat(60))]];
    await fixture(440, 1, async ({ page, reads, pings, disconnect }) => {
      await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
      await page.locator('.reading-mode-entry:visible').click();
      await expectVisibleTail(page);
      expect(reads).toEqual(['head', 'fill-1']);
      if (scenario === 'historical reader') {
        await swipeEarlier(page);
        await page.locator('.panes:not(.is-following)').waitFor();
      }
      const start = reads.length;
      await page.evaluate(() => window.dispatchEvent(new Event('focus-host-pause')));
      if (scenario === 'reconnect before resume') {
        disconnect();
        await expect.poll(() => reads.slice(start), { timeout: 12_000 }).toEqual(['head']);
        await expect.poll(() => gap(page)).toBeGreaterThan(96);
      }
      await page.evaluate(() => {
        window.dispatchEvent(new Event('focus-host-resume'));
        document.dispatchEvent(new Event('visibilitychange'));
        window.dispatchEvent(new Event('focus-host-resume'));
      });
      if (scenario === 'reconnect after resume' || scenario === 'historical reader') disconnect();
      if (scenario === 'historical reader') {
        await expect.poll(() => reads.slice(start), { timeout: 12_000 }).toEqual([expect.stringMatching(/^anchor-/)]);
        await page.locator('.panes:not(.is-following) .transcript-notice button').waitFor();
        return;
      }
      if (scenario.startsWith('reconnect')) {
        await expect.poll(() => reads.slice(start), { timeout: 12_000 }).toEqual(['head', 'fill-1']);
      } else {
        await expect.poll(pings).toBeGreaterThan(0);
      }
      await expectVisibleTail(page);
      await page.locator('.panes .sending-placeholder').waitFor();
      expect(await page.locator('.tool-group-head[aria-expanded="false"]').allTextContents())
        .toEqual([expect.stringContaining('37 tool calls')]);
      if (!scenario.startsWith('reconnect')) expect(reads.slice(start)).toEqual([]);
    }, { mobileTabs: true, running: true, pages, fromProfile: scenario === 'server selection' });
  }, 45_000);

it('fills the reselected instance after its confirmed tail, and restores a historical reader at the exact item', async () => {
  await fixture(390, 2, async ({ page, reads }) => {
    await expect.poll(() => page.locator('.transcript-row').count()).toBe(2);
    expect(reads).toEqual(['head', 'fill-1', 'fill-2']);
    await page.locator('.reading-mode-entry:visible').click();
    async function reselect() {
      expect(await page.evaluate(() => window.__focusSetTabActive?.(false))).toBe(true);
      expect(await page.evaluate(() => window.__focusSetTabActive?.(true))).toBe(true);
    }
    await reselect();
    await expect.poll(() => reads.slice(3)).toEqual(['head', 'fill-1', 'fill-2']);
    await expectVisibleTail(page);
    await swipeEarlier(page);
    await page.locator('.panes:not(.is-following)').waitFor();
    const previous = reads.length;
    await reselect();
    await page.locator('.transcript-notice button').waitFor();
    expect(reads.slice(previous)).toEqual([expect.stringMatching(/^anchor-/)]);
    expect(await page.locator('.panes.is-following').count()).toBe(0);
  }, { mobileTabs: true });
}, 45_000);

it.each(['resize', 'stale cursor', 'second handshake'])('fills a running folded tail on instance return after %s', async scenario => {
  await fixture(440, 1, async ({ page, reads, disconnect, refuseNextCursor }) => {
    await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
    await page.locator('.reading-mode-entry:visible').click();
    expect(await page.evaluate(() => window.__focusSetTabActive?.(false))).toBe(true);
    const start = reads.length;
    if (scenario === 'resize') await page.setViewportSize({ width: 440, height: 245 });
    if (scenario === 'stale cursor') refuseNextCursor();
    expect(await page.evaluate(() => window.__focusSetTabActive?.(true))).toBe(true);
    await page.getByText('Confirmed latest.', { exact: true }).first().waitFor({ state: 'attached' });
    if (scenario === 'resize') {
      await expect.poll(() => gap(page)).toBeLessThan(96);
      // Let the compact viewport settle before expanding it back to phone height.
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(reads.slice(start)).toEqual(['head']);
      await page.setViewportSize({ width: 440, height: 674 });
    } else if (scenario === 'second handshake') {
      await expect.poll(() => reads.slice(start)).toEqual(['head', 'fill-1']);
      await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
      disconnect();
    }
    const expected = scenario === 'stale cursor' ? ['head', 'fill-1', 'head', 'fill-11']
      : scenario === 'second handshake' ? ['head', 'fill-1', 'head', 'fill-1'] : ['head', 'fill-1'];
    await expect.poll(() => reads.slice(start), { timeout: 12_000 }).toEqual(expected);
    await page.locator('.panes.is-following .sending-placeholder').waitFor();
    await expectVisibleTail(page);
    expect(await page.locator('.tool-group-head[aria-expanded="true"]').count()).toBe(0);
  }, { mobileTabs: true, running: true });
}, 45_000);

it('honors a scroll gesture before the reselected instance has confirmed its head', async () => {
  await fixture(440, 1, async ({ page, reads }) => {
    await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
    await page.locator('.reading-mode-entry:visible').click();
    expect(await page.evaluate(() => window.__focusSetTabActive?.(false))).toBe(true);
    let release!: () => void, waiting = false;
    const pending = new Promise<void>(resolve => { release = resolve; });
    await page.route('**/threads/thread-1/transcript*', async route => {
      waiting = true;
      await pending;
      await route.fallback();
    });
    const start = reads.length;
    try {
      expect(await page.evaluate(() => window.__focusSetTabActive?.(true))).toBe(true);
      await expect.poll(() => waiting).toBe(true);
      await page.locator('.panes').hover();
      await page.mouse.wheel(0, 60);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    } finally { release(); }
    await page.locator('.md').getByText('Confirmed latest.', { exact: true }).waitFor();
    await page.setViewportSize({ width: 440, height: 880 });
    await expect.poll(() => gap(page)).toBeGreaterThan(96);
    await page.locator('.top-sentinel-btn:enabled').waitFor();
    await page.locator('.top-sentinel-btn').click();
    await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
    expect(reads.slice(start)).toEqual(['head', 'older-1']);
  }, { mobileTabs: true });
}, 45_000);

it('fills past 57 folded calls that span two source pages on a running instance return', async () => {
  const last = tools(15, 57);
  for (const item of last.slice(-8)) item.tools![0]!.status = 'error';
  const pages = [last.slice(-40),
    [...tools(1, 14), reply('progress', '正在检查各个实例切换回来之后的对话阅读位置。'.repeat(4)), ...last.slice(0, 17)],
    [reply('previous', 'Previous discussion.\n\n'.repeat(60))]];
  let holdSecond = false, release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  try {
    await fixture(440, pages.length - 1, async ({ page, reads }) => {
      await page.locator('[data-turn-id*=":previous:"]').waitFor({ state: 'attached' });
      await expectVisibleTail(page);
      await page.locator('.reading-mode-entry:visible').click();
      await expectVisibleTail(page);
      expect(await page.evaluate(() => window.__focusSetTabActive?.(false))).toBe(true);
      await page.setViewportSize({ width: 440, height: 674 });
      const start = reads.length;
      holdSecond = true;
      expect(await page.evaluate(() => window.__focusSetTabActive?.(true))).toBe(true);
      await expect.poll(() => reads.slice(start)).toEqual(['head', 'fill-1', 'fill-2']);
      const groups = page.locator('.tool-group-head[aria-expanded="false"]');
      expect(await groups.allTextContents()).toEqual([expect.stringContaining('14 tool calls'), expect.stringMatching(/57 tool calls.*8 failed/s)]);
      expect(await gap(page)).toBeGreaterThan(96);
      release();
      await page.locator('[data-turn-id*=":previous:"]').waitFor({ state: 'attached' });
      await expectVisibleTail(page);
      expect(await groups.count()).toBe(2);
      expect(reads.slice(start)).toEqual(['head', 'fill-1', 'fill-2']);
      const rebuilt = reads.length;
      await page.reload();
      await page.locator('.focus-app.reading-mode').waitFor();
      await expect.poll(() => reads.slice(rebuilt), { timeout: 12_000 }).toEqual(['head', 'fill-1', 'fill-2']);
      await expectVisibleTail(page);
      expect(await groups.count()).toBe(2);
      // The prefix can return at a new height or the original height after
      // follow frames settle. Only the later touch should leave the tail.
      for (const grow of [true, false]) {
        const clamped = await page.locator('.panes').evaluate(async (pane, grow) => {
          for (let i = 0; i < 8; i++) await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
          const content = pane.querySelector('[data-transcript-end]')!.parentElement!;
          const height = pane.scrollHeight;
          content.style.display = 'none';
          const top = pane.scrollTop;
          content.style.display = '';
          if (grow) content.style.paddingTop = '120px';
          return { top, sameHeight: pane.scrollHeight === height };
        }, grow);
        expect(clamped).toEqual({ top: 0, sameHeight: !grow });
        await expectVisibleTail(page);
      }
      await swipeEarlier(page);
      await page.locator('.panes:not(.is-following)').waitFor();
    }, { mobileTabs: true, running: true, pages, onFill: cursor => { if (holdSecond && cursor === 2) return pending; } });
  } finally { release(); }
}, 45_000);

it.each([1280, 390])('fills the ordinary live tail and keeps the read prefix on Latest at width %s', async width => {
  await fixture(width, 2, async ({ page, reads }) => {
    await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
    await expectVisibleTail(page);
    expect(reads).toEqual(['head', 'fill-1', 'fill-2']);
    expect(await page.locator('.transcript-row').count()).toBe(2);
    if (width < 500) {
      await page.locator('.reading-mode-entry:visible').click();
      await swipeEarlier(page);
    } else {
      await page.locator('.panes').hover();
      await page.mouse.wheel(0, -700);
    }
    await page.locator('.newmsg-pill').click();
    await page.getByText('Confirmed latest.', { exact: true }).first().waitFor();
    await expectVisibleTail(page);
    expect(await page.locator('.transcript-row').count()).toBe(2);
    expect(await page.locator('.tool-group-head[aria-expanded="true"]').count()).toBe(0);
    expect(reads).toEqual(['head', 'fill-1', 'fill-2', 'head']);
  });
}, 45_000);

it('limits one persistent shortfall across mode, resize and reconnect and keeps manual paging', async () => {
  await fixture(390, 4, async ({ page, reads, disconnect }) => {
    await expect.poll(() => reads).toEqual(['head', 'fill-1', 'fill-2']);
    await page.locator('.top-sentinel-btn:enabled').waitFor();
    await page.locator('.reading-mode-entry:visible').click();
    await page.setViewportSize({ width: 390, height: 664 });
    await page.setViewportSize({ width: 390, height: 880 });
    disconnect();
    await page.getByText('Confirmed latest.', { exact: true }).first().waitFor();
    await expect.poll(() => reads.at(-1)).toBe('head');
    expect(await gap(page)).toBeGreaterThan(96);
    await page.locator('.top-sentinel-btn:enabled').click();
    await expect.poll(() => reads.at(-1)).toBe('older-1');
    expect(reads.filter(read => read.startsWith('fill-'))).toHaveLength(2);
  });
}, 45_000);

it('leaves a small gap without requesting an extra page', async () => {
  await fixture(1280, 3, async ({ page, reads }) => {
    await page.locator('.panes.is-following').waitFor();
    expect(await gap(page)).toBeLessThan(96);
    expect(reads).toEqual(['head']);
  }, { height: 420 });
}, 45_000);

it.each(['wheel', 'host-pause'])('retires an in-flight optional page on %s', async action => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  try {
    await fixture(1280, 3, async ({ page, reads }) => {
      await expect.poll(() => reads.at(-1)).toBe('fill-1');
      if (action === 'wheel') {
        await page.locator('.panes').hover();
        await page.mouse.wheel(0, -65);
      } else await page.evaluate(() => window.dispatchEvent(new Event('focus-host-pause')));
      await page.locator('.top-sentinel-btn:enabled').waitFor();
      release();
      expect(await page.locator('.transcript-row').count()).toBe(1);
      await page.locator('.top-sentinel-btn').click();
      await expect.poll(() => reads.at(-1)).toBe('older-1');
      expect(reads).toEqual(['head', 'fill-1', 'older-1']);
    }, { onFill: () => pending });
  } finally { release(); }
}, 45_000);

it('opens a verified cold tool range one member page at a time', async () => {
  await fixture(1280, 1, async ({ page, reads }) => {
    await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
    const header = page.locator('.tool-group-head');
    expect(await header.innerText()).toContain('100 tool calls');
    expect(await page.locator('.transcript-row').count()).toBe(1);
    expect(reads).toEqual(['head', 'fill-1']);
    await header.click();
    await expect.poll(() => page.locator('.transcript-row').count()).toBe(61);
    await page.locator('.tool-member-page').click();
    await expect.poll(() => page.locator('.transcript-row').count()).toBe(101);
    expect(reads).toEqual(['head', 'fill-1', 'older-members-1', 'older-members-21']);
    await header.click();
    expect(await page.locator('.transcript-row').count()).toBe(1);
  }, { pages: [tools(61, 40)], compactPages: true });
}, 45_000);

it('rearms after new prose fills the viewport and a later edit makes it short again', async () => {
  await fixture(1280, 4, async ({ page, reads, update }) => {
    await expect.poll(() => reads).toEqual(['head', 'fill-1', 'fill-2']);
    await page.locator('.top-sentinel-btn:enabled').waitFor();
    update(reply('live', 'Arrived during work.\n\n'.repeat(70)));
    await expectVisibleTail(page);
    update(reply('live', 'Short edit.'));
    await page.locator('[data-turn-id*=":earlier:"]').waitFor({ state: 'attached' });
    await expectVisibleTail(page);
    expect(reads).toEqual(['head', 'fill-1', 'fill-2', 'fill-3', 'fill-4']);
  });
}, 45_000);
