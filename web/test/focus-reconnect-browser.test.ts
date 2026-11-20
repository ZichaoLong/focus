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
  { mode: 'cold-document', width: 390 },
  { mode: 'scroll-during-reload', width: 390 }, { mode: 'scroll-during-reload', width: 1280 },
])('preserves reading and draft after foreground recovery: $mode at $width', async ({ mode, width }) => {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width, height: 900 } });
  page.setDefaultTimeout(15_000);
  const sockets: WebSocketRoute[] = [], errors: string[] = [], posts: string[] = [], targets: string[] = [];
  let broken = false, revision = 1, registrations = 0;
  const scrollDuringReload = mode === 'scroll-during-reload';
  let releaseRecovery!: () => void, recoveryRequested!: () => void, heldRecovery = false;
  const recoveryGate = new Promise<void>(resolve => { releaseRecovery = resolve; });
  const recoveryReadStarted = new Promise<void>(resolve => { recoveryRequested = resolve; });
  const profile = { selected_thread_id: 'thread-1', working_dir: '/work', scope_generation: 1 };
  const source = { ...thread(), name: 'Reading recovery', title: 'Reading recovery', source: 'cli', ephemeral: false,
    session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  const rows = Array.from({ length: 40 }, (_, i) => ({ id: `turn-1:item:item-${i}:0`, rawTurnId: 'turn-1', itemId: `item-${i}`,
    role: 'assistant', no: 0, text: `Message ${i}\n\n${'A paragraph for checking the reading position. '.repeat(12)}` }));
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
    else if (path === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision, scope: query.get('scope') ?? 'global', archived: false, limit: 100, truncated: false, threads: [source] };
    else if (path.endsWith('/transcript')) {
      const item = query.get('item_id');
      if (item) targets.push(item);
      if (scrollDuringReload && revision > 1 && !item && query.get('view') !== 'prompts' && !heldRecovery) {
        heldRecovery = true;
        recoveryRequested();
        await recoveryGate;
      }
      const start = item ? Math.max(0, rows.findIndex(row => row.itemId === item) - 2)
        : mode === 'cold-document' && registrations > 1 ? 30 : 0;
      payload = { runtime_epoch: 'epoch-1', revision, thread_id: 'thread-1', turn_id: query.get('turn_id'),
        view: query.get('view') ?? 'transcript', target_pending: false, turns: rows.slice(Math.max(0, start)).map(row =>
          revision > 1 ? { ...row, text: row.text.replace('Message', 'Recovered message') } : row),
        older_cursor: null, newer_cursor: null, full_text: null };
    } else if (/^\/api\/threads\/thread-1(?:\/open)?$/.test(path)) {
      const base = snapshot('none', 'thread-1', 1);
      payload = { ...base, revision, thread: source, active_turn_context: null,
        selection_scope: { ...base.selection_scope, writer_profile: profile, scope_changed: false,
          previous_attachment_scope: '', previous_scope_generation: 1, attachment_scope_disposition: 'unchanged' } };
    } else { await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: path } }) }); return; }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  try {
    await page.goto(url);
    // fill() can write beneath the loading overlay before the initial thread
    // selection has settled; real users cannot edit that covered input yet.
    await page.locator('.gload').waitFor({ state: 'hidden' });
    const origin = await page.evaluate(() => performance.timeOrigin);
    await page.locator('textarea:visible').first().fill('Keep my unsent draft');
    const readingMode = !scrollDuringReload && mode !== 'cold-document';
    if (readingMode) await page.locator('[data-reading-mode-toggle][aria-label="Enter reading mode"]:visible').click();
    const exit = page.getByRole('button', { name: 'Exit reading mode', exact: true });
    if (readingMode) await exit.waitFor();
    const pane = page.locator('.panes');
    let anchor = page.locator('[data-turn-id="turn-1:item:item-20:0"]');
    await anchor.waitFor({ state: 'attached' });
    await pane.hover();
    if (!scrollDuringReload) {
      const delta = await anchor.evaluate(el => el.getBoundingClientRect().top - document.querySelector('.panes')!.getBoundingClientRect().top - 8);
      await page.mouse.wheel(0, delta);
      await expect.poll(async () => Math.abs(await anchor.evaluate(el => el.getBoundingClientRect().top - document.querySelector('.panes')!.getBoundingClientRect().top - 8))).toBeLessThan(2);
    }
    let before = (await anchor.boundingBox())!.y;
    let element = await anchor.elementHandle();
    if (mode === 'cold-document') {
      await expect.poll(() => page.evaluate(() => sessionStorage.getItem('focus-web.reading-bookmark'))).toBeTruthy();
      await page.reload();
      await expect.poll(() => registrations, { timeout: 15_000 }).toBe(2);
      await expect.poll(() => targets.length, { timeout: 10_000 }).toBeGreaterThan(0);
      await expect.poll(async () => Math.abs(((await anchor.boundingBox())?.y ?? -9999) - before), { timeout: 10_000 }).toBeLessThan(3);
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
        await recoveryReadStarted;
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
