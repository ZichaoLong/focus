import { describe, expect, it } from 'vitest';
import { TranscriptPageWindow, TRANSCRIPT_CACHE_BYTES } from '../../../src/focus/transcriptPageWindow';
import type { FocusTranscriptPage } from '../../../src/focus/types';
import type { ChatTurn } from '../../../src/types';

const row = (n: number, text = `${n}`): ChatTurn => ({ id: `row-${n}`, rawTurnId: `turn-${Math.floor(n / 100)}`,
  itemId: `item-${n}`, role: 'assistant', no: 0, text });
const page = (start: number, count = 40, text?: string): FocusTranscriptPage => ({
  runtime_epoch: 'epoch', revision: 1, thread_id: 'thread', turn_id: null, view: 'transcript',
  target_pending: false, full_text: null, older_cursor: `before-${start}`, newer_cursor: `after-${start + count}`,
  turns: Array.from({ length: count }, (_, i) => row(start + i, text)),
});

describe('contiguous transcript cache', () => {
  it('retains ten visited pages, evicts the distant edge, and keeps continuation cursors', () => {
    const cache = new TranscriptPageWindow();
    cache.replace(page(480), true);
    for (let start = 440; start >= 0; start -= 40) cache.extend(page(start), 'older');
    expect(cache.pageCount).toBe(10);
    expect(cache.rows).toHaveLength(400);
    expect(cache.rows[0]?.id).toBe('row-0');
    expect(cache.rows.at(-1)?.id).toBe('row-399');
    expect(cache.older).toBe('before-0');
    expect(cache.newer).toBe('after-400');
    expect(cache.atTail).toBe(false);
    cache.extend(page(399, 40), 'newer');
    expect(cache.rows.map(row => row.id)).toEqual(Array.from({ length: 399 }, (_, i) => `row-${40 + i}`));
    expect(cache.older).toBe('before-40');
  });

  it('refreshes inclusive boundary rows without duplicate rows or empty cache pages', () => {
    const cache = new TranscriptPageWindow(); cache.replace(page(40), false);
    cache.extend(page(0, 41, 'updated'), 'older');
    expect(cache.rows).toHaveLength(80);
    expect(cache.rows.find(row => row.id === 'row-40')?.text).toBe('updated');
    cache.extend({ ...page(79, 1), newer_cursor: null }, 'newer');
    expect(cache.rows).toHaveLength(80);
    expect(cache.pageCount).toBe(2);
    expect(cache.atTail).toBe(true);
  });

  it('uses the byte ceiling before the page ceiling and releases old row references', () => {
    const cache = new TranscriptPageWindow(); cache.replace(page(400, 40, 'x'.repeat(16_000)), true);
    for (let start = 360; start >= 0; start -= 40) cache.extend(page(start, 40, 'x'.repeat(16_000)), 'older');
    expect(cache.bytes).toBeLessThanOrEqual(TRANSCRIPT_CACHE_BYTES);
    expect(cache.pageCount).toBeLessThan(10);
    cache.clear(); expect(cache.rows).toEqual([]); expect(cache.bytes).toBe(0);
  });

  it('protects the reader after reversing direction during a delayed page request', () => {
    const cache = new TranscriptPageWindow(); cache.replace(page(360), true);
    for (let start = 320; start >= 0; start -= 40) cache.extend(page(start), 'older');
    cache.extend(page(-40), 'older', 'row-399');
    expect(cache.rows).toHaveLength(400);
    expect(cache.rows.at(-1)?.id).toBe('row-399');
    expect(cache.older).toBe('before-0');
    expect(cache.atTail).toBe(true);
  });

  it('admits an oversized current item intact and retires it when browsing to another page', () => {
    const cache = new TranscriptPageWindow();
    const text = '正文'.repeat(TRANSCRIPT_CACHE_BYTES / 4);
    cache.replace(page(0, 1, text), true);
    expect(cache.rows[0]?.text).toBe(text);
    expect(cache.update([row(0, text + '追加')], 'newer')).toBe(false);
    expect(cache.rows[0]?.text).toBe(text + '追加');
    cache.extend(page(1, 1), 'newer');
    expect(cache.rows.map(row => row.id)).toEqual(['row-1']);
    expect(cache.bytes).toBeLessThan(TRANSCRIPT_CACHE_BYTES);
  });

  it.each(['older', 'newer'] as const)('keeps an adjacent %s page reachable beside an oversized reader anchor', direction => {
    const cache = new TranscriptPageWindow();
    cache.replace(page(40, 1, '正文'.repeat(TRANSCRIPT_CACHE_BYTES / 4)), false);
    cache.extend(page(direction === 'older' ? 0 : 41, 1), direction, 'row-40');
    expect(cache.pageCount).toBe(2);
    expect(cache.rows).toHaveLength(2);
    expect(cache.update(cache.rows, direction, 'row-40')).toBe(false);
    cache.update(cache.rows, direction, direction === 'older' ? 'row-0' : 'row-41');
    expect(cache.pageCount).toBe(1);
    expect(cache.rows[0]?.id).toBe(direction === 'older' ? 'row-0' : 'row-41');
  });

  it('refreshes overlapping tail rows while retaining the protected earlier page', () => {
    const cache = new TranscriptPageWindow(); cache.replace(page(40), true);
    cache.extend(page(0), 'older');
    cache.refreshTail(page(70, 40, 'refreshed'), 'row-10');
    expect(cache.rows).toHaveLength(110);
    expect(cache.rows[10]?.id).toBe('row-10');
    expect(cache.rows[70]?.text).toBe('refreshed');
    expect(cache.atTail).toBe(true);
    expect(cache.newer).toBe('after-110');
    cache.refreshTail({ ...page(200), newer_cursor: null }, 'row-10');
    expect(cache.rows).toHaveLength(110);
    expect(cache.atTail).toBe(false);
  });

  it('stops extending a full live page before evicting the reader inside it', () => {
    const cache = new TranscriptPageWindow(); cache.replace({ ...page(0), newer_cursor: null }, true);
    expect(cache.update(Array.from({ length: 81 }, (_, i) => row(i)), 'newer', 'row-0')).toBe(false);
    expect(cache.rows).toHaveLength(80);
    expect(cache.rows[0]?.id).toBe('row-0');
    expect(cache.rows.at(-1)?.id).toBe('row-79');
    expect(cache.atTail).toBe(false);
    expect(cache.newer).toBeNull();
  });
});
