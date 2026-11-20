import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type WebSocketRoute } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';
import { snapshot, thread } from './focus_client/support';

let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-reconnect-browser-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/?thread=thread-1`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

it.each([
  { mode: 'healthy', width: 390 }, { mode: 'silent', width: 390 },
  { mode: 'closed', width: 390 }, { mode: 'silent', width: 1280 },
  { mode: 'thread-roundtrip', width: 390 }, { mode: 'cold-document', width: 390 },
  { mode: 'scroll-during-reload', width: 390 }, { mode: 'scroll-during-reload', width: 1280 },
])('preserves reading and draft after foreground recovery: $mode at $width', async ({ mode, width }) => {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width, height: 900 } });
  page.setDefaultTimeout(15_000);
  const sockets: WebSocketRoute[] = [], errors: string[] = [], posts: string[] = [], targets: string[] = [];
  let broken = false, revision = 1, registrations = 0;
  const roundtrip = mode === 'thread-roundtrip';
  const bodyReads: { thread: string; item: string | null; bytes: number }[] = [];
  const scrollDuringReload = mode === 'scroll-during-reload';
  let releaseRecovery!: () => void, heldRecovery = false;
  const recoveryGate = new Promise<void>(resolve => { releaseRecovery = resolve; });
  const profile = { selected_thread_id: 'thread-1', working_dir: '/work', scope_generation: 1 };
  const source = { ...thread(), name: 'Reading recovery', title: 'Reading recovery', source: 'cli', ephemeral: false,
    session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  const other = { ...source, id: 'thread-2', title: 'Other thread', name: 'Other thread' };
  const rows = Array.from({ length: 40 }, (_, i) => {
    const sourceRow = { id: `turn-1:item:item-${i}:0`, rawTurnId: 'turn-1', itemId: `item-${i}`, role: 'assistant', no: 0 };
    if (roundtrip && i === 22) {
      const tool = { id: 'tool-22', name: 'Shell', arg: 'pwd', status: 'ok', output: [] };
      return { ...sourceRow, text: '', contentDeferred: true, tools: [tool], blocks: [{ kind: 'tool', tool }] };
    }
    return { ...sourceRow, text: `Message ${i}\n\n${'A paragraph for checking the reading position. '.repeat(12)}` };
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/api/events?*', socket => {
    const index = sockets.push(socket) - 1;
    socket.onMessage(message => { if (message === 'ping' && !(broken && index === 0)) socket.send('pong'); });
    setTimeout(() => socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision })), 20);
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), parsed = new URL(request.url()), path = parsed.pathname, query = parsed.searchParams;
    if (request.method() === 'POST') posts.push(path);
    let payload: unknown;
    if (path === '/api/client/register') { registrations++; payload = registration(); }
    else if (path === '/api/meta') payload = { ...meta, revision, writer_profile: profile };
    else if (path === '/api/settings/next-turn') payload = { runtime_epoch: 'epoch-1', revision, next_turn_settings: meta.next_turn_settings };
    else if (path === '/api/operator-status') payload = { status: 'ok', observed_at: 1, poll_after_seconds: 60, warnings: [], runtime_loop: {} };
    else if (path === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision, scope: query.get('scope') ?? 'global', archived: false, limit: 100, truncated: false, threads: roundtrip ? [source, other] : [source] };
    else if (path.endsWith('/transcript')) {
      const item = query.get('item_id');
      if (item) targets.push(item);
      if (scrollDuringReload && revision > 1 && !item && query.get('view') !== 'prompts' && !heldRecovery) {
        heldRecovery = true;
        await recoveryGate;
      }
      const start = item ? Math.max(0, rows.findIndex(row => row.itemId === item) - 2)
        : mode === 'cold-document' && registrations > 1 ? 30 : 0;
      payload = { runtime_epoch: 'epoch-1', revision, thread_id: path.split('/')[3], turn_id: query.get('turn_id'),
        view: query.get('view') ?? 'transcript', target_pending: false, turns: rows.slice(Math.max(0, start)).map(row =>
          revision > 1 ? { ...row, text: row.text.replace('Message', 'Recovered message') } : row),
        older_cursor: null, newer_cursor: null, full_text: null };
      if (roundtrip && query.get('view') !== 'prompts') {
        const bytes = Buffer.byteLength(JSON.stringify(payload));
        bodyReads.push({ thread: path.split('/')[3]!, item, bytes });
        await new Promise(resolve => setTimeout(resolve, 180 + Math.ceil(8 * bytes / 3000)));
      }
    } else if (/^\/api\/threads\/thread-[12](?:\/open)?$/.test(path)) {
      const id = path.split('/')[3]!;
      const previous = profile.selected_thread_id;
      const changed = previous !== id;
      if (changed) { profile.scope_generation++; profile.selected_thread_id = id; }
      const base = snapshot('none', id, profile.scope_generation);
      payload = { ...base, revision, thread: id === source.id ? source : other, active_turn_context: null,
        selection_scope: { ...base.selection_scope, writer_profile: profile, scope_changed: changed,
          previous_attachment_scope: changed ? 'thread:' + previous : '', previous_scope_generation: profile.scope_generation - Number(changed),
          attachment_scope_disposition: changed ? 'isolated' : 'unchanged' } };
    } else { await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: path } }) }); return; }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  try {
    await page.goto(url);
    // An absent pre-mount overlay also matches "hidden". Start editing only
    // after the selected transcript exists and the input receives real clicks.
    await page.locator('[data-turn-id="turn-1:item:item-20:0"]').waitFor({ state: 'attached' });
    await page.locator('.gload').waitFor({ state: 'hidden' });
    const origin = await page.evaluate(() => performance.timeOrigin);
    const editor = page.locator('#composer-input:visible');
    await editor.click();
    await editor.fill('Keep my unsent draft');
    const toolGroup = page.locator('.tool-group-head');
    if (roundtrip) {
      expect(await toolGroup.getAttribute('aria-expanded')).toBe('false');
      await toolGroup.click();
    }
    const readingMode = !scrollDuringReload;
    if (readingMode) await page.locator('[data-reading-mode-toggle][aria-label="Enter reading mode"]:visible').click();
    const exit = page.getByRole('button', { name: 'Exit reading mode', exact: true });
    if (readingMode) await exit.waitFor();
    const pane = page.locator('.panes');
    let anchor = page.locator('[data-turn-id="turn-1:item:item-20:0"]');
    await anchor.waitFor({ state: 'attached' });
    await pane.hover();
    if (scrollDuringReload) {
      await page.mouse.wheel(0, await pane.evaluate(el => el.scrollHeight));
      await expect.poll(() => pane.evaluate(el => el.classList.contains('is-following')
        && el.scrollHeight - el.scrollTop - el.clientHeight < 3)).toBe(true);
    } else {
      const delta = await anchor.evaluate(el => el.getBoundingClientRect().top - document.querySelector('.panes')!.getBoundingClientRect().top - 8);
      await page.mouse.wheel(0, delta);
      await expect.poll(async () => Math.abs(await anchor.evaluate(el => el.getBoundingClientRect().top - document.querySelector('.panes')!.getBoundingClientRect().top - 8))).toBeLessThan(2);
    }
    let before = (await anchor.boundingBox())!.y;
    let element = await anchor.elementHandle();
    if (roundtrip) {
      const select = async (name: string) => {
        await page.locator('.reading-session-switch:visible,.tb-mid:visible').click();
        await page.locator('.srow').filter({ hasText: name }).click();
        await page.waitForFunction(title => document.querySelector('.reading-session-title,.tb-mid .se')?.textContent?.trim() === title, name);
        await page.locator('.gload').waitFor({ state: 'hidden' });
      };
      await select('Other thread');
      expect(await toolGroup.getAttribute('aria-expanded')).toBe('false');
      if (await exit.isVisible()) await exit.click();
      await page.locator('#composer-input:visible').fill('Second draft');
      bodyReads.length = 0;
      await select('Reading recovery');
      await expect.poll(async () => Math.abs(((await anchor.boundingBox())?.y ?? -9999) - before)).toBeLessThan(3);
      expect(await exit.isVisible()).toBe(true);
      expect(await toolGroup.getAttribute('aria-expanded')).toBe('true');
      expect(bodyReads.filter(r => r.thread === 'thread-1').map(r => r.item)).toEqual(['item-20']);
      await exit.click();
      expect(await editor.inputValue()).toBe('Keep my unsent draft');
      await select('Other thread');
      expect(await exit.isVisible()).toBe(false);
      expect(await editor.inputValue()).toBe('Second draft');
      expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
      expect(posts.filter(path => !path.endsWith('/open') && path !== '/api/client/register')).toEqual([]);
      return;
    }
    if (mode === 'cold-document') {
      await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('focus-web.thread-reading.v1') ?? '[]').find((row: { thread: string }) => row.thread === 'thread-1')?.bookmark)).toBeTruthy();
      await page.reload();
      await expect.poll(() => registrations, { timeout: 15_000 }).toBe(2);
      await expect.poll(() => targets.length, { timeout: 10_000 }).toBeGreaterThan(0);
      await expect.poll(async () => Math.abs(((await anchor.boundingBox())?.y ?? -9999) - before), { timeout: 10_000 }).toBeLessThan(3);
      expect(await exit.isVisible()).toBe(true);
      await exit.click();
      expect(await page.locator('textarea:visible').first().inputValue()).toBe('Keep my unsent draft');
      expect(posts.filter(path => path !== '/api/client/register')).toEqual([]);
      expect(errors).toEqual([]);
      return;
    }
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
      document.dispatchEvent(new Event('visibilitychange'));
    });
    if (mode !== 'healthy') { broken = true; revision++; }
    if (mode === 'closed' || scrollDuringReload) sockets[0]!.close({ code: 1011, reason: 'test network loss' });
    await page.evaluate(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
      document.dispatchEvent(new Event('visibilitychange'));
      window.dispatchEvent(new Event('online'));
      window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
    });
    if (mode === 'healthy') {
      await page.waitForTimeout(600);
      expect(sockets).toHaveLength(1);
    } else {
      await expect.poll(() => sockets.length, { timeout: 15_000 }).toBe(2);
      if (scrollDuringReload) {
        await expect.poll(() => heldRecovery, { timeout: 10_000 }).toBe(true);
        await page.mouse.wheel(0, -60);
        await expect.poll(() => pane.evaluate(el => el.classList.contains('is-following'))).toBe(false);
        const id = await pane.evaluate(el => {
          const top = el.getBoundingClientRect().top;
          return [...el.querySelectorAll<HTMLElement>('.transcript-row')]
            .find(row => row.getBoundingClientRect().bottom > top)?.dataset.turnId;
        });
        expect(id).toBeTruthy();
        anchor = page.locator(`[data-turn-id="${id}"]`);
        before = (await anchor.boundingBox())!.y;
        element = await anchor.elementHandle();
        releaseRecovery();
      }
      await expect.poll(() => targets.length, { timeout: 10_000 }).toBeGreaterThan(0);
      // A dispatched HTTP request is not proof its response was installed.
      // Wait for revalidated content before checking recovery invariants.
      await expect.poll(() => anchor.innerText(), { timeout: 10_000 }).toContain('Recovered message');
      await expect.poll(async () => Math.abs((await anchor.boundingBox())!.y - before), { timeout: 10_000 }).toBeLessThan(2);
    }
    expect(await exit.isVisible()).toBe(!scrollDuringReload);
    expect(await element!.evaluate(el => el.isConnected)).toBe(true);
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
    expect(registrations).toBe(1);
    expect(posts.filter(path => path.endsWith('/prompt') || path.endsWith('/revert'))).toEqual([]);
    if (!scrollDuringReload) await exit.click();
    const input = page.locator('textarea:visible').first();
    await expect.poll(async () => await input.isEnabled() ? input.inputValue() : null,
      { timeout: 3000 }).toBe('Keep my unsent draft');
    expect(errors).toEqual([]);
  } catch (error) {
    await page.screenshot({ path: join(tmpdir(), `focus-reconnect-${mode}-${width}.png`), fullPage: true });
    throw new Error(`${error instanceof Error ? error.stack : String(error)}\nErrors: ${JSON.stringify(errors)}\nTargets: ${targets}\nPage: ${(await page.locator('body').innerText()).slice(0, 1500)}`);
  } finally { releaseRecovery(); await page.close(); }
}, 45_000);
