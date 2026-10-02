import type { ChatTurn } from '../types';
import type { FocusTranscriptPage } from './types';
import { TRANSCRIPT_WINDOW_ITEMS } from './transcriptItems';

export const TRANSCRIPT_CACHE_PAGES = 10;
export const TRANSCRIPT_CACHE_BYTES = 8 * 1024 * 1024;

interface CachedPage {
  rows: ChatTurn[];
  older: string | null;
  newer: string | null;
}

/** Contiguous source pages, with one copy of each row and no durable cache. */
export class TranscriptPageWindow {
  private pages: CachedPage[] = [];
  private sizes = new Map<string, { row: ChatTurn; bytes: number }>();
  atTail = false;

  get rows(): ChatTurn[] { return this.pages.flatMap(page => page.rows); }
  get older(): string | null { return this.pages[0]?.older ?? null; }
  get newer(): string | null { return this.pages.at(-1)?.newer ?? null; }
  get pageCount(): number { return this.pages.length; }
  get bytes(): number { return [...this.sizes.values()].reduce((sum, entry) => sum + entry.bytes, 0); }

  clear(): void { this.pages = []; this.sizes.clear(); this.atTail = false; }

  replace(page: FocusTranscriptPage, atTail: boolean): void {
    this.clear();
    this.pages = [{ rows: page.turns, older: page.older_cursor, newer: page.newer_cursor }];
    this.atTail = atTail;
    this.measure();
  }

  extend(page: FocusTranscriptPage, direction: 'older' | 'newer', protectedRow: string | null = null): void {
    const incoming = new Map(page.turns.map(row => [row.id, row]));
    const existing = new Set(this.rows.map(row => row.id));
    // Reversing upstream cursors includes their anchor again. Refresh that row
    // in its existing page instead of duplicating either the row or its budget.
    this.pages = this.pages.map(cached => ({ ...cached,
      rows: cached.rows.map(row => incoming.get(row.id) ?? row),
    }));
    const rows = page.turns.filter(row => !existing.has(row.id));
    if (rows.length || !this.pages.length) {
      const next = { rows, older: page.older_cursor, newer: page.newer_cursor };
      if (direction === 'older') this.pages.unshift(next);
      else this.pages.push(next);
    } else if (direction === 'older') this.pages[0]!.older = page.older_cursor;
    else this.pages.at(-1)!.newer = page.newer_cursor;
    if (direction === 'newer') this.atTail = !page.newer_cursor;
    this.bound(direction, protectedRow);
  }

  /** Streaming changes reuse page boundaries; only the live tail may grow. */
  update(rows: ChatTurn[], direction: 'older' | 'newer', protectedRow: string | null = null): boolean {
    const previous = this.pages;
    const previousTail = this.atTail;
    const incoming = new Map(rows.map(row => [row.id, row]));
    const existing = new Set(this.rows.map(row => row.id));
    this.pages = this.pages.map(page => ({ ...page,
      rows: page.rows.flatMap(row => incoming.has(row.id) ? [incoming.get(row.id)!] : []),
    }));
    const additions = rows.filter(row => !existing.has(row.id));
    if (!this.pages.length && additions.length) this.pages.push({ rows: [], older: null, newer: null });
    const tail = this.pages.at(-1);
    if (tail) {
      tail.rows.push(...additions);
      const order = new Map(rows.map((row, index) => [row.id, index]));
      tail.rows.sort((a, b) => order.get(a.id)! - order.get(b.id)!);
    }
    // Newly streamed rows do not have source cursors yet. Re-read the head
    // before allowing pagination after a live page has outgrown its budget.
    const overflow = !!tail && tail.rows.length > TRANSCRIPT_WINDOW_ITEMS;
    if (overflow) tail!.rows = tail!.rows.slice(-TRANSCRIPT_WINDOW_ITEMS);
    this.bound(direction, protectedRow);
    if (this.bytes > TRANSCRIPT_CACHE_BYTES) {
      // A single growing live page cannot be evicted without losing its source
      // cursor. Keep the last bounded view until the owner resynchronizes it.
      this.pages = previous; this.atTail = previousTail; this.measure();
      return true;
    }
    return overflow;
  }

  private measure(): void {
    const next = new Map<string, { row: ChatTurn; bytes: number }>();
    for (const row of this.rows) {
      const previous = this.sizes.get(row.id);
      next.set(row.id, previous?.row === row ? previous
        : { row, bytes: JSON.stringify(row).length * 2 });
    }
    this.sizes = next;
  }

  private bound(direction: 'older' | 'newer', protectedRow: string | null = null): void {
    this.measure();
    while (this.pages.length > 1 && (this.pages.length > TRANSCRIPT_CACHE_PAGES
      || this.bytes > TRANSCRIPT_CACHE_BYTES)) {
      const evictTail = direction === 'older';
      const candidate = evictTail ? this.pages.at(-1)! : this.pages[0]!;
      const protectedEdge = candidate.rows.some(row => row.id === protectedRow);
      if (evictTail !== protectedEdge) { this.pages.pop(); this.atTail = false; }
      else this.pages.shift();
      this.measure();
    }
  }
}
