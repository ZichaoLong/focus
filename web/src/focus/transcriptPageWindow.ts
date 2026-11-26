import type { ChatTurn } from '../types';
import type { FocusTranscriptPage } from './types';
import { TRANSCRIPT_PAGE_ITEMS, TRANSCRIPT_WINDOW_ITEMS } from './transcriptItems';

export const TRANSCRIPT_CACHE_PAGES = 10;
export const TRANSCRIPT_CACHE_BYTES = 8 * 1024 * 1024;
export const MAX_TAIL_FILL_READS = 2;

interface CachedPage {
  rows: ChatTurn[];
  older: string | null;
  newer: string | null;
  needsOlderAnchor?: boolean;
}

function isEmptyReasoningItem(row: ChatTurn): boolean {
  const block = row.blocks?.[0];
  return row.role === 'assistant' && !row.contentDeferred && !row.tools?.length && !row.text && !row.thinking
    && row.blocks?.length === 1 && block?.kind === 'thinking' && block.itemId === row.itemId && block.thinking === '';
}

/** Contiguous source pages, with one copy of each row and no durable cache. */
export class TranscriptPageWindow {
  private pages: CachedPage[] = [];
  private sizes = new Map<string, { row: ChatTurn; bytes: number }>();
  atTail = false;

  get rows(): ChatTurn[] { return this.pages.flatMap(page => page.rows); }
  get older(): string | null { return this.pages[0]?.older ?? null; }
  get needsOlderAnchor(): boolean { return !!this.pages[0]?.needsOlderAnchor; }
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

  /** Install the authoritative head, keeping only a proven adjacent prefix. */
  returnToLatest(page: FocusTranscriptPage): void {
    const rows = this.rows;
    const start = rows.findIndex(row => row.id === page.turns[0]?.id);
    const incoming = new Set(page.turns.map(row => row.id));
    if (!page.older_cursor || start <= 0
      || rows.slice(start).some((row, i) => row.id !== page.turns[i]?.id)
      || rows.slice(0, start).some(row => incoming.has(row.id))) {
      this.replace(page, true);
      return;
    }
    const prefix: CachedPage[] = [];
    let remaining = start;
    for (const cached of this.pages) {
      if (!remaining) break;
      if (cached.rows.length > remaining) {
        // The original forward cursor would skip the rest of this split page.
        // If the head is evicted, newer() continues from the exact last item.
        prefix.push({ ...cached, rows: cached.rows.slice(0, remaining), newer: null });
        break;
      }
      prefix.push(cached);
      remaining -= cached.rows.length;
    }
    // Frequent overlapping heads can advance by just one item. Adjacent small
    // slices share one cache page without losing either outer cursor.
    const last = prefix.at(-1);
    const previous = prefix.at(-2);
    if (last && previous && previous.rows.length + last.rows.length <= TRANSCRIPT_PAGE_ITEMS) {
      prefix.splice(-2, 2, { ...previous, rows: [...previous.rows, ...last.rows], newer: last.newer });
    }
    this.pages = [...prefix, { rows: page.turns, older: page.older_cursor, newer: page.newer_cursor }];
    this.atTail = true;
    this.bound('newer');
  }

  /** Refresh the live edge without replacing a reader's earlier cached rows. */
  refreshTail(page: FocusTranscriptPage, protectedRow: string): void {
    const rows = this.rows;
    const existing = new Set(rows.map(row => row.id));
    const overlap = page.turns.findIndex(row => existing.has(row.id));
    const start = rows.findIndex(row => row.id === page.turns[overlap]?.id);
    if (start < 0 || rows.slice(start).some((row, i) => row.id !== page.turns[overlap + i]?.id)) {
      // Retain the reading anchor; exact newer navigation can bridge a gap.
      this.atTail = false;
      return;
    }
    // A latest-first read can still carry an inclusive backwards cursor.
    // Its query proves the tail; the presence of that cursor does not deny it.
    this.extend({ ...page, turns: page.turns.slice(overlap) }, 'newer', protectedRow, true);
  }

  extend(page: FocusTranscriptPage, direction: 'older' | 'newer' | 'tail-context', protectedRow: string | null = null,
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
      if (direction !== 'newer') this.pages.unshift(next);
      else this.pages.push(next);
    } else if (direction !== 'newer') this.pages[0]!.older = page.older_cursor;
    else this.pages.at(-1)!.newer = page.newer_cursor;
    if (direction === 'newer') this.atTail = atTail;
    // An optional prepend may discard its own page, never the confirmed tail.
    if (direction === 'tail-context') this.bound('newer');
    else this.bound(direction, protectedRow);
  }

  /** A replay installs headers only where the same compact identities still reside. */
  hydrateTools(cursor: string, source: FocusTranscriptPage, protectedRow: string | null): string[] {
    const rows = source.turns;
    const resident = this.rows;
    const pending = resident.filter(row => row.compactTool?.cursor === cursor);
    if (!pending.length) return [];
    let toolCount = 0;
    for (const row of rows) {
      if (row.contentDeferred && row.tools?.length === 1) toolCount++;
      else if (!isEmptyReasoningItem(row)) return [];
    }
    for (const row of pending) {
      const member = row.compactTool!;
      const replayed = rows[member.index];
      if (member.pageSize !== rows.length || member.count !== toolCount
        || replayed?.id !== row.id || !replayed.contentDeferred) return [];
    }
    const start = resident.indexOf(pending[0]!) - pending[0]!.compactTool!.index;
    const first = Math.max(0, start);
    if (resident.slice(first, start + rows.length).some((row, i) => row.id !== rows[first + i - start]?.id)) return [];
    const replacements = new Map(pending.map(row => [row.id, rows[row.compactTool!.index]!]));
    const ids = new Set(rows.map(row => row.id));
    this.pages = this.pages.flatMap(page => {
      const first = page.rows.findIndex(row => ids.has(row.id));
      if (first < 0) return [page];
      let end = first + 1;
      while (end < page.rows.length && ids.has(page.rows[end]!.id)) end++;
      const before = page.rows.slice(0, first), after = page.rows.slice(end);
      const members = page.rows.slice(first, end).map(row => replacements.get(row.id) ?? row);
      // Expanded headers occupy a normal cache page. A surviving partial
      // boundary continues by exact item when its cursor cannot be proven.
      const exactStart = members[0]!.id === rows[0]!.id;
      const exactEnd = members.at(-1)!.id === rows.at(-1)!.id;
      return [
        ...(before.length ? [{ ...page, rows: before, newer: null }] : []),
        { rows: members, older: before.length ? (exactStart ? source.older_cursor : null) : page.older,
          needsOlderAnchor: before.length ? !exactStart : page.needsOlderAnchor,
          newer: after.length ? (exactEnd ? source.newer_cursor : null) : page.newer },
        ...(after.length ? [{ ...page, rows: after, older: exactEnd ? cursor : null, needsOlderAnchor: !exactEnd }] : []),
      ];
    });
    this.bound('newer', protectedRow);
    return [...replacements.keys()];
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
    // A coalesced item_order may cross a previously sealed page. Repartition
    // in authoritative order, retaining cursors only at unchanged boundaries.
    let offset = 0;
    for (const page of this.pages) {
      const length = page.rows.length;
      if (page.rows.some((row, i) => row.id !== rows[offset + i]?.id)) {
        const ordered = rows.slice(offset, offset + length);
        if (page.rows[0]?.id !== ordered[0]?.id) {
          page.needsOlderAnchor = offset > 0 || !!page.older || page.needsOlderAnchor;
          page.older = null;
        }
        if (page.rows.at(-1)?.id !== ordered.at(-1)?.id) page.newer = null;
        page.rows = ordered;
      }
      offset += length;
    }
    // A head read supplies real cursor boundaries. While it is in flight,
    // partition the ordered stream by identity and keep its adjacent prefix.
    // A provisional edge can only be reopened by its exact source item.
    const confirm = !!tail && tail.rows.length >= TRANSCRIPT_WINDOW_ITEMS - 8;
    if (tail && tail.rows.length > TRANSCRIPT_WINDOW_ITEMS) {
      const anchorIndex = tail.rows.findIndex(row => row.id === protectedRow);
      if (anchorIndex >= 0 && anchorIndex < tail.rows.length - TRANSCRIPT_WINDOW_ITEMS) {
        tail.rows = tail.rows.slice(0, TRANSCRIPT_WINDOW_ITEMS);
        tail.newer = null;
        this.atTail = false;
        this.bound(direction, protectedRow);
        return false;
      }
      let edge = tail;
      while (edge.rows.length > TRANSCRIPT_WINDOW_ITEMS) {
        const next: CachedPage = { rows: edge.rows.splice(TRANSCRIPT_PAGE_ITEMS), older: null, newer: null, needsOlderAnchor: true };
        edge.newer = null;
        this.pages.push(next);
        edge = next;
      }
    }
    this.bound(direction, protectedRow);
    // A complete current item can exceed the cache target. Keep its new text;
    // shrinking pages on the next source read retires older whole items.
    const currentTail = this.pages.at(-1);
    return confirm || (!!currentTail && currentTail.rows.length > 1
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
