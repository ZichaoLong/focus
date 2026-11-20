/** Browser draft and timing expiry. Preferences and recovery receipts are excluded. */
import { persistMobilePresentation } from './mobilePresentation';
import { STORAGE_KEYS, safeGetJson, safeGetString, safeRemove } from './storage';

const META_KEY = 'focus-web.data-retention.v1';
export const TIMING_STORAGE_KEY = 'focus-web.prompt-timings.v1';
const DRAFT_PREFIX = 'kimi-web.draft.';
interface Metadata { drafts: Record<string, number> }
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
  if (raw === null) return { drafts: {} };
  if (!raw || typeof raw !== 'object' || !raw.drafts
    || typeof raw.drafts !== 'object'
    || Object.values(raw.drafts).some(value => !Number.isFinite(value) || value <= 0)) {
    throw new Error('Invalid browser retention metadata');
  }
  return { drafts: raw.drafts };
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
      persistMobilePresentation(key, null);
      delete meta.drafts[key];
      removed += 1;
    }
  }
  for (const key of Object.keys(meta.drafts)) if (!drafts.has(key)) delete meta.drafts[key];
  // Retire the former arrow-key recall cache; conversation history is separate.
  if (storage.getItem(STORAGE_KEYS.inputHistory) !== null) {
    storage.removeItem(STORAGE_KEYS.inputHistory);
    removed += 1;
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
