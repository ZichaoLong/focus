import { shallowRef } from 'vue';
import { FocusApiError } from './types';
import { isBrowserTimingRecord, type BrowserTimingRecord, type PromptTimingRecord } from './promptTimingTypes';

const KEY = 'focus-web.prompt-timings.v1';
const LIMIT = 64;
type LocalRecord = BrowserTimingRecord & { clientId: string; synced: boolean; version: number };
interface TimingApi {
  clientId: string;
  syncPromptTimings(records: BrowserTimingRecord[]): Promise<unknown>;
  readPromptTiming(id: string): Promise<{ record: PromptTimingRecord | null }>;
  listPromptTimings(threadId: string): Promise<{ records: PromptTimingRecord[] }>;
}

function read(): LocalRecord[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    return Array.isArray(value) && value.length <= LIMIT ? value.filter((row): row is LocalRecord =>
      isBrowserTimingRecord(row) && typeof (row as LocalRecord).clientId === 'string'
      && typeof (row as LocalRecord).synced === 'boolean' && Number.isSafeInteger((row as LocalRecord).version)
      && (row as LocalRecord).version > 0) : [];
  } catch { return []; }
}

/** Owns browser evidence only. Sync never contains text or invokes prompt submission. */
export function createPromptTimingStore(api: TimingApi) {
  const records = shallowRef<LocalRecord[]>(read());
  const durable = shallowRef(true);
  const revision = shallowRef(0);
  const changedId = shallowRef('');
  let syncing: Promise<void> | null = null;
  let disconnected = 0;
  function merge(row?: LocalRecord) {
    const merged = new Map<string, LocalRecord>();
    for (const value of [...records.value, ...read(), ...(row ? [row] : [])]) {
      const previous = merged.get(value.submission_id);
      if (!previous || value.version > previous.version
        || (value.version === previous.version && (value.synced || !previous.synced))) merged.set(value.submission_id, value);
    }
    records.value = [...merged.values()].sort((a, b) => a.submitted_at_ms - b.submitted_at_ms).slice(-LIMIT);
  }
  function save(row: LocalRecord) {
    merge(row);
    try { localStorage.setItem(KEY, JSON.stringify(records.value)); durable.value = true; }
    catch { durable.value = false; }
  }
  async function sync(): Promise<void> {
    if (syncing) return syncing;
    syncing = (async () => {
      try {
        // Include incomplete attempts after reload, even if registration has
        // replaced the document identity. These are observations, never input.
        merge();
        for (let batch = 0; batch < 3; batch += 1) {
          const pending = records.value.filter(row => !row.synced).slice(0, 32);
          if (!pending.length) break;
          await api.syncPromptTimings(pending.map(({ submission_id, thread_id, submitted_at_ms, browser }) => (
            { submission_id, thread_id, submitted_at_ms, browser })));
          for (const row of pending) {
            if (records.value.find(value => value.submission_id === row.submission_id)?.version === row.version) save({ ...row, synced: true });
          }
        }
      } catch { /* Keep evidence for the next ready boundary or explicit refresh. */ }
    })();
    try { await syncing; } finally { syncing = null; }
  }
  async function submit<T extends { thread_id?: string; status?: string; accepted?: boolean }>(
    id: string, threadId: string, send: (headers: Record<string, string>) => Promise<T>,
  ): Promise<T> {
    merge();
    const previous = records.value.find(value => value.submission_id === id);
    const row: LocalRecord = { submission_id: id, thread_id: threadId, submitted_at_ms: previous?.submitted_at_ms ?? Date.now(),
      browser: {}, clientId: api.clientId, synced: false, version: (previous?.version ?? 0) + 1 };
    const start = performance.now(), disconnectStart = disconnected;
    save(row);
    try {
      const result = await send({ 'X-Focus-Prompt-Id': id, 'X-Focus-Submitted-At': String(row.submitted_at_ms) });
      row.thread_id = result.thread_id || threadId;
      row.browser.result = result.status ?? (result.accepted ? 'succeeded' : 'outcome_unknown');
      return result;
    } catch (error) {
      row.browser.result = error instanceof FocusApiError && error.effectEvidence === 'pre_effect' ? 'known_no_effect' : 'outcome_unknown';
      if (error instanceof FocusApiError && typeof error.details?.thread_id === 'string') row.thread_id = error.details.thread_id;
      throw error;
    } finally {
      row.browser.completed_at_ms = Date.now();
      row.browser.elapsed_ms = Math.min(86_400_000, Math.max(0, Math.round(performance.now() - start)));
      row.browser.disconnects = disconnected - disconnectStart;
      save({ ...row, version: row.version + 1, browser: { ...row.browser } });
      changedId.value = id;
      revision.value += 1;
      void sync();
    }
  }
  return {
    records, durable, revision, changedId, submit, sync,
    disconnected() { disconnected += 1; },
    changed(id: string) { changedId.value = id; revision.value += 1; },
    local(id: string) { return records.value.find(row => row.submission_id === id); },
    read: (id: string) => api.readPromptTiming(id),
    list: (threadId: string) => api.listPromptTimings(threadId),
  };
}
export type PromptTimingStore = ReturnType<typeof createPromptTimingStore>;
