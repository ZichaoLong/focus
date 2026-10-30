/** Browser history timestamps and expiry. Preferences and recovery receipts are excluded. */
import { STORAGE_KEYS, safeGetJson, safeGetString, safeRemove } from './storage';

const META_KEY = 'focus-web.data-retention.v1';
export const TIMING_STORAGE_KEY = 'focus-web.prompt-timings.v1';
const DRAFT_PREFIX = 'kimi-web.draft.';
interface Metadata { drafts: Record<string, number>; history: Record<string, number[]>; historyDigests: Record<string, string> }
let recordsDays: number | null = null;
const activeDrafts = new Map<string, number>();
export function protectDraft(key: string): () => void {
  activeDrafts.set(key, (activeDrafts.get(key) ?? 0) + 1);
  touchDraft(key);
  return () => {
    const count = (activeDrafts.get(key) ?? 1) - 1;
    if (count) activeDrafts.set(key, count); else activeDrafts.delete(key);
  };
}
export const activeTimingIds = new Set<string>();

function metadata(): Metadata {
  const raw = safeGetJson<Metadata>(META_KEY);
  if (raw === null) return { drafts: {}, history: {}, historyDigests: {} };
  if (!raw || typeof raw !== 'object' || !raw.drafts || !raw.history
    || typeof raw.drafts !== 'object' || typeof raw.history !== 'object'
    || Object.values(raw.drafts).some(value => !Number.isFinite(value) || value <= 0)
    || Object.values(raw.history).some(value => !Array.isArray(value)
      || value.some(stamp => !Number.isFinite(stamp) || stamp <= 0))) {
    throw new Error('Invalid browser retention metadata');
  }
  return { ...raw, historyDigests: raw.historyDigests ?? {} };
}

export function setBrowserRetentionDays(days: number): void {
  if (![7, 30, 90].includes(days)) throw new Error('Invalid retention period');
  recordsDays = days;
}

export function retainedTimestamp(stamp: number, now = Date.now()): boolean {
  return recordsDays === null || stamp >= now - recordsDays * 86_400_000;
}

export function touchDraft(key: string, present = true): void {
  try {
    const meta = metadata();
    if (present && safeGetString(key)) meta.drafts[key] = Date.now();
    else if (key in meta.drafts) delete meta.drafts[key];
    else return;
    localStorage.setItem(META_KEY, JSON.stringify(meta));
  } catch { safeRemove(META_KEY); /* Missing timestamps grant migration grace. */ }
}

// A change marker detects stale metadata from another tab or a failed text write.
// It is not an authentication or execution authority token.
function historyDigest(entries: string[]): string {
  const source = JSON.stringify(entries);
  let first = 2166136261, second = 5381;
  for (let index = 0; index < source.length; index += 1) {
    first = Math.imul(first ^ source.charCodeAt(index), 16777619);
    second = Math.imul(second, 33) ^ source.charCodeAt(index);
  }
  return `${source.length}:${first >>> 0}:${second >>> 0}`;
}

export function recordHistoryTime(scope: string, previous: string[], next: string[], now = Date.now()): void {
  try {
    const meta = metadata();
    const existing = meta.history[scope];
    const stamps = existing?.length === previous.length && meta.historyDigests[scope] === historyDigest(previous)
      ? existing : Array<number>(previous.length).fill(now);
    meta.history[scope] = [...stamps, now].slice(-100);
    meta.historyDigests[scope] = historyDigest(next);
    localStorage.setItem(META_KEY, JSON.stringify(meta));
  } catch { safeRemove(META_KEY); /* A partial write cannot leave stale expiry authority. */ }
}

/** Undated data gets a full retention period from first observation after upgrade. */
export function pruneBrowserData(now = Date.now()): number {
  if (recordsDays === null) return 0;
  const storage = globalThis.localStorage; // Throw to the caller when storage is unavailable.
  const meta = metadata();
  let removed = 0;
  const drafts = new Set(Array.from({ length: storage.length }, (_, index) => storage.key(index))
    .filter((key): key is string => key !== null && key.startsWith(DRAFT_PREFIX)));
  for (const key of drafts) {
    const stamp = activeDrafts.has(key) ? now : (meta.drafts[key] ?? now);
    meta.drafts[key] = stamp;
    if (!retainedTimestamp(stamp, now)) {
      storage.removeItem(key);
      delete meta.drafts[key];
      removed += 1;
    }
  }
  for (const key of Object.keys(meta.drafts)) if (!drafts.has(key)) delete meta.drafts[key];
  const raw: unknown = JSON.parse(storage.getItem(STORAGE_KEYS.inputHistory) ?? '{}');
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    const history = raw as Record<string, unknown>;
    for (const [scope, entries] of Object.entries(history)) {
      if (!Array.isArray(entries) || entries.some(entry => typeof entry !== 'string')) continue;
      const existing = meta.history[scope];
      const stamps = existing?.length === entries.length && meta.historyDigests[scope] === historyDigest(entries)
        ? existing : Array<number>(entries.length).fill(now);
      const kept: string[] = [], times: number[] = [];
      entries.forEach((entry: string, index: number) => {
        if (retainedTimestamp(stamps[index]!, now)) { kept.push(entry); times.push(stamps[index]!); }
        else removed += 1;
      });
      if (kept.length) { history[scope] = kept; meta.history[scope] = times; meta.historyDigests[scope] = historyDigest(kept); }
      else { delete history[scope]; delete meta.history[scope]; delete meta.historyDigests[scope]; }
    }
    for (const key of Object.keys(meta.history)) if (!(key in history)) {
      delete meta.history[key]; delete meta.historyDigests[key];
    }
    storage.setItem(STORAGE_KEYS.inputHistory, JSON.stringify(history));
  }
  const timings: unknown = JSON.parse(storage.getItem(TIMING_STORAGE_KEY) ?? '[]');
  if (Array.isArray(timings)) {
    const kept = timings.filter(row => !row || typeof row.submitted_at_ms !== 'number'
      || activeTimingIds.has(row.submission_id) || retainedTimestamp(row.submitted_at_ms, now));
    removed += timings.length - kept.length;
    storage.setItem(TIMING_STORAGE_KEY, JSON.stringify(kept));
  }
  storage.setItem(META_KEY, JSON.stringify(meta));
  return removed;
}
