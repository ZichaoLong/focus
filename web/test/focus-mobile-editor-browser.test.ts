import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type Page, type WebSocketRoute } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';
import { snapshot, thread } from './focus_client/support';

let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-mobile-editor-'));
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
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

async function openPage(width = 390, empty = false) {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width, height: 844 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [], submitted: string[] = [];
  let succeed = false, revision = 1, approval = false, socket: WebSocketRoute;
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    let height: number | null = null, top = 0;
    const viewport = window.visualViewport!;
    Object.defineProperty(viewport, 'height', { get: () => height ?? window.innerHeight });
    Object.defineProperty(viewport, 'offsetTop', { get: () => top });
    Object.assign(window, { editorViewport: (nextHeight: number, nextTop = 0) => {
      height = nextHeight; top = nextTop; viewport.dispatchEvent(new Event('resize'));
    } });
  });
  const profile = { selected_thread_id: empty ? '' : 'thread-1', working_dir: '/work', scope_generation: 1 };
  const source = { ...thread(), name: 'Long draft', title: 'Long draft', source: 'cli', ephemeral: false,
    session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  const rows = Array.from({ length: 40 }, (_, i) => ({ id: `turn-1:item:item-${i}:0`, rawTurnId: 'turn-1', itemId: `item-${i}`,
    role: 'assistant', no: 0, text: `Message ${i}\n\n${'A paragraph for checking the reading position. '.repeat(12)}` }));
  await page.routeWebSocket('**/api/events?*', route => {
    socket = route;
    socket.onMessage(message => { if (message === 'ping') socket.send('pong'); });
    setTimeout(() => socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision })), 20);
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), parsed = new URL(request.url()), path = parsed.pathname, query = parsed.searchParams;
    let payload: unknown;
    if (path === '/api/client/register') payload = registration();
    else if (path === '/api/meta') payload = { ...meta, revision, writer_profile: profile };
    else if (path === '/api/settings/next-turn') payload = { runtime_epoch: 'epoch-1', revision, next_turn_settings: meta.next_turn_settings };
    else if (path === '/api/operator-status') payload = { status: 'ok', observed_at: 1, poll_after_seconds: 60, warnings: [], runtime_loop: {} };
    else if (path === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision, scope: query.get('scope') ?? 'global', archived: false, limit: 100, truncated: false, threads: empty ? [] : [source] };
    else if (path.endsWith('/transcript')) payload = { runtime_epoch: 'epoch-1', revision, thread_id: 'thread-1', turn_id: query.get('turn_id'),
      view: query.get('view') ?? 'transcript', target_pending: false, turns: rows, older_cursor: null, newer_cursor: null, full_text: null };
    else if (path.endsWith('/prompt')) {
      const body = request.postDataJSON(); submitted.push(body.text);
      payload = { thread_id: 'thread-1', mutation_id: body.mutation_id, client_user_message_id: `focus-web:${body.mutation_id}`,
        status: succeed ? 'succeeded' : 'known_no_effect', mode: 'start', turn_id: succeed ? 'turn-new' : '',
        reason_code: succeed ? '' : 'test_rejection', observed_thread_status: null, diagnostic_stage: 'upstream', recorded_at: 1_790_550_000 };
    } else if (/^\/api\/threads\/thread-1(?:\/open)?$/.test(path)) {
      const base = snapshot('none', 'thread-1', 1);
      payload = { ...base, revision, thread: source, active_turn_context: null,
        pending_requests: approval ? [{ id: 'approval', connection_generation: 1, response_capability: 'cap-a', kind: 'approval',
          method: 'item/commandExecution/requestApproval', thread_id: 'thread-1', owner_thread_id: 'thread-1', turn_id: 'turn-1',
          status: 'pending', title: 'Command approval', params: { command: 'git status' }, agent_name: 'Codex',
          actions: [{ id: 'approve_once', label: 'Allow once', style: 'primary' }] }] : [],
        selection_scope: { ...base.selection_scope, writer_profile: profile, scope_changed: false,
          previous_attachment_scope: '', previous_scope_generation: 1, attachment_scope_disposition: 'unchanged' } };
    } else { await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: path } }) }); return; }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  await page.goto(url + (empty ? '' : '?thread=thread-1'));
  await page.locator('.gload').waitFor({ state: 'hidden' });
  await page.locator('textarea:visible').waitFor();
  await expect.poll(async () => page.locator('textarea:visible').isEnabled()).toBe(true);
  return { page, errors, submitted, succeed: () => { succeed = true; }, approval: (pending: boolean) => {
    approval = pending; revision++; socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision }));
  } };
}

async function viewport(page: Page, height: number, top = 0) {
  await page.evaluate(({ height, top }) => {
    (window as unknown as { editorViewport(height: number, top: number): void }).editorViewport(height, top);
  }, { height, top });
  await expect.poll(async () => (await page.locator('.focus-shell').boundingBox())!.height).toBe(height);
}
const draft = '中文输入与选区\n' + 'A longer draft to edit.\n'.repeat(35);

it.each([320, 390])('uses keyboard and full-page space without replacing input or moving history at %s px', async width => {
  const { page, errors, submitted } = await openPage(width);
  try {
    const input = page.locator('textarea:visible'), pane = page.locator('.panes');
    await input.fill(draft);
    const element = await input.elementHandle();
    const anchor = page.locator('[data-turn-id="turn-1:item:item-20:0"]');
    await anchor.waitFor({ state: 'attached' });
    await pane.hover();
    await page.mouse.wheel(0, await anchor.evaluate(el => el.getBoundingClientRect().top - document.querySelector('.panes')!.getBoundingClientRect().top - 8));
    await expect.poll(async () => Math.abs(await anchor.evaluate(el => el.getBoundingClientRect().top - document.querySelector('.panes')!.getBoundingClientRect().top - 8))).toBeLessThan(2);
    const before = await pane.evaluate(el => el.scrollTop);
    await input.evaluate(el => { el.focus({ preventScroll: true }); el.setSelectionRange(2, 7, 'backward'); });
    await page.locator('.expand-btn:visible').click();
    await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(650);
    expect(await page.locator('.timing-history').isVisible()).toBe(false);
    expect(await pane.isVisible()).toBe(false);
    expect(await page.locator('.expanded-editor-title').innerText()).toBe('Long draft');
    expect(await element!.evaluate(el => el === document.querySelector('textarea:focus'))).toBe(true);
    expect(await input.evaluate(el => [el.selectionStart, el.selectionEnd, el.selectionDirection])).toEqual([2, 7, 'backward']);
    if (width === 390) await page.screenshot({ path: '/tmp/focus-mobile-editor-full.png' });
    await viewport(page, 420, 30);
    await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(260);
    expect((await input.boundingBox())!.height).toBeLessThan(350);
    const send = await page.locator('.send').boundingBox();
    expect(send!.y + send!.height).toBeLessThanOrEqual(450);
    if (width === 390) await page.screenshot({ path: '/tmp/focus-mobile-editor-keyboard.png' });
    await input.dispatchEvent('compositionstart', { data: '中' });
    await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true, bubbles: true, cancelable: true });
    expect(submitted).toEqual([]);
    await input.dispatchEvent('compositionend', { data: '中文' });
    await viewport(page, 844);
    await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(650);
    await page.locator('.expanded-editor-collapse').click();
    await expect.poll(async () => Math.abs(await pane.evaluate(el => el.scrollTop) - before)).toBeLessThan(2);
    expect(await input.inputValue()).toBe(draft);
    expect(await element!.evaluate(el => el.isConnected)).toBe(true);
    expect(await page.locator('.timing-history').isVisible()).toBe(true);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 45_000);

it('keeps a failed submission expanded and collapses only after success', async () => {
  const h = await openPage();
  try {
    const input = h.page.locator('textarea:visible');
    await input.fill('Retain until sent');
    await h.page.locator('.expand-btn:visible').click();
    await h.page.locator('.send').click();
    await expect.poll(() => h.submitted.length).toBe(1);
    await expect.poll(async () => h.page.locator('.send').isEnabled()).toBe(true);
    expect(await h.page.locator('.expanded-editor-collapse').isVisible()).toBe(true);
    expect(await h.page.locator('.primary-notices').isVisible()).toBe(true);
    expect(await input.inputValue()).toBe('Retain until sent');
    h.succeed();
    await h.page.locator('.send').click();
    await expect.poll(async () => input.inputValue()).toBe('');
    expect(h.submitted).toEqual(['Retain until sent', 'Retain until sent']);
    expect(await h.page.locator('.expanded-editor-collapse').count()).toBe(0);
    expect(h.errors).toEqual([]);
  } finally { await h.page.close(); }
}, 45_000);

it('keeps the wide expanded editor and visible conversation layout', async () => {
  const { page, errors } = await openPage(1280);
  try {
    const input = page.locator('textarea:visible');
    await input.fill(draft);
    await page.locator('.expand-btn:visible').click();
    await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(570);
    expect((await input.boundingBox())!.height).toBeLessThan(610);
    expect(await page.locator('.expanded-editor-collapse').count()).toBe(0);
    expect(await page.locator('.panes').isVisible()).toBe(true);
    expect(await input.inputValue()).toBe(draft);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 45_000);

it.each([1024, 1280, 1550])('keeps the sidebar stationary during native editor paging at %s px', async width => {
  const { page, errors, submitted } = await openPage(width);
  try {
    const input = page.locator('textarea:visible'), app = page.locator('.focus-app');
    const sidebar = page.locator('.side'), rail = page.locator('.conversation-toc');
    const railElement = await rail.elementHandle();
    await expect.poll(() => rail.isVisible()).toBe(width === 1550);
    for (const expanded of [false, true]) {
      const text = expanded ? draft : 'A short draft.\n第二行文字。';
      await input.fill(text);
      if (expanded) await page.locator('.expand-btn:visible').click();
      await input.evaluate(el => { el.focus({ preventScroll: true }); el.setSelectionRange(el.value.length, el.value.length); });
      const before = (await sidebar.boundingBox())!;
      await input.press('PageUp');
      await expect.poll(() => input.evaluate(el => el.selectionStart)).toBeLessThan(text.length);
      const pageUpCaret = await input.evaluate(el => el.selectionStart);
      // The browser owns caret scrolling; wait for its layout before checking
      // that the application frame and sidebar stayed in the viewport.
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect(await app.evaluate(el => el.scrollLeft)).toBe(0);
      expect((await sidebar.boundingBox())!.x).toBeCloseTo(before.x, 1);
      expect((await sidebar.boundingBox())!.width).toBeCloseTo(before.width, 1);
      expect(await input.inputValue()).toBe(text);
      if (width !== 1550) {
        expect(await app.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
      }
      await input.press('PageDown');
      await expect.poll(() => input.evaluate(el => el.selectionStart)).toBeGreaterThan(pageUpCaret);
      expect(await app.evaluate(el => el.scrollLeft)).toBe(0);
    }
    // Hiding must retain the measurable rail so a wider window can reveal it.
    await page.setViewportSize({ width: 1920, height: 844 });
    await expect.poll(() => rail.isVisible()).toBe(true);
    expect(await railElement!.evaluate(el => el.isConnected)).toBe(true);
    await rail.hover();
    expect((await rail.boundingBox())!.width).toBeGreaterThan(0);
    await page.setViewportSize({ width: 1024, height: 844 });
    await expect.poll(() => rail.isVisible()).toBe(false);
    expect(await app.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
    expect((await sidebar.boundingBox())!.x).toBe(0);
    expect(submitted).toEqual([]);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 45_000);

it('yields to an approval and resumes the same expanded draft afterwards', async () => {
  const h = await openPage();
  try {
    const input = h.page.locator('textarea:visible');
    await input.fill('Draft while working');
    const element = await input.elementHandle();
    await h.page.locator('.expand-btn:visible').click();
    h.approval(true);
    await h.page.getByRole('button', { name: /^Allow once/ }).waitFor();
    expect(await h.page.locator('.expanded-editor-collapse').isVisible()).toBe(false);
    expect(await h.page.locator('.timing-history').isVisible()).toBe(true);
    h.approval(false);
    await h.page.locator('.expanded-editor-collapse').waitFor();
    expect(await input.inputValue()).toBe('Draft while working');
    expect(await element!.evaluate(el => el.isConnected)).toBe(true);
    expect(h.submitted).toEqual([]);
    expect(h.errors).toEqual([]);
  } catch (error) {
    await h.page.screenshot({ path: '/tmp/focus-mobile-editor-approval.png' });
    throw new Error(`${String(error)}\n${JSON.stringify(h.errors)}\n${(await h.page.locator('body').innerText()).slice(0, 2000)}`);
  } finally { await h.page.close(); }
}, 45_000);

it('expands a new-conversation draft and safely returns to compact after a width change', async () => {
  const { page, errors } = await openPage(390, true);
  try {
    const input = page.locator('textarea:visible');
    await input.fill('A new draft');
    const element = await input.elementHandle();
    await page.locator('.expand-btn:visible').click();
    await expect.poll(async () => (await input.boundingBox())!.height).toBeGreaterThan(650);
    expect(await page.locator('.expanded-editor-title').innerText()).toBe('New conversation');
    expect(await input.inputValue(), 'after expansion').toBe('A new draft');
    await viewport(page, 420);
    await expect.poll(async () => (await input.boundingBox())!.height).toBeLessThan(350);
    expect(await input.inputValue(), 'after keyboard opens').toBe('A new draft');
    await page.setViewportSize({ width: 1280, height: 844 });
    await expect.poll(async () => page.locator('.expanded-editor-collapse').count()).toBe(0);
    expect(await element!.evaluate(el => el.isConnected)).toBe(true);
    expect(await input.inputValue()).toBe('A new draft');
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 45_000);
