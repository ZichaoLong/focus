import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { ref } from 'vue';
import { createDataRetention } from '../src/focus/client-state/data-retention';
import { decodeDataRetention, decodeDataPrune } from '../src/focus/dataRetentionDecoder';
import type { FocusWebApiPort } from '../src/focus/api';
import { useInputHistory } from '../src/composables/useInputHistory';
import { STORAGE_KEYS, draftStorageKey } from '../src/lib/storage';
import { pruneBrowserData, setBrowserRetentionDays, protectDraft, touchDraft, recordHistoryTime, TIMING_STORAGE_KEY } from '../src/lib/dataRetention';
import { createPromptTimingStore } from '../src/focus/promptTimingStore';

const day = 86_400_000, now = 200 * day;
function memoryStorage(): Storage {
  const rows = new Map<string, string>();
  return { get length() { return rows.size; }, key: index => [...rows.keys()][index] ?? null,
    getItem: key => rows.get(key) ?? null, setItem: (key, value) => { rows.set(key, value); },
    removeItem: key => { rows.delete(key); }, clear: () => { rows.clear(); } };
}
beforeEach(() => { vi.stubGlobal('localStorage', memoryStorage()); vi.useFakeTimers(); vi.setSystemTime(now); setBrowserRetentionDays(30); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it('gives undated drafts and history migration grace, preserving preferences', () => {
  localStorage.setItem(draftStorageKey('old'), 'draft');
  localStorage.setItem(STORAGE_KEYS.inputHistory, JSON.stringify({ scope: ['legacy'] }));
  localStorage.setItem(STORAGE_KEYS.colorScheme, 'dark');
  expect(pruneBrowserData()).toBe(0);
  expect(pruneBrowserData(now + 30 * day)).toBe(0);
  expect(pruneBrowserData(now + 30 * day + 1)).toBe(2);
  expect(localStorage.getItem(draftStorageKey('old'))).toBeNull();
  expect(localStorage.getItem(STORAGE_KEYS.colorScheme)).toBe('dark');
});

it('prunes individual history entries without letting a mounted composer resurrect them', () => {
  localStorage.setItem(STORAGE_KEYS.inputHistory, JSON.stringify({ scope: ['old'] }));
  recordHistoryTime('scope', [], ['old'], now - 31 * day);
  const text = ref('');
  const history = useInputHistory({ text, textareaRef: ref(null), autosize: () => {}, sessionId: () => 'scope' });
  history.push('fresh');
  expect(pruneBrowserData()).toBe(1);
  history.recallOlder(); expect(text.value).toBe('fresh');
  history.recallOlder(); expect(text.value).toBe('fresh');
  history.push('later');
  expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.inputHistory)!)).toEqual({ scope: ['fresh', 'later'] });
});

it('preserves a mounted draft while idle drafts expire', () => {
  localStorage.setItem(draftStorageKey('active'), 'editing');
  localStorage.setItem(draftStorageKey('idle'), 'idle');
  const release = protectDraft(draftStorageKey('active'));
  pruneBrowserData();
  expect(pruneBrowserData(now + 31 * day)).toBe(1);
  expect(localStorage.getItem(draftStorageKey('active'))).toBe('editing');
  release();
  expect(pruneBrowserData(now + 62 * day)).toBe(1);
});

it('uses the selected period for browser timing observations and fails visibly on unavailable storage', () => {
  localStorage.setItem(TIMING_STORAGE_KEY, JSON.stringify([{ submitted_at_ms: now - 40 * day, submission_id: 'old' }]));
  setBrowserRetentionDays(90);
  expect(pruneBrowserData()).toBe(0);
  setBrowserRetentionDays(7);
  expect(pruneBrowserData()).toBe(1);
  vi.stubGlobal('localStorage', { getItem: () => { throw new Error('unavailable'); } });
  expect(() => pruneBrowserData()).toThrow();
});

function timingApi() {
  return { clientId: 'doc', syncPromptTimings: vi.fn(async () => ({ accepted: true })),
    readPromptTiming: vi.fn(async () => ({ record: null })), listPromptTimings: vi.fn(async () => ({ records: [] })) };
}

it('filters expired timing lookups and drops stale evidence at the next sync or submission', async () => {
  const id = '11111111-1111-4111-8111-111111111111';
  const saved = JSON.stringify([{ submission_id: id, thread_id: 'thread', submitted_at_ms: now - 8 * day,
    browser: {}, clientId: 'old-doc', synced: false, version: 1 }]);
  localStorage.setItem(TIMING_STORAGE_KEY, saved);
  const remote = timingApi(), store = createPromptTimingStore(remote);
  expect(store.local(id)?.submitted_at_ms).toBe(now - 8 * day);
  setBrowserRetentionDays(7);
  expect(store.local(id)).toBeUndefined();
  expect(localStorage.getItem(TIMING_STORAGE_KEY)).toBe(saved);
  await store.sync();
  expect(remote.syncPromptTimings).not.toHaveBeenCalled();
  expect(store.records.value).toEqual([]);
  const freshId = '22222222-2222-4222-8222-222222222222';
  await store.submit(freshId, 'thread', async () => ({ status: 'succeeded' }));
  await store.sync();
  expect(store.local(id)).toBeUndefined();
  expect(store.local(freshId)?.browser.result).toBe('succeeded');
  expect(JSON.parse(localStorage.getItem(TIMING_STORAGE_KEY)!).map((row: { submission_id: string }) => row.submission_id)).toEqual([freshId]);
});

it('keeps in-flight timing evidence available across expiry until the submission settles', async () => {
  setBrowserRetentionDays(7);
  vi.setSystemTime(now - 8 * day);
  const id = '11111111-1111-4111-8111-111111111111';
  const remote = timingApi(), store = createPromptTimingStore(remote);
  let finish!: (result: { status: string }) => void;
  const pending = store.submit(id, 'thread', () => new Promise<{ status: string }>(resolve => { finish = resolve; }));
  try {
    vi.setSystemTime(now);
    expect(store.local(id)?.submitted_at_ms).toBe(now - 8 * day);
    expect(pruneBrowserData()).toBe(0);
  } finally { finish({ status: 'succeeded' }); await pending; }
  await store.sync();
  expect(store.local(id)).toBeUndefined();
  expect(JSON.parse(localStorage.getItem(TIMING_STORAGE_KEY)!)).toEqual([]);
  expect(remote.syncPromptTimings).not.toHaveBeenCalled();
});

it('rejects invalid retention and cleanup responses', () => {
  expect(decodeDataRetention({ records_days: '7', attachments_days: 30 })).toBeNull();
  expect(decodeDataRetention({ records_days: 7, attachments_days: 30 })).toEqual({ records_days: 7, attachments_days: 30 });
  expect(decodeDataPrune({ policy: { records_days: 7, attachments_days: 30 }, records: -1, bytes_freed: 0, errors: {}, results: {} })).toBeNull();
});

it('does not sweep browser data until the server policy arrives; reports partial cleanup', async () => {
  let resolve!: (value: { records_days: 90; attachments_days: 7 }) => void;
  const api = {
    readDataRetention: vi.fn(() => new Promise(resolvePolicy => { resolve = resolvePolicy; })),
    pruneData: vi.fn(async () => ({ policy: { records_days: 90, attachments_days: 7 }, records: 2, bytes_freed: 0, results: {}, errors: { attachments: 'cleanup_failed' } })),
  } as unknown as FocusWebApiPort;
  const owner = createDataRetention(api);
  owner.start();
  expect(localStorage.length).toBe(0);
  resolve({ records_days: 90, attachments_days: 7 });
  await vi.advanceTimersByTimeAsync(0);
  expect(owner.policy.value).toEqual({ records_days: 90, attachments_days: 7 });
  await owner.prune();
  expect(owner.notice.value).toMatch(/2/);
  expect(owner.notice.value).toMatch(/retry|重试/i);
  owner.dispose();
  await vi.advanceTimersByTimeAsync(60 * 60 * 1000);
  expect(api.readDataRetention).toHaveBeenCalledTimes(1);
});

it('does not use stale timestamps for equal-length replacement history', () => {
  localStorage.setItem(STORAGE_KEYS.inputHistory, JSON.stringify({ scope: ['old'] }));
  recordHistoryTime('scope', [], ['old'], now - 31 * day);
  localStorage.setItem(STORAGE_KEYS.inputHistory, JSON.stringify({ scope: ['fresh replacement'] }));
  expect(pruneBrowserData()).toBe(0);
  expect(JSON.parse(localStorage.getItem(STORAGE_KEYS.inputHistory)!).scope).toEqual(['fresh replacement']);
});


it('a quota failure cannot leave an old deletion timestamp on a freshly saved draft', () => {
  const key = draftStorageKey('fresh');
  localStorage.setItem(key, 'old');
  vi.setSystemTime(now - 31 * day);
  touchDraft(key);
  vi.setSystemTime(now);
  localStorage.setItem(key, 'new text');
  const setItem = localStorage.setItem.bind(localStorage);
  const write = vi.spyOn(localStorage, 'setItem').mockImplementation((name, value) => {
    if (name === 'focus-web.data-retention.v1') throw new Error('quota');
    setItem(name, value);
  });
  touchDraft(key);
  write.mockRestore();
  expect(pruneBrowserData()).toBe(0);
  expect(localStorage.getItem(key)).toBe('new text');
});
