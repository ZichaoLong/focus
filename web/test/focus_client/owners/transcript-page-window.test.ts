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
  it('keeps only the proven prefix and real edge cursors when the latest page moves', () => {
    const cache = new TranscriptPageWindow();
    cache.replace(page(40), true);
    cache.extend(page(0), 'older');
    cache.returnToLatest(page(65, 40, 'fresh'));
    expect(cache.rows.map(r => r.id)).toEqual(page(0, 105).turns.map(r => r.id));
    expect(cache.rows[64]?.text).toBe('64');
    expect(cache.rows[65]?.text).toBe('fresh');
    expect([cache.older, cache.newer, cache.atTail]).toEqual(['before-0', 'after-105', true]);
    for (let i = 1; i <= 8; i++) cache.extend(page(-40 * i), 'older');
    expect(cache.rows.at(-1)?.id).toBe('row-64');
    expect([cache.newer, cache.atTail]).toEqual([null, false]); // resume from exact row 64
  });

  it.each([
    page(90), page(60, 0), { ...page(55), older_cursor: null }, page(55, 10),
    { ...page(60), turns: [row(60), row(62), row(61)] },
    { ...page(79), turns: [row(79), row(80), row(20)] },
  ])('falls back to the authoritative head on a gap, truncation or reorder', latest => {
    const cache = new TranscriptPageWindow();
    cache.replace(page(40), true);
    cache.extend(page(0), 'older');
    cache.returnToLatest(latest);
    expect(cache.rows).toEqual(latest.turns);
    expect([cache.pageCount, cache.older, cache.atTail]).toEqual([1, latest.older_cursor, true]);
  });

  it('retains the confirmed tail when an optional older page exceeds the cache budget', () => {
    const cache = new TranscriptPageWindow();
    const tail = page(40, 1, 'x'.repeat(TRANSCRIPT_CACHE_BYTES / 2));
    cache.replace(tail, true);
    cache.extend(page(0), 'tail-context');
    expect(cache.rows).toEqual(tail.turns);
    expect([cache.older, cache.atTail]).toEqual([tail.older_cursor, true]);
  });

  it('partitions a fast live burst and verifies its overlap before retaining the prefix', () => {
    const cache = new TranscriptPageWindow();
    cache.replace(page(40), true);
    cache.extend(page(0), 'older');
    expect(cache.update(page(0, 125).turns, 'newer')).toBe(true);
    const latest = page(95);
    cache.returnToLatest(latest);
    expect(cache.rows.map(row => row.id)).toEqual(page(0, 135).turns.map(row => row.id));
    expect(cache.older).toBe('before-0');
  });

  it('rejects changed compact members and pages verified headers within the normal cache', () => {
    const cache = new TranscriptPageWindow();
    const compact = page(1).turns.map((r, index) => ({ ...r, contentDeferred: true,
      compactTool: { cursor: 'members', index, count: 40, pageSize: 40, status: 'ok' as const } }));
    cache.replace(page(41), true);
    cache.extend({ ...page(0), turns: [row(0), ...compact] }, 'tail-context');
    const headers = page(1).turns.map(r => ({ ...r, contentDeferred: true,
      tools: [{ id: r.id, arg: 'sample', name: 'Shell', status: 'ok' as const }] }));
    expect(cache.hydrateTools('members', { ...page(1), turns: [...headers].reverse() }, null)).toEqual([]);
    expect(cache.rows[1]!.compactTool?.cursor).toBe('members');
    const continuous = cache.rows;
    const interrupted = [...continuous.slice(0, 12), row(99, 'interleaved prose'), ...continuous.slice(12)];
    const changed = new TranscriptPageWindow();
    changed.replace({ ...page(0), turns: interrupted }, true);
    expect(changed.hydrateTools('members', { ...page(1), turns: headers }, null)).toEqual([]);
    expect(cache.hydrateTools('members', { ...page(1), turns: headers }, null)).toEqual(headers.map(r => r.id));
    expect(cache.pageCount).toBe(3);
    expect(cache.rows.map(r => r.id)).toEqual(page(0, 81).turns.map(r => r.id));
    expect(cache.rows[1]).toBe(headers[0]);
  });

  it('honors an ordered live update across page boundaries', () => {
    const cache = new TranscriptPageWindow();
    cache.replace(page(40), true);
    cache.extend(page(0), 'older');
    const ordered = cache.rows;
    [ordered[39], ordered[40]] = [ordered[40]!, ordered[39]!];
    cache.update(ordered, 'newer');
    expect(cache.rows).toEqual(ordered);
  });

  it('replays mixed source positions without counting blank reasoning or replacing newer live content', () => {
    const blank = { ...row(2, ''), blocks: [{ kind: 'thinking' as const, itemId: 'item-2', thinking: '' }] };
    const readable = { ...blank, blocks: [{ ...blank.blocks[0]!, thinking: 'New reasoning' }] };
    const headers = [1, 3].map(n => ({ ...row(n, ''), contentDeferred: true,
      tools: [{ id: row(n).itemId!, name: 'Shell', arg: 'sample', status: 'ok' as const }] }));
    const compact = headers.map((header, i) => ({ ...row(i * 2 + 1, ''), contentDeferred: true,
      compactTool: { cursor: 'mixed', index: i * 2, count: 2, pageSize: 3, status: header.tools[0]!.status } }));
    const cache = new TranscriptPageWindow();
    cache.replace({ ...page(0), turns: [compact[0]!, readable, compact[1]!] }, true);
    const replay = (rows: ChatTurn[]) => cache.hydrateTools('mixed', { ...page(0), turns: rows }, null);
    expect(replay([headers[0]!, readable, headers[1]!])).toEqual([]); // Source page changed kind or content.
    expect(replay([blank, ...headers])).toEqual([]);
    expect(replay(headers)).toEqual([]);
    expect(replay([headers[0]!, blank, headers[1]!])).toEqual(headers.map(r => r.id));
    expect(cache.rows).toEqual([headers[0], readable, headers[1]]);
  });

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
