import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type WebSocketRoute } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { meta, registration } from './focus-api-test-support';
import { snapshot, thread } from './focus_client/support';
import type { PromptFirstOutput } from '../src/focus/promptTimingTypes';
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
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { value: {
      writeText: async (text: string) => { Reflect.set(window, 'timingDiagnostic', text); },
    } });
  });
  const errors: string[] = [], requests: string[] = [], posts: string[] = [];
  const time = 1_790_000_000_123;
  const source = { ...thread(), source: 'cli', ephemeral: false, session_id: '', parent_thread_id: '', can_accept_direct_input: true, thread_source: '', agent_nickname: '', agent_role: '', subagent_kind: '' };
  const record = { submission_id: id, thread_id: 'thread-1', turn_id: 'turn', item_id: 'item',
    submitted_at_ms: time, received_at_ms: time + 100, result: 'succeeded', reason_code: 'upstream_acknowledged', epoch: 'epoch-1',
    first_output: { status: 'pending', reason_code: '' } as PromptFirstOutput,
    updated_at_ms: time + 400, stages: [{ name: 'service_received', at_ms: time + 100, elapsed_ms: 0 },
      { name: 'settled', at_ms: time + 400, elapsed_ms: 300 }], browser: { result: 'succeeded', elapsed_ms: 500 } };
  let unavailable = false;
  let events!: WebSocketRoute;
  page.on('pageerror', error => errors.push(error.message));
  await page.routeWebSocket('**/api/events?*', socket => {
    events = socket;
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
    const submitted = page.getByRole('button', { name: /^Browser submitted/ }).first();
    await submitted.waitFor();
    expect(requests.filter(path => path.includes('prompt-timings'))).toEqual([]);
    await submitted.click();
    await page.getByText('Focus received first output: Not yet observed', { exact: true }).waitFor();
    expect(requests.filter(path => path === `/api/prompt-timings/${id}`)).toHaveLength(1);
    const detail = page.locator('.prompt-time-detail').first();
    expect(await detail.innerText()).not.toMatch(/upstream_acknowledged|Codex accepted input|\d+ ms|Collection not integrated/);
    const lines = (await detail.innerText()).split('\n');
    expect(lines.slice(0, 5).map(line => line.split(': ')[0])).toEqual([
      'Browser submitted', 'Focus received submission', 'Codex recorded input', 'Focus received first output', 'Submission ID',
    ]);
    expect(await detail.evaluate(el => el.clientWidth)).toBeGreaterThan(width === 390 ? 300 : 400);
    expect((await detail.boundingBox())!.y).toBeGreaterThan((await submitted.boundingBox())!.y);
    expect(await page.locator('body').evaluate(el => el.scrollWidth <= window.innerWidth)).toBe(true);
    if (width === 390) await page.screenshot({ path: join(tmpdir(), 'focus-prompt-timing-mobile.png'), fullPage: true });
    await detail.getByRole('button', { name: 'Copy diagnostic details', exact: true }).click();
    await detail.getByRole('button', { name: 'Diagnostic details copied', exact: true }).waitFor();
    expect(JSON.parse(await page.evaluate(() => Reflect.get(window, 'timingDiagnostic')))).toEqual({
      server: record, browser: null, codex_recorded_at_ms: time + 250,
      durations_ms: { browser_submit: 500, focus_submit: 300 }, model_upstream: { collection: 'not_integrated' },
    });

    await page.locator('summary').filter({ hasText: 'Submission history' }).click();
    await page.getByText('Delivery outcome unknown', { exact: true }).waitFor();
    expect(requests.filter(path => path.endsWith('/thread-1/prompt-timings'))).toHaveLength(1);
    record.first_output = { status: 'observed', at_ms: time + 1800, elapsed_ms: 1700, turn_id: 'turn', item_id: 'output', kind: 'thinking' };
    const listRefreshed = page.waitForResponse(response => new URL(response.url()).pathname === '/api/threads/thread-1/prompt-timings');
    events.send(JSON.stringify({ type: 'prompt_timing_changed', runtime_epoch: 'epoch-1', revision: 2,
      thread_id: 'thread-1', detail: { submission_id: id } }));
    await listRefreshed;
    expect(requests.filter(path => path === `/api/prompt-timings/${id}`)).toHaveLength(1);
    await detail.getByText('Focus received first output: Not yet observed', { exact: true }).waitFor();
    await detail.getByRole('button', { name: 'Refresh', exact: true }).click();
    await detail.getByText(/Focus received first output:.*2026/).waitFor();
    expect(requests.filter(path => path === `/api/prompt-timings/${id}`)).toHaveLength(2);
    await detail.getByRole('button', { name: 'Copy diagnostic details', exact: true }).click();
    await detail.getByRole('button', { name: 'Diagnostic details copied', exact: true }).waitFor();
    expect(JSON.parse(await page.evaluate(() => Reflect.get(window, 'timingDiagnostic')))).toEqual({
      server: record, browser: null, codex_recorded_at_ms: time + 250,
      durations_ms: { browser_submit: 500, focus_submit: 300, focus_first_output: 1700 },
      model_upstream: { collection: 'not_integrated' },
    });

    unavailable = true;
    await detail.getByRole('button', { name: 'Refresh', exact: true }).click();
    await detail.getByText('Refresh failed; showing previous record', { exact: true }).waitFor();
    await detail.getByText(/Focus received first output:.*2026/).waitFor();
    await submitted.click();
    const native = page.getByRole('button', { name: /^Codex recorded/ });
    await native.click();
    expect(requests.filter(path => path === `/api/prompt-timings/${id}`)).toHaveLength(3);
    expect(requests.filter(path => path.endsWith('/thread-1/prompt-timings'))).toHaveLength(2);
    expect(posts.filter(path => path.endsWith('/prompt') || path === '/api/threads/start')).toEqual([]);
    expect(errors).toEqual([]);
  } catch (error) {
    throw new Error(`${String(error)}\nBrowser errors: ${JSON.stringify(errors)}\nRequests: ${JSON.stringify(requests)}\nPage: ${(await page.locator('body').innerText()).slice(0, 4000)}`);
  } finally { await page.close(); }
}, 45_000);
