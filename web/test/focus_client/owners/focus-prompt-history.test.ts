import { afterEach, describe, expect, it, vi } from 'vitest';
import { ref, shallowRef } from 'vue';
import { createFocusPromptHistory } from '../../../src/focus/focusPromptHistory';
import { decodeFocusTranscriptPage } from '../../../src/focus/httpResponseDecoder';
import { snapshot } from './mutation-actions-test-support';
import type { FocusTranscriptPage, FocusTranscriptQuery } from '../../../src/focus/types';
import type { ChatTurn } from '../../../src/types';

const user = (turn: number, item: number): ChatTurn => ({
  id: `turn-${turn}:item:user-${item}:0`, rawTurnId: `turn-${turn}`, itemId: `user-${item}`,
  role: 'user', no: 0, text: `Prompt ${item}`,
});
const page = (turns: ChatTurn[], older: string | null = null): FocusTranscriptPage => ({
  runtime_epoch: 'epoch-1', revision: 1, thread_id: 'thread-1', turn_id: null,
  view: 'prompts', target_pending: false, turns, older_cursor: older, newer_cursor: null, full_text: null,
});
const owners: ReturnType<typeof createFocusPromptHistory>[] = [];
afterEach(() => { owners.splice(0).forEach(owner => owner.dispose()); vi.useRealTimers(); });
function harness(seed: ChatTurn[] = [user(1, 1), user(2, 3)]) {
  vi.useFakeTimers();
  const state = shallowRef({ ...snapshot(), runtime_epoch: 'epoch-1',
    thread: { ...snapshot().thread, id: 'thread-1', history_mode: 'paginated' as const }, turns: seed });
  const enabled = ref(true);
  const read = vi.fn(async (_id: string, _query?: FocusTranscriptQuery, _signal?: AbortSignal) => page([]));
  const reportError = vi.fn();
  const owner = createFocusPromptHistory({ api: { readTranscriptWindow: read }, snapshot: state,
    enabled, reportError, isDisposed: () => false });
  owners.push(owner);
  return { owner, state, enabled, read, reportError };
}

describe('paginated Prompt history', () => {
  it('does no body scanning until requested, then restores every steer in chronological order across empty pages', async () => {
    const h = harness();
    expect(h.read).not.toHaveBeenCalled();
    expect(h.owner.outline.value.map(p => p.itemId)).toEqual(['user-1', 'user-3']);
    h.read.mockResolvedValueOnce(page([user(2, 4)], 'one'))
      .mockResolvedValueOnce(page([], 'two'))
      .mockResolvedValueOnce(page([user(1, 1), user(1, 2), user(2, 3)]));
    h.owner.setVisible(true);
    await vi.runAllTimersAsync();
    expect(h.owner.outline.value.map(p => p.itemId)).toEqual(['user-1', 'user-2', 'user-3', 'user-4']);
    expect(h.owner.hasMore.value).toBe(false);
    expect(h.read.mock.calls.map(call => call[1])).toEqual([
      { view: 'prompts' }, { view: 'prompts', cursor: 'one' }, { view: 'prompts', cursor: 'two' },
    ]);
  });

  it('pauses on close, resumes the same cursor, and rejects late results after a thread change', async () => {
    const h = harness();
    let resolve!: (value: FocusTranscriptPage) => void;
    h.read.mockResolvedValueOnce(page([user(2, 4)], 'one'))
      .mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    h.owner.setVisible(true); await vi.runAllTimersAsync();
    const signal = h.read.mock.calls[1]?.[2];
    h.owner.setVisible(false);
    expect(signal?.aborted).toBe(true);
    resolve(page([user(1, 99)])); await vi.runAllTimersAsync();
    expect(h.owner.outline.value.some(p => p.itemId === 'user-99')).toBe(false);
    h.read.mockResolvedValueOnce(page([user(1, 2)]));
    h.owner.setVisible(true); await vi.runAllTimersAsync();
    expect(h.read.mock.calls[2]?.[1]).toEqual({ view: 'prompts', cursor: 'one' });
    h.owner.setVisible(false);
    h.enabled.value = false;
    h.state.value = { ...h.state.value, turns: [], thread: { ...h.state.value.thread, id: 'thread-2' } };
    expect(h.owner.outline.value).toEqual([]);
  });

  it('retains live additional messages after body eviction and deduplicates scanned copies', async () => {
    const h = harness();
    h.owner.handleDelta({ method: 'item/completed', item_turns: [user(2, 4)] });
    h.read.mockResolvedValueOnce(page([user(1, 1), user(1, 2), user(2, 3), user(2, 4)]));
    const loading = h.owner.loadMore(); await vi.runAllTimersAsync(); await loading;
    expect(h.owner.outline.value.map(p => p.itemId)).toEqual(['user-1', 'user-2', 'user-3', 'user-4']);
    h.state.value = { ...h.state.value, turns: [] };
    expect(h.owner.outline.value.map(p => p.itemId)).toEqual(['user-1', 'user-2', 'user-3', 'user-4']);
  });

  it('keeps partial results and allows retry when a page fails or repeats its cursor', async () => {
    const h = harness();
    h.read.mockResolvedValueOnce(page([user(2, 4)], 'same'))
      .mockResolvedValueOnce(page([], 'same'));
    const loading = h.owner.loadMore(); await vi.runAllTimersAsync(); await loading;
    expect(h.owner.error.value).toBe(true);
    expect(h.owner.hasMore.value).toBe(true);
    h.read.mockResolvedValueOnce(page([user(1, 2)]));
    const retry = h.owner.loadMore(); await vi.runAllTimersAsync(); await retry;
    expect(h.owner.error.value).toBe(false);
    expect(h.owner.outline.value).toHaveLength(4);
  });

  it('bounds the directory at 200 prompts and admits a full 100-title page', async () => {
    const h = harness([]);
    const titles = Array.from({ length: 100 }, (_, n) => user(1, n));
    expect(decodeFocusTranscriptPage(page(titles))).not.toBeNull();
    h.read.mockResolvedValueOnce(page(titles.map((_p, n) => user(1, n + 100)), 'one'))
      .mockResolvedValueOnce(page(titles, 'two'));
    const loading = h.owner.loadMore(); await vi.runAllTimersAsync(); await loading;
    expect(h.owner.outline.value).toHaveLength(200);
    expect(h.owner.truncated.value).toBe(true);
    expect(h.read).toHaveBeenCalledTimes(2);
  });
});
