import { recoveryStorage } from '../../lib/mobileHost';
import type { TranscriptScrollAnchor } from './transcriptScrollAnchor';

const KEY = 'focus-web.reading-bookmark';
export interface ReadingBookmark {
  scope: string;
  turn: string;
  item: string;
  anchor: TranscriptScrollAnchor;
}
export function readReadingBookmark(): ReadingBookmark | null {
  try {
    const value = JSON.parse(recoveryStorage().getItem(KEY) ?? 'null') as ReadingBookmark | null;
    if (!value || typeof value.scope !== 'string' || typeof value.turn !== 'string' || typeof value.item !== 'string'
      || typeof value.anchor?.id !== 'string' || !Number.isFinite(value.anchor.offset)) return null;
    return value;
  } catch { return null; }
}
export function saveReadingBookmark(bookmark: ReadingBookmark | null): void {
  try {
    if (bookmark) recoveryStorage().setItem(KEY, JSON.stringify(bookmark));
    else recoveryStorage().removeItem(KEY);
  } catch { /* Storage is optional. */ }
}
