import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';
import { snapshot, thread } from './focus_client/support';
let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-history-browser-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] }, server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/?thread=thread-1`;
  browser = await chromium.launch({ headless: true, ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => {
  await browser?.close(); await server?.close();
  rmSync(cacheDir, { recursive: true, force: true });
});
it.each(['direct', 'navigate', 'lost'])('preserves exact IDs, draft and single-effect semantics: %s', async mode => {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [], posts: Array<{ path: string; body: Record<string, unknown> }> = [];
  const original = 'Original full prompt\n' + 'unclipped input '.repeat(1000);
  const rows = [{ id: 'display-is-not-an-id', rawTurnId: 'real-turn-early', itemId: 'real-item', role: 'user', no: 99, text: 'TRUNCATED PREVIEW' }];
  const source = { ...thread(), source: 'cli', ephemeral: false, session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  const branch = { ...source, id: 'branch', name: 'Branch', title: 'Branch', preview: '' };
  const profile = { selected_thread_id: 'thread-1', working_dir: '/work', scope_generation: 1 };
  const other = { ...source, id: 'other', name: 'Other', title: 'Other' };
  let finishFork = () => {};
  const forkGate = new Promise<void>(resolve => { finishFork = resolve; });
  let created = false, revision = 1;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/api/events?*', socket => {
    socket.onMessage(message => { if (message === 'ping') socket.send('pong'); });
    setTimeout(() => socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision: 0 })), 20);
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname, query = new URL(request.url()).searchParams;
    let body: Record<string, unknown> = {};
    if (request.method() === 'POST') { body = request.postDataJSON() ?? {}; posts.push({ path, body }); }
    let payload: unknown;
    if (path === '/api/client/register') payload = registration();
    else if (path === '/api/meta') payload = { ...meta, revision, runtime_identity: { ...meta.runtime_identity, codex_app_server: { user_agent: 'focus/0.164.0' } }, writer_profile: { ...profile } };
    else if (path === '/api/settings/next-turn') payload = { runtime_epoch: 'epoch-1', revision, next_turn_settings: meta.next_turn_settings };
    else if (path === '/api/operator-status') payload = { status: 'ok', observed_at: 1, poll_after_seconds: 60, warnings: [], runtime_loop: {} };
    else if (path === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision, scope: query.get('scope') ?? 'global', archived: false, limit: 100, truncated: false, threads: created ? [source, other, branch] : [source, other] };
    else if (path.endsWith('/fork')) {
      created = true; revision += 1;
      if (mode === 'lost') { await route.abort('connectionreset'); return; }
      if (mode === 'navigate') await forkGate;
      payload = { accepted: true, source_thread_id: 'thread-1', thread_id: 'branch', name_warning: '', list_visibility: 'not_found', visibility_diagnostic: '', edit_prompt: { turn_id: 'real-turn-early', item_id: 'real-item', text: original } };
    } else if (path.endsWith('/transcript')) {
      const id = path.split('/')[3]!;
      payload = { runtime_epoch: 'epoch-1', revision, thread_id: id, turn_id: null, view: query.get('view') ?? 'transcript', target_pending: false, turns: id === 'thread-1' ? rows : [], older_cursor: null, newer_cursor: null, full_text: null };
    } else if (path.endsWith('/prompt')) {
      payload = { thread_id: 'branch', mutation_id: body.mutation_id, client_user_message_id: `focus-web:${body.mutation_id}`, status: 'succeeded', mode: 'start', turn_id: 'edited-turn', reason_code: '', observed_thread_status: 'idle', diagnostic_stage: 'upstream', recorded_at: 1_790_000_000 };
    } else if (/^\/api\/threads\/[^/]+(?:\/open)?$/.test(path)) {
      const id = path.split('/')[3]!, old = { ...profile }, changed = old.selected_thread_id !== id;
      if (changed) { profile.selected_thread_id = id; profile.scope_generation += 1; }
      const base = snapshot('none', id, profile.scope_generation);
      payload = { ...base, revision, active_turn_context: null, thread: id === 'branch' ? branch : id === 'other' ? other : source, selection_scope: { ...base.selection_scope, writer_profile: { ...profile }, scope_changed: changed, previous_attachment_scope: changed ? `thread:${old.selected_thread_id}` : '', previous_scope_generation: old.scope_generation, attachment_scope_disposition: changed ? 'isolated' : 'unchanged' } };
    } else { await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: path } }) }); return; }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  try {
    await page.goto(url);
    const edit = page.getByRole('button', { name: 'Edit and fork', exact: true });
    await edit.waitFor();
    expect(await edit.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if (mode === 'lost') await page.locator('textarea:visible').first().fill('Draft to retain');
    await edit.click();
    if (mode === 'lost') {
      await page.getByText(/Fork result could not be confirmed/).first().waitFor();
      expect(await page.locator('textarea:visible').first().inputValue()).toBe('Draft to retain');
      expect(posts.filter(p => p.path.endsWith('/fork'))).toHaveLength(1);
      expect(posts.filter(p => p.path.endsWith('/prompt'))).toHaveLength(0);
      return;
    }
    if (mode === 'navigate') {
      await page.getByText('Other', { exact: true }).first().click();
      await page.waitForURL('**thread=other*');
      await page.locator('textarea:visible').first().fill('Other thread draft');
      finishFork();
      await page.getByText('Branch', { exact: true }).first().waitFor();
      expect(await page.locator('textarea:visible').first().inputValue()).toBe('Other thread draft');
      await page.getByText('Branch', { exact: true }).first().click();
    }
    await page.waitForFunction(value => [...document.querySelectorAll('textarea')].some(el => el.value === value), original);
    expect(posts.filter(p => p.path.endsWith('/fork'))).toEqual([{ path: '/api/threads/thread-1/fork', body: { turn_id: 'real-turn-early', item_id: 'real-item' } }]);
    expect(posts.filter(p => p.path.endsWith('/prompt'))).toEqual([]);
    const composer = page.locator('textarea:visible').first();
    expect(await composer.inputValue()).toBe(original);
    expect(await page.getByTestId('fork-note').isVisible()).toBe(true);
    await composer.fill('Edited prompt'); await composer.press('Enter');
    await page.waitForFunction(() => ![...document.querySelectorAll('textarea')].some(el => el.value === 'Edited prompt'));
    expect(posts.filter(p => p.path.endsWith('/prompt')).map(p => [p.path, p.body.text])).toEqual([['/api/threads/branch/prompt', 'Edited prompt']]);
    expect(errors).toEqual([]);
  } catch (error) {
    throw new Error(`${String(error)}\nBrowser errors: ${JSON.stringify(errors)}\nPage: ${(await page.locator('body').innerText()).slice(0, 3000)}`);
  } finally { finishFork(); await page.close(); }
}, 45_000);
