import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';
import { snapshot, thread } from './focus_client/support';
let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-timing-browser-'));
const id = '11111111-1111-4111-8111-111111111111';
const missingId = '22222222-2222-4222-8222-222222222222';
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] }, server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/?thread=thread-1`;
  browser = await chromium.launch({ headless: true, ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

it.each([1280, 390])('defers diagnostic reads, displays cross-device and uncertain evidence, fits width %s', async width => {
  const page = await browser.newPage({ locale: 'en-US', viewport: { width, height: 900 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [], requests: string[] = [], posts: string[] = [];
  const time = 1_790_000_000_123;
  const source = { ...thread(), source: 'cli', ephemeral: false, session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  const record = { submission_id: id, thread_id: 'thread-1', turn_id: 'turn', item_id: 'item',
    submitted_at_ms: time, received_at_ms: time + 100, result: 'succeeded', reason_code: '', epoch: 'epoch-1',
    updated_at_ms: time + 400, stages: [{ name: 'service_received', at_ms: time + 100, elapsed_ms: 0 },
      { name: 'settled', at_ms: time + 400, elapsed_ms: 300 }], browser: { elapsed_ms: 500 } };
  let unavailable = false;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/api/events?*', socket => {
    socket.onMessage(message => { if (message === 'ping') socket.send('pong'); });
    setTimeout(() => socket.send(JSON.stringify({ type: 'hello', runtime_epoch: 'epoch-1', revision: 0 })), 20);
  });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    requests.push(path); if (request.method() !== 'GET') posts.push(path);
    let payload: unknown;
    if (path === '/api/client/register') payload = registration();
    else if (path === '/api/meta') payload = { ...meta, revision: 1,
      writer_profile: { selected_thread_id: 'thread-1', working_dir: '/work', scope_generation: 1 } };
    else if (path === '/api/settings/next-turn') payload = { runtime_epoch: 'epoch-1', revision: 1, next_turn_settings: meta.next_turn_settings };
    else if (path === '/api/operator-status') payload = { status: 'ok', observed_at: 1, poll_after_seconds: 60, warnings: [], runtime_loop: {} };
    else if (path === '/api/threads') payload = { runtime_epoch: 'epoch-1', revision: 1, scope: new URL(request.url()).searchParams.get('scope') ?? 'global', archived: false, limit: 100, truncated: false, threads: [source] };
    else if (path.endsWith('/transcript')) payload = { runtime_epoch: 'epoch-1', revision: 1, thread_id: 'thread-1', turn_id: null, view: 'transcript', target_pending: false,
      turns: [{ id: 'row', rawTurnId: 'turn', itemId: 'item', role: 'user', no: 1, text: 'Cross-device prompt',
        promptTiming: { submissionId: id, submittedAtMs: time }, codexRecordedAtMs: time + 250 },
      { id: 'native', rawTurnId: 'turn', itemId: 'native-item', role: 'user', no: 2, text: 'Native prompt', codexRecordedAtMs: time + 10_000 }],
      older_cursor: null, newer_cursor: null, full_text: null };
    else if (path === `/api/prompt-timings/${id}`) {
      if (unavailable) { await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: { code: 'prompt_timing_unavailable', message: 'unavailable' } }) }); return; }
      payload = { record };
    } else if (path === `/api/prompt-timings/${missingId}`) payload = { record: null };
    else if (path.endsWith('/prompt-timings')) payload = { records: [record, { ...record, submission_id: missingId,
      submitted_at_ms: time + 20_000, item_id: '', turn_id: '', result: 'outcome_unknown', stages: [] }] };
    else if (path === '/api/threads/thread-1' || path === '/api/threads/thread-1/open') payload = { ...snapshot('none', 'thread-1', 1), revision: 1, active_turn_context: null, thread: source };
    else { await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ error: { code: 'unavailable', message: path } }) }); return; }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) });
  });
  try {
    await page.goto(url);
    const submitted = page.getByRole('button', { name: /^Submitted/ }).first();
    await submitted.waitFor();
    expect(requests.filter(path => path.includes('prompt-timings'))).toEqual([]);
    await submitted.click();
    await page.getByText('Server submission evidence: Codex accepted input', { exact: true }).waitFor();
    expect(requests.filter(path => path === `/api/prompt-timings/${id}`)).toHaveLength(1);
    await page.getByText(/Not collected. These timestamps/).waitFor();
    const detail = page.locator('.prompt-time-detail').first();
    expect(await detail.evaluate(el => el.clientWidth)).toBeGreaterThan(width === 390 ? 300 : 400);
    expect((await detail.boundingBox())!.y).toBeGreaterThan((await submitted.boundingBox())!.y);
    expect(await page.locator('body').evaluate(el => el.scrollWidth <= window.innerWidth)).toBe(true);
    if (width === 390) await page.screenshot({ path: join(tmpdir(), 'focus-prompt-timing-mobile.png'), fullPage: true });
    unavailable = true;
    await page.getByRole('button', { name: 'Refresh observations', exact: true }).first().click();
    await page.getByText(/Server observations are unavailable/).waitFor();
    await submitted.click();
    const native = page.getByRole('button', { name: /^Codex recorded/ });
    await native.click();
    expect(requests.filter(path => path.includes('prompt-timings'))).toHaveLength(2);
    await page.locator('summary').filter({ hasText: 'Submission history' }).click();
    await page.getByText('Delivery outcome unknown', { exact: true }).waitFor();
    expect(requests.filter(path => path.endsWith('/thread-1/prompt-timings'))).toHaveLength(1);
    expect(posts.filter(path => path.endsWith('/prompt') || path === '/api/threads/start')).toEqual([]);
    expect(errors).toEqual([]);
  } catch (error) {
    throw new Error(`${String(error)}\nBrowser errors: ${JSON.stringify(errors)}\nRequests: ${JSON.stringify(requests)}\nPage: ${(await page.locator('body').innerText()).slice(0, 4000)}`);
  } finally { await page.close(); }
}, 45_000);
