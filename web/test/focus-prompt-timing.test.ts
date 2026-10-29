import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPromptTimingStore } from '../src/focus/promptTimingStore';
import { decodePromptTiming, type PromptTimingRecord } from '../src/focus/promptTimingTypes';
import { FocusApiError } from '../src/focus/types';
import { createPromptTimingReader } from '../src/focus/promptTimingPresentation';

const id = '11111111-1111-4111-8111-111111111111';
const key = 'focus-web.prompt-timings.v1';
function api() {
  return { clientId: 'doc-1', syncPromptTimings: vi.fn(async (_records: unknown[]) => ({ accepted: true })),
    readPromptTiming: vi.fn(async (_id: string): Promise<{ record: PromptTimingRecord | null }> => ({ record: null })),
    listPromptTimings: vi.fn(async () => ({ records: [] })) };
}
beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v) });
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it('captures before fetch, retains unknown outcome after reload, and syncs metadata only', async () => {
  const remote = api(), store = createPromptTimingStore(remote);
  remote.syncPromptTimings.mockRejectedValue(new Error('offline'));
  const send = vi.fn(async (headers: Record<string, string>) => {
    const saved = JSON.parse(localStorage.getItem(key)!)[0];
    expect(headers).toEqual({ 'X-Focus-Prompt-Id': id, 'X-Focus-Submitted-At': String(saved.submitted_at_ms) });
    store.disconnected();
    throw new Error('response lost');
  });
  await expect(store.submit(id, 'thread-1', send)).rejects.toThrow('response lost');
  await store.sync();
  const local = store.local(id)!;
  expect(local.browser.result).toBe('outcome_unknown');
  expect(local.browser.disconnects).toBe(1);
  expect(store.durable.value).toBe(true);
  const nextRemote = api(); nextRemote.clientId = 'replacement-document';
  const reloaded = createPromptTimingStore(nextRemote);
  await reloaded.sync();
  expect(nextRemote.syncPromptTimings).toHaveBeenCalledExactlyOnceWith([{
    submission_id: id, thread_id: 'thread-1', submitted_at_ms: local.submitted_at_ms, browser: local.browser,
  }]);
  expect(send).toHaveBeenCalledTimes(1);
  expect(nextRemote.readPromptTiming).not.toHaveBeenCalled();
  expect(nextRemote.listPromptTimings).not.toHaveBeenCalled();
});

it('can sync an interrupted incomplete attempt from a replaced document without claiming a result', async () => {
  localStorage.setItem(key, JSON.stringify([{ submission_id: id, thread_id: 'thread-1', submitted_at_ms: 1_790_000_000_000,
    browser: {}, clientId: 'old-doc', version: 1, synced: false }]));
  const remote = api(), store = createPromptTimingStore(remote);
  await store.sync();
  expect(remote.syncPromptTimings.mock.calls[0]![0]).toEqual([{
    submission_id: id, thread_id: 'thread-1', submitted_at_ms: 1_790_000_000_000, browser: {},
  }]);
});

it('does not lose completion metadata when an earlier sync is in flight', async () => {
  const remote = api(), store = createPromptTimingStore(remote);
  let complete!: (result: { status: string }) => void, synced!: (result: { accepted: boolean }) => void;
  const send = new Promise<{ status: string }>(resolve => { complete = resolve; });
  remote.syncPromptTimings.mockImplementationOnce(() => new Promise(resolve => { synced = resolve; }));
  const submission = store.submit(id, 'thread-1', () => send);
  const pendingSync = store.sync();
  complete({ status: 'succeeded' }); await submission;
  synced({ accepted: true }); await pendingSync;
  expect(remote.syncPromptTimings).toHaveBeenCalledTimes(2);
  expect(store.local(id)?.browser.result).toBe('succeeded');
  expect(store.local(id)?.synced).toBe(true);
});

it('keeps a newer cross-tab completion when another tab saves a different submission', async () => {
  const remote = api(), store = createPromptTimingStore(remote);
  await store.submit(id, 'thread-1', async () => ({ status: 'succeeded' })); await store.sync();
  const newer = JSON.parse(localStorage.getItem(key)!)[0];
  newer.version += 1; newer.browser.disconnects = 3;
  localStorage.setItem(key, JSON.stringify([newer]));
  const second = '22222222-2222-4222-8222-222222222222';
  await store.submit(second, 'thread-1', async () => ({ status: 'succeeded' })); await store.sync();
  expect(store.local(id)?.browser.disconnects).toBe(3);
  expect(JSON.parse(localStorage.getItem(key)!)).toHaveLength(2);
});

it('storage failures and metadata-sync failures leave submission semantics unchanged', async () => {
  vi.stubGlobal('localStorage', { getItem() { throw new Error('denied'); }, setItem() { throw new Error('quota'); } });
  const remote = api(); remote.syncPromptTimings.mockRejectedValue(new Error('unavailable'));
  const store = createPromptTimingStore(remote);
  await expect(store.submit(id, 'thread-1', async () => ({ status: 'succeeded' }))).resolves.toEqual({ status: 'succeeded' });
  await store.sync();
  expect(store.local(id)?.browser.result).toBe('succeeded');
  expect(store.durable.value).toBe(false);
  const failure = new FocusApiError('rejected', { code: 'invalid_prompt', status: 400, effectEvidence: 'pre_effect' });
  await expect(store.submit('22222222-2222-4222-8222-222222222222', 'thread-1', async () => { throw failure; })).rejects.toBe(failure);
  expect(store.records.value[1]?.browser.result).toBe('known_no_effect');
});

it('summarizes same-clock durations while preserving full diagnostic evidence', async () => {
  const remote = api(), store = createPromptTimingStore(remote);
  const record: PromptTimingRecord = { submission_id: id, thread_id: 'thread-1', turn_id: 'turn', item_id: 'item',
    submitted_at_ms: 100_000, received_at_ms: 10_000, result: 'succeeded', reason_code: 'upstream_acknowledged', epoch: 'epoch', updated_at_ms: 10_030,
    browser: { result: 'succeeded', elapsed_ms: 500, disconnects: 1, completed_at_ms: 100_500 }, stages: [
      { name: 'service_received', at_ms: 10_000, elapsed_ms: 0 },
      { name: 'app_server_rpc_started', at_ms: 10_001, elapsed_ms: 1 },
      { name: 'app_server_rpc_returned', at_ms: 10_020, elapsed_ms: 20 },
      { name: 'settled', at_ms: 9_000, elapsed_ms: 30 },
    ] };
  expect(decodePromptTiming({ record })).toEqual({ record });
  expect(decodePromptTiming({ record: { ...record, result: 'upstream_received' } })).toBe(null);
  remote.readPromptTiming.mockResolvedValue({ record });
  const view = await createPromptTimingReader(store, key => key).read(id);
  expect(view.lines).toContainEqual({ label: 'focus.timing.serviceElapsed', value: '30 ms' });
  expect(view.lines).toContainEqual({ label: 'focus.timing.upstream', value: 'focus.timing.collectionNotIntegrated' });
  expect(view.lines.map(line => line.label)).toEqual([
    'focus.timing.serviceReceived', 'focus.timing.result', 'focus.timing.roundTrip',
    'focus.timing.serviceElapsed', 'focus.timing.upstream', 'focus.timing.identity',
  ]);
  expect(JSON.parse(view.diagnostic)).toEqual({ server: record, browser: null });
  expect(view.lines.some(line => line.value === '-90000 ms')).toBe(false);

  record.browser.result = 'outcome_unknown';
  const conflicting = await createPromptTimingReader(store, key => key).read(id);
  expect(conflicting.lines).toContainEqual({ label: 'focus.timing.browserResult', value: 'focus.timing.result_outcome_unknown' });

  remote.readPromptTiming.mockResolvedValue({ record: null });
  const missing = await createPromptTimingReader(store, key => key).read(id);
  expect(missing.lines).toContainEqual({ label: 'focus.timing.missing', value: 'focus.timing.notFound' });
  expect(missing.lines.some(line => line.label === 'focus.timing.result')).toBe(false);
});
