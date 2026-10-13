import { describe, expect, it, vi } from 'vitest';
import { createExportTurnSelection } from '../src/focus/exportTurnSelection';
import { decodeFocusExportTurnPage } from '../src/focus/httpResponseDecoder';
import type { FocusExportTurn, FocusExportTurnPage } from '../src/focus/types';

const row = (id: string, status: FocusExportTurn['status'] = 'completed'): FocusExportTurn => ({ turn_id: id, status, prompt: `Question ${id}`, answer: `Reply ${id}` });
const page = (turns: FocusExportTurn[], cursor: string | null = null): FocusExportTurnPage => ({ thread_id: 'one', turns, next_cursor: cursor });
function harness() {
  const listExportTurns = vi.fn(async (): Promise<FocusExportTurnPage> => page([row('new')], 'older'));
  const previewExportTurn = vi.fn(async () => new Blob(['# Q&A\nFull answer']));
  return { listExportTurns, previewExportTurn, state: createExportTurnSelection({ listExportTurns, previewExportTurn }) };
}

describe('export turn selection', () => {
  it('keeps selections across pages and opening the same target, never selects unfinished turns', async () => {
    const h = harness(); h.state.open('one');
    await vi.waitFor(() => expect(h.state.rows.value).toHaveLength(1));
    h.state.toggle(row('new')); h.state.toggle(row('running', 'inProgress'));
    h.listExportTurns.mockResolvedValueOnce(page([row('old'), row('broken', 'failed')]));
    await h.state.load(1); h.state.selectPage();
    expect(h.state.selected.value).toEqual(['new', 'old']);
    expect(h.state.pageIndex.value).toBe(1);
    expect(h.state.hasNext.value).toBe(false);
    h.state.open('one');
    expect(h.listExportTurns).toHaveBeenCalledTimes(2);
    h.state.clear(); expect(h.state.selected.value).toEqual([]);
  });

  it('cancels on dialog/thread changes and ignores stale pages and previews', async () => {
    const h = harness(); let finish!: (page: FocusExportTurnPage) => void;
    h.listExportTurns.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    h.state.open('one');
    const signal = h.listExportTurns.mock.calls[0]![2] as AbortSignal;
    h.state.reset(); expect(signal.aborted).toBe(true);
    finish(page([row('late')])); await Promise.resolve();
    expect(h.state.rows.value).toEqual([]);
    h.state.open('one'); await vi.waitFor(() => expect(h.state.rows.value).toHaveLength(1));
    let resolvePreview!: (blob: Blob) => void;
    h.previewExportTurn.mockImplementationOnce(() => new Promise(resolve => { resolvePreview = resolve; }));
    const preview = h.state.preview(row('new'));
    h.state.reset(); resolvePreview(new Blob(['Secret stale answer'])); await preview;
    expect(h.state.previewText.value).toBe(''); expect(h.state.selected.value).toEqual([]);
  });

  it('keeps a failed page retryable without changing prior selections', async () => {
    const h = harness(); h.state.open('one'); await vi.waitFor(() => expect(h.state.loading.value).toBe(false));
    h.state.toggle(row('new'));
    h.listExportTurns.mockRejectedValueOnce(new Error('Temporary failure'));
    await h.state.load(1);
    expect(h.state.error.value).toBe('Temporary failure'); expect(h.state.pageIndex.value).toBe(0);
    expect(h.state.selected.value).toEqual(['new']);
    h.listExportTurns.mockResolvedValueOnce(page([row('old')]));
    await h.state.load(); expect(h.state.rows.value[0]?.turn_id).toBe('old');
  });

  it('enforces the selection limit without silently partially selecting a page', async () => {
    const h = harness(); h.state.open('one'); await vi.waitFor(() => expect(h.state.loading.value).toBe(false));
    for (let n = 0; n < 100; n += 1) h.state.toggle(row(String(n)));
    expect(h.state.canSelectPage.value).toBe(false); h.state.selectPage(); h.state.toggle(row('extra'));
    expect(h.state.selected.value).toHaveLength(100);
    h.state.toggle(row('0')); h.state.toggle(row('extra')); expect(h.state.selected.value).toContain('extra');
  });

  it('rejects a repeated cursor or wrong target instead of showing unrelated turns', async () => {
    const h = harness(); h.state.open('one'); await vi.waitFor(() => expect(h.state.loading.value).toBe(false));
    await h.state.load(1); expect(h.state.error.value).not.toBe(''); expect(h.state.pageIndex.value).toBe(0);
    h.listExportTurns.mockResolvedValueOnce({ ...page([row('wrong')]), thread_id: 'other' });
    await h.state.load(1); expect(h.state.rows.value[0]?.turn_id).toBe('new');
  });

  it('previews a whole turn on demand and toggles it closed', async () => {
    const h = harness(); h.state.open('one'); await vi.waitFor(() => expect(h.state.loading.value).toBe(false));
    await h.state.preview(row('new'));
    expect(h.previewExportTurn).toHaveBeenCalledWith('one', 'new', expect.any(AbortSignal));
    expect(h.state.previewText.value).toContain('Full answer');
    await h.state.preview(row('new')); expect(h.state.previewText.value).toBe('');
  });
});

describe('export directory wire admission', () => {
  it('admits exact bounded rows and rejects malformed, duplicate and overlarge pages', () => {
    expect(decodeFocusExportTurnPage(page([row('a')]))).not.toBeNull();
    for (const bad of [
      { ...page([]), extra: true }, page([row('a'), row('a')]), page(Array.from({ length: 21 }, (_, n) => row(String(n)))),
      page([{ ...row('a'), status: 'unknown' } as unknown as FocusExportTurn]), { ...page([]), next_cursor: '' },
      page([{ ...row('a'), prompt: null } as unknown as FocusExportTurn]),
    ]) expect(decodeFocusExportTurnPage(bad)).toBeNull();
  });
});
