import { afterEach, describe, expect, it, vi } from 'vitest';
import { nextTick, ref, shallowRef } from 'vue';
import { createFocusTranscript } from '../../../src/focus/focusTranscript';
import { appendTranscriptDelta } from '../../../src/focus/transcriptItems';
import { decodeFocusTranscriptPage } from '../../../src/focus/httpResponseDecoder';
import type { FocusThreadSnapshot, FocusTranscriptPage, FocusTranscriptQuery, FocusThreadDeltaDetail } from '../../../src/focus/types';
import type { ChatTurn } from '../../../src/types';
import { FocusApiError } from '../../../src/focus/types';
import { snapshot as controlSnapshot } from './mutation-actions-test-support';

function snapshot(): FocusThreadSnapshot {
  const result = controlSnapshot();
  return { ...result, thread: { ...result.thread, id: 'thread-1', history_mode: 'paginated' } };
}

const owners: ReturnType<typeof createFocusTranscript>[] = [];
afterEach(() => { owners.splice(0).forEach(owner => owner.dispose()); vi.useRealTimers(); });
const row = (n: number, text = String(n)): ChatTurn => ({
  id: `turn-1:item:item-${n}:0`, rawTurnId: 'turn-1', itemId: `item-${n}`,
  role: 'assistant', no: 0, text, blocks: [{ kind: 'text', text, itemId: `item-${n}` }],
});
const page = (turns = [row(1)], options: Partial<FocusTranscriptPage> = {}): FocusTranscriptPage => ({
  view: 'transcript', target_pending: false, thread_id: 'thread-1', turn_id: null, runtime_epoch: 'epoch-1', revision: 1,
  turns, older_cursor: 'older', newer_cursor: 'newer', full_text: null, ...options,
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function harness(initial = page()) {
  const state = shallowRef<FocusThreadSnapshot | null>(snapshot());
  const threadId = ref('thread-1');
  const read = vi.fn(async (_threadId: string, _query?: FocusTranscriptQuery, _signal?: AbortSignal) => initial);
  const owner = createFocusTranscript({ api: { readTranscriptWindow: read }, snapshot: state,
    activeThreadId: threadId, isDisposed: () => false });
  owners.push(owner);
  const event = (revision: number, detail: FocusThreadDeltaDetail) => owner.handleDelta({
    type: 'thread_delta', runtime_epoch: 'epoch-1', revision,
    thread_id: 'thread-1', reason: detail.method, detail: { ...detail },
  }, detail);
  return { owner, read, state, threadId, event };
}
const settle = async () => { await nextTick(); await Promise.resolve(); await nextTick(); };

describe('bounded transcript owner', () => {
  it('does not restart body reads when control-only events replace the same snapshot revision', async () => {
    const h = harness(); await settle();
    h.state.value = { ...h.state.value!, active_turn_status: 'inProgress' };
    await settle();
    expect(h.read).toHaveBeenCalledOnce();
  });
  it('loads body independently and pages within the same giant turn without accumulating history', async () => {
    const h = harness(page(Array.from({ length: 40 }, (_, i) => row(i + 100))));
    await settle();
    expect(h.owner.turns.value).toHaveLength(40);
    h.read.mockResolvedValue(page(Array.from({ length: 40 }, (_, i) => row(i + 60)), { older_cursor: 'older-2' }));
    expect(await h.owner.older()).toBe(true);
    expect(h.owner.turns.value[0]?.itemId).toBe('item-60');
    expect(h.owner.turns.value).toHaveLength(40);
    expect(h.owner.historical.value).toBe(true);
    expect(h.read).toHaveBeenLastCalledWith('thread-1', { cursor: 'older', direction: 'desc' }, expect.any(AbortSignal));
    h.event(2, { method: 'item/started', item_turns: [row(999)] });
    expect(h.owner.turns.value.some(turn => turn.itemId === 'item-999')).toBe(false);
  });

  it('replays only post-response deltas and preserves coalesced item order', async () => {
    const h = harness(); await settle();
    const pending = deferred<FocusTranscriptPage>();
    h.read.mockReturnValueOnce(pending.promise);
    const loading = h.owner.load();
    h.event(1, { method: 'item/agentMessage/delta', stream_delta: { kind: 'text', turn_id: 'turn-1', item_id: 'item-1', delta: 'duplicate' } });
    h.event(2, { method: 'item/agentMessage/delta', stream_delta: { kind: 'text', turn_id: 'turn-1', item_id: 'item-1', delta: 'new' } });
    pending.resolve(page()); await loading;
    expect(h.owner.turns.value[0]?.text).toBe('1new');
    h.event(3, { method: 'item/completed', item_turns: [row(0), row(2)], item_order: [row(0).id, row(1).id, row(2).id] });
    expect(h.owner.turns.value.map(turn => turn.itemId)).toEqual(['item-0', 'item-1', 'item-2']);
  });

  it('rejects stale navigation and aborts old reads after a thread change', async () => {
    const h = harness(); await settle();
    const pending = deferred<FocusTranscriptPage>(); h.read.mockReturnValueOnce(pending.promise);
    const request = h.owner.older();
    const signal = h.read.mock.calls.at(-1)?.[2] as AbortSignal | undefined;
    h.threadId.value = 'thread-2'; await settle();
    expect(signal?.aborted).toBe(true);
    pending.resolve(page([row(999)])); expect(await request).toBe(false);
    expect(h.owner.turns.value).toEqual([]);
  });

  it('bounds live items and buffering, then stops automatic recovery after three attempts', async () => {
    vi.useFakeTimers();
    const h = harness(); await settle();
    const pending = deferred<FocusTranscriptPage>(); h.read.mockReturnValueOnce(pending.promise);
    const loading = h.owner.load();
    for (let i = 0; i < 400; i++) h.event(i + 2, { method: 'item/started', item_turns: [row(i, 'x'.repeat(4000))] });
    h.read.mockRejectedValue(new Error('offline'));
    pending.resolve(page()); expect(await loading).toBe(false);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.read).toHaveBeenCalledTimes(5); // initial + manual + three recoveries
    expect(h.owner.turns.value.length).toBeLessThanOrEqual(80);
    expect(h.owner.error.value).toBe('offline');
  });

  it('full content is read by exact item identity and discarded on scope changes', async () => {
    const h = harness(); await settle();
    const full = '完整\n'.repeat(20_000);
    h.read.mockResolvedValue(page([], { turn_id: 'turn-1', full_text: full }));
    await h.owner.openFull(row(1)); expect(h.owner.fullText.value).toBe(full);
    expect(h.read).toHaveBeenLastCalledWith('thread-1', { turn_id: 'turn-1', item_id: 'item-1', full: true }, expect.any(AbortSignal));
    h.state.value = { ...snapshot(), runtime_epoch: 'epoch-2' }; await settle();
    expect(h.owner.fullText.value).toBeNull();
  });

  it('rereads a source page with its string locator and retries a stale full read once', async () => {
    const h = harness(); await settle();
    h.read.mockRejectedValueOnce(new FocusApiError('retry', { status: 409, code: 'stale_thread_read' }))
      .mockResolvedValueOnce(page([], { turn_id: 'turn-1', full_text: '**complete**' }));
    await h.owner.openFull({ ...row(1), sourceCursor: 'opaque source page' });
    expect(h.owner.fullText.value).toBe('**complete**');
    expect(h.read).toHaveBeenLastCalledWith('thread-1', {
      turn_id: 'turn-1', item_id: 'item-1', full: true, source_cursor: 'opaque source page',
    }, expect.any(AbortSignal));
  });

  it('follows bounded string-only target pages to the additional prompt, not the turn start', async () => {
    const h = harness(); await settle();
    h.read.mockResolvedValueOnce(page([], { turn_id: 'turn-1', target_pending: true, newer_cursor: 'scan-next' }))
      .mockResolvedValueOnce(page([row(99)], { turn_id: 'turn-1' }));
    expect(await h.owner.locate('turn-1', 'item-99')).toBe(row(99).id);
    expect(h.read).toHaveBeenLastCalledWith('thread-1', {
      turn_id: 'turn-1', item_id: 'item-99', direction: 'asc', cursor: 'scan-next',
    }, expect.any(AbortSignal));
    expect(h.owner.turns.value.map(turn => turn.itemId)).toEqual(['item-99']);
  });

  it('rejects mismatched or duplicate wire row identities and clips streams at a safe Unicode boundary', () => {
    expect(decodeFocusTranscriptPage(page())).not.toBeNull();
    expect(decodeFocusTranscriptPage(page([{ ...row(1), itemId: '' }]))).toBeNull();
    expect(decodeFocusTranscriptPage(page([row(1), row(1)]))).toBeNull();
    const tools: ChatTurn[] = Array.from({ length: 40 }, (_, i) => ({ ...row(i), blocks: [],
      tools: [{ id: `tool-${i}`, name: 'Tool', arg: '', status: 'ok', output: ['one'] }] }));
    expect(decodeFocusTranscriptPage(page(tools))?.turns).toHaveLength(40);
    const result = appendTranscriptDelta(row(1, 'x'.repeat(16_383)), {
      kind: 'text', turn_id: 'turn-1', item_id: 'item-1', delta: '😀tail',
    });
    expect(result?.contentDeferred).toBe(true);
    expect(result?.text).toBe('x'.repeat(16_383));
  });
});
