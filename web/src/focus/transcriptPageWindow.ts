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

  /** Refresh the live edge without replacing a reader's earlier cached rows. */
  refreshTail(page: FocusTranscriptPage, protectedRow: string): void {
    const existing = new Set(this.rows.map(row => row.id));
    const overlap = page.turns.findIndex(row => existing.has(row.id));
    if (overlap < 0) {
      // A long disconnect can leave a real gap. Keep the reading window and
      // let its exact last item anchor bridge it, never join disjoint pages.
      this.atTail = false;
      return;
    }
    // A latest-first read can still carry an inclusive backwards cursor.
    // Its query proves the tail; the presence of that cursor does not deny it.
    this.extend({ ...page, turns: page.turns.slice(overlap) }, 'newer', protectedRow, true);
  }

  extend(page: FocusTranscriptPage, direction: 'older' | 'newer', protectedRow: string | null = null,
    atTail = !page.newer_cursor): void {
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
    if (direction === 'newer') this.atTail = atTail;
    this.bound(direction, protectedRow);
  }

  /** Streaming changes reuse page boundaries; only the live tail may grow. */
  update(rows: ChatTurn[], direction: 'older' | 'newer', protectedRow: string | null = null): boolean {
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
    if (overflow) {
      const anchorIndex = tail!.rows.findIndex(row => row.id === protectedRow);
      if (anchorIndex >= 0 && anchorIndex < tail!.rows.length - TRANSCRIPT_WINDOW_ITEMS) {
        tail!.rows = tail!.rows.slice(0, TRANSCRIPT_WINDOW_ITEMS);
        this.atTail = false;
        this.bound(direction, protectedRow);
        return false;
      }
      tail!.rows = tail!.rows.slice(-TRANSCRIPT_WINDOW_ITEMS);
    }
    this.bound(direction, protectedRow);
    // A complete current item can exceed the cache target. Keep its new text;
    // shrinking pages on the next source read retires older whole items.
    const currentTail = this.pages.at(-1);
    return overflow || (!!currentTail && currentTail.rows.length > 1
      && this.pageBytes(currentTail) > TRANSCRIPT_CACHE_BYTES);
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
      // Keep one adjacent page reachable while the reader is inside a large
      // page. Otherwise every next page would be discarded before they can
      // scroll into it. The exception ends as soon as the anchor moves away.
      if (protectedEdge && this.pages.length === 2) break;
      if (evictTail !== protectedEdge) { this.pages.pop(); this.atTail = false; }
      else this.pages.shift();
      this.measure();
    }
  }

  private pageBytes(page: CachedPage): number {
    return page.rows.reduce((sum, row) => sum + (this.sizes.get(row.id)?.bytes ?? 0), 0);
  }
}
