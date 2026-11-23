import { mobileRecords, recoveryStorage } from '../../lib/mobileHost';
import { trimThreadToolExpansion } from '../toolGroupPresentation';
import type { TranscriptScrollAnchor } from './transcriptScrollAnchor';

const KEY = 'focus-web.thread-reading.v1';
const LIMIT_KEY = 'focus-web.thread-reading-limit';
const OLD_BOOKMARK = 'focus-web.reading-bookmark';
const OLD_MODE = 'focus-web.reading-thread';
export const THREAD_READING_LIMITS = [5, 10, 20];

export interface ReadingBookmark {
  turn: string;
  item: string;
  anchor: TranscriptScrollAnchor;
}
interface ThreadReading {
  thread: string;
  reading: boolean;
  bookmark: ReadingBookmark | null;
}

export function readingLimit(): number {
  try {
    const value = Number(localStorage.getItem(LIMIT_KEY));
    if (THREAD_READING_LIMITS.includes(value)) return value;
  } catch { /* Browser preferences may be unavailable. */ }
  return 10;
}

function validBookmark(value: ReadingBookmark | null): boolean {
  return !!value && typeof value.turn === 'string' && typeof value.item === 'string'
    && typeof value.anchor?.id === 'string' && Number.isFinite(value.anchor.offset) && Number.isFinite(value.anchor.scrollTop);
}

function entries(): ThreadReading[] {
  const store = recoveryStorage();
  const raw = store.getItem(KEY);
  if (raw !== null) {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((r: ThreadReading) => r && typeof r.thread === 'string'
      && typeof r.reading === 'boolean' && (r.bookmark === null || validBookmark(r.bookmark))).slice(-readingLimit()) : [];
  }
  const oldMode = store.getItem(OLD_MODE);
  let previous: (ReadingBookmark & { scope: string }) | null = null;
  try { previous = JSON.parse(store.getItem(OLD_BOOKMARK) ?? 'null'); } catch { /* Keep a valid mode even if its old anchor is corrupt. */ }
  const thread = typeof previous?.scope === 'string'
    ? new RegExp('^(?:mobile:[^:]+|[^:]+:generation:[0-9]+):thread:(.+)$', 's').exec(previous.scope)?.[1] : '';
  const migrated: ThreadReading[] = [];
  if (oldMode && oldMode !== thread) migrated.push({ thread: oldMode, reading: true, bookmark: null });
  if (thread && previous && validBookmark(previous)) {
    const { turn, item, anchor } = previous;
    migrated.push({ thread, reading: thread === oldMode, bookmark: { turn, item, anchor } });
  } else if (thread && thread === oldMode) migrated.push({ thread, reading: true, bookmark: null });
  if (oldMode || previous) {
    store.setItem(KEY, JSON.stringify(migrated));
    store.removeItem(OLD_MODE);
    store.removeItem(OLD_BOOKMARK);
  }
  return migrated;
}

export function setReadingLimit(value: number): void {
  if (!THREAD_READING_LIMITS.includes(value)) return;
  try {
    localStorage.setItem(LIMIT_KEY, String(value));
    trimThreadToolExpansion(value);
    recoveryStorage().setItem(KEY, JSON.stringify(entries().slice(-value)));
  } catch { /* Saving a preference is optional. */ }
}

export function threadReading(thread: string): ThreadReading | undefined {
  try { return entries().find(row => row.thread === thread); } catch { return undefined; }
}

function remember(thread: string, changes: Partial<Pick<ThreadReading, 'reading' | 'bookmark'>>): void {
  if (!thread) return;
  try {
    let rows: ThreadReading[];
    try { rows = entries(); } catch { rows = []; }
    const previous = rows.find(row => row.thread === thread);
    const entry = { reading: false, bookmark: null, ...previous, thread, ...changes };
    const next = [...rows.filter(row => row.thread !== thread), entry].slice(-readingLimit());
    const data = JSON.stringify(next);
    const store = recoveryStorage();
    if (data !== store.getItem(KEY)) {
      store.setItem(KEY, data);
      mobileRecords('bookmark',{thread,now:Date.now(),anchor:JSON.stringify({
        turn:entry.bookmark?.turn, item:entry.bookmark?.item, chunk:entry.bookmark?.anchor.chunk,
        offset:entry.bookmark?.anchor.offset, reading:entry.reading,
      })});
    }
  } catch { /* Reading and navigation work without storage. */ }
}

export function rememberReadingMode(thread: string, reading: boolean): void { remember(thread, { reading }); }
export function saveReadingBookmark(thread: string, bookmark: ReadingBookmark | null): void { remember(thread, { bookmark }); }
