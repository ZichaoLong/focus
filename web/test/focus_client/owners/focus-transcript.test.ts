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
  it('carries precise reply timing through deltas and a delayed start skeleton', async () => {
    const h = harness(); await settle();
    h.event(2, { method: 'item/agentMessage/delta', stream_delta: { kind: 'text', turn_id: 'turn-1', item_id: 'item-1', delta: 'stream' } });
    const reply = { state: 'generating' as const, startedAtMs: 120_000 };
    h.event(3, { method: 'item/started', item_turns: [{ ...row(1), reply }] });
    expect(h.owner.turns.value[0]).toMatchObject({ text: '1stream', reply, blocks: [{ reply }] });
    h.event(4, { method: 'item/agentMessage/delta', stream_delta: { kind: 'text', turn_id: 'turn-1', item_id: 'item-1', delta: 'more' } });
    expect(h.owner.turns.value[0]?.blocks?.[0]).toMatchObject({ reply });
    h.event(5, { method: 'turn/completed', turn_id: 'turn-1' });
    expect(h.owner.turns.value[0]?.reply).toEqual({ state: 'unknown', startedAtMs: 120_000 });
    expect(h.owner.turns.value[0]?.blocks?.[0]).toMatchObject({ reply: { state: 'unknown', startedAtMs: 120_000 } });
    const complete = { state: 'complete' as const, startedAtMs: 120_000, completedAtMs: 123_000 };
    const finished = { ...row(1), reply: complete };
    expect(decodeFocusTranscriptPage(page([finished]))?.turns[0]?.reply).toEqual(complete);
    for (const bad of [NaN, Infinity, -1, 1.2, '120', true, 8_640_000_000_000_001]) {
      expect(decodeFocusTranscriptPage(page([{ ...finished, reply: { ...complete, startedAtMs: bad } } as ChatTurn]))).toBeNull();
    }
  });

  it('does not restart body reads when control-only events replace the same snapshot revision', async () => {
    const h = harness(); await settle();
    h.state.value = { ...h.state.value!, active_turn_status: 'inProgress' };
    await settle();
    expect(h.read).toHaveBeenCalledOnce();
  });
  it('loads body independently and retains adjacent pages while browsing a giant turn', async () => {
    const h = harness(page(Array.from({ length: 40 }, (_, i) => row(i + 100))));
    await settle();
    expect(h.owner.turns.value).toHaveLength(40);
    h.read.mockResolvedValue(page(Array.from({ length: 40 }, (_, i) => row(i + 60)), { older_cursor: 'older-2' }));
    expect(await h.owner.older()).toBe(true);
    expect(h.owner.turns.value[0]?.itemId).toBe('item-60');
    expect(h.owner.turns.value).toHaveLength(80);
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

  it('reads only the selected item and retries a stale detail read once', async () => {
    const h = harness(); await settle();
    h.read.mockRejectedValueOnce(new FocusApiError('retry', { status: 409, code: 'stale_thread_read' }))
      .mockResolvedValueOnce(page([], { turn_id: 'turn-1', full_text: '**complete**' }));
    await h.owner.openFull({ ...row(1), sourceCursor: 'opaque source page' });
    expect(h.owner.fullText.value).toBe('**complete**');
    expect(h.read).toHaveBeenLastCalledWith('thread-1', {
      turn_id: 'turn-1', item_id: 'item-1', full: true,
    }, expect.any(AbortSignal));
  });

  it('keeps the selected tool identity through loading and failure without accepting stale detail', async () => {
    const h = harness(); await settle();
    const tool = { id: 'tool', name: 'MCP · research/search', arg: '{"query":"needle"}', status: 'ok' as const };
    const first = deferred<FocusTranscriptPage>();
    h.read.mockReturnValueOnce(first.promise);
    const pending = h.owner.openFull({ ...row(1), tools: [tool], contentDeferred: true });
    expect(h.owner.fullTool.value).toEqual({ name: tool.name, arg: tool.arg, status: tool.status });
    expect(h.owner.fullLoading.value).toBe(true);
    const signal = h.read.mock.calls.at(-1)?.[2];
    h.read.mockRejectedValueOnce(new Error('offline'));
    await h.owner.openFull({ ...row(2), tools: [{ ...tool, name: 'Another tool' }] });
    expect(signal?.aborted).toBe(true);
    first.resolve(page([], { turn_id: 'turn-1', full_text: 'wrong tool' })); await pending;
    expect(h.owner.fullText.value).toBeNull();
    expect(h.owner.fullTool.value?.name).toBe('Another tool');
    expect(h.owner.fullError.value).toBe('offline');
    h.owner.closeFull();
    expect(h.owner.fullTool.value).toBeNull();
    expect(h.owner.fullError.value).toBe('');

    h.read.mockResolvedValue(page([], { turn_id: 'turn-1', full_text: 'source' }));
    await h.owner.openFull({ ...row(1), tools: [tool] });
    await h.owner.openFull(row(2));
    expect(h.owner.fullTool.value).toBeNull();
    expect(h.owner.fullText.value).toBe('source');
    await h.owner.openFull({ ...row(1), tools: [tool] });
    h.threadId.value = 'thread-2';
    expect(h.owner.fullTool.value).toBeNull();
    expect(h.owner.fullText.value).toBeNull();
  });

  it('reads tool details only on request and refreshes an opened running tool once it completes', async () => {
    const h = harness(); await settle();
    const tool = { id: 'tool', name: 'Shell', arg: 'job', status: 'running' as const, output: [] };
    const running = { ...row(2, ''), contentDeferred: true, tools: [tool] };
    h.event(2, { method: 'item/started', item_turns: [running] });
    expect(h.read).toHaveBeenCalledTimes(1);
    h.read.mockResolvedValue(page([], { turn_id: 'turn-1', full_text: 'running record' }));
    await h.owner.openFull(running);
    expect(h.owner.fullText.value).toBe('running record');
    h.read.mockResolvedValue(page([], { turn_id: 'turn-1', full_text: 'complete record' }));
    h.event(3, { method: 'item/completed', item_turns: [{ ...running, tools: [{ ...tool, status: 'ok' }] }] });
    await settle();
    expect(h.owner.fullText.value).toBe('complete record');
    expect(h.read).toHaveBeenCalledTimes(3);
    h.owner.closeFull();
    h.owner.refreshFull();
    expect(h.read).toHaveBeenCalledTimes(3);
  });

  it('appends complete reasoning fragments past the old limit independently from other items', () => {
    const text = '思考😀'.repeat(10_000);
    let current = appendTranscriptDelta(undefined, { kind: 'thinking', turn_id: 'turn-1', item_id: 'reason', delta: text });
    current = appendTranscriptDelta(current!, { kind: 'thinking_separator', turn_id: 'turn-1', item_id: 'reason', delta: '' });
    current = appendTranscriptDelta(current!, { kind: 'thinking', turn_id: 'turn-1', item_id: 'reason', delta: '最后一段' });
    expect(current?.blocks).toEqual([{ kind: 'thinking', itemId: 'reason', thinking: text + '\n\n最后一段' }]);
    expect(current?.contentDeferred).toBeUndefined();
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

  it('rejects mismatched or duplicate wire row identities and keeps every streamed character', () => {
    expect(decodeFocusTranscriptPage(page())).not.toBeNull();
    expect(decodeFocusTranscriptPage(page([{ ...row(1), itemId: '' }]))).toBeNull();
    expect(decodeFocusTranscriptPage(page([row(1), row(1)]))).toBeNull();
    const tools: ChatTurn[] = Array.from({ length: 40 }, (_, i) => {
      const tool = { id: `tool-${i}`, name: 'Tool', arg: '', status: 'ok' as const, output: [] };
      return { ...row(i, ''), contentDeferred: true, tools: [tool], blocks: [{ kind: 'tool', tool }] };
    });
    expect(decodeFocusTranscriptPage(page(tools))?.turns).toHaveLength(40);
    expect(decodeFocusTranscriptPage(page([{ ...row(1), contentDeferred: true }]))).toBeNull();
    expect(decodeFocusTranscriptPage(page([{ ...tools[0]!, tools: [{ ...tools[0]!.tools![0]!, output: ['leak'] }] }]))).toBeNull();
    const result = appendTranscriptDelta(row(1, 'x'.repeat(16_383)), {
      kind: 'text', turn_id: 'turn-1', item_id: 'item-1', delta: '😀tail',
    });
    expect(result?.contentDeferred).toBeUndefined();
    expect(result?.text).toBe('x'.repeat(16_383) + '😀tail');
  });

  it('admits complete long prose through the shared HTTP and live wire boundary', () => {
    const text = '完整正文😀\n'.repeat(12_000) + '最后一行';
    const reply = row(1, text);
    const prompt = { ...row(2, text), role: 'user' as const, blocks: [] };
    const reasoning: ChatTurn = { ...row(3, ''), blocks: [{ kind: 'thinking', itemId: 'item-3', thinking: text }] };
    const decoded = decodeFocusTranscriptPage(page([prompt, reasoning, reply]));
    expect(decoded).not.toBeNull();
    expect(decoded?.turns.map(turn => turn.text)).toEqual([text, '', text]);
    expect(decoded?.turns[1]?.blocks).toEqual(reasoning.blocks);
  });

  it('continues globally after locating a steer and reuses cached pages on reversal', async () => {
    const h = harness(); await settle();
    const nextTurn = { ...row(100), rawTurnId: 'turn-2', id: 'turn-2:item:item-100:0' };
    h.read.mockResolvedValueOnce(page([row(99), nextTurn], { turn_id: 'turn-1', newer_cursor: 'forward' }));
    expect(await h.owner.locate('turn-1', 'item-99')).toBe(row(99).id);
    h.read.mockResolvedValueOnce(page([row(59), row(98)], { older_cursor: 'back' }));
    expect(await h.owner.older()).toBe(true);
    expect(h.read).toHaveBeenLastCalledWith('thread-1', { cursor: 'older', direction: 'desc' }, expect.any(AbortSignal));
    h.owner.updateViewport(row(99).id, false);
    expect(h.owner.turns.value.map(row => row.itemId)).toEqual(['item-59', 'item-98', 'item-99', 'item-100']);
    expect(h.read).toHaveBeenCalledTimes(3);
    h.read.mockResolvedValueOnce(page([nextTurn, row(101)], { newer_cursor: null }));
    expect(await h.owner.newer()).toBe(true);
    expect(h.read).toHaveBeenLastCalledWith('thread-1', { cursor: 'forward', direction: 'asc' }, expect.any(AbortSignal));
    expect(h.owner.hasNewer.value).toBe(false);
    h.owner.updateViewport(row(101).id, true);
    expect(h.owner.historical.value).toBe(false);
  });

  it('keeps a single page flight, retains content on failure, and only retries on request', async () => {
    const h = harness(); await settle();
    const pending = deferred<FocusTranscriptPage>(); h.read.mockReturnValueOnce(pending.promise);
    const loading = h.owner.older();
    expect(await h.owner.older()).toBe(false);
    expect(await h.owner.newer()).toBe(false);
    expect(h.read).toHaveBeenCalledTimes(2);
    pending.resolve(page([row(0)], { older_cursor: 'next' })); await loading;
    h.read.mockRejectedValueOnce(new Error('slow network'));
    expect(await h.owner.older()).toBe(false);
    expect(h.owner.turns.value.map(row => row.itemId)).toEqual(['item-0', 'item-1']);
    await settle(); expect(h.read).toHaveBeenCalledTimes(3);
  });

  it('does not pull history to the live tail, and fetches unseen live rows before following', async () => {
    const h = harness(); await settle();
    h.owner.updateViewport(row(1).id, false);
    h.event(2, { method: 'item/started', item_turns: [row(2)] });
    expect(h.owner.turns.value.map(row => row.itemId)).toEqual(['item-1']);
    expect(h.owner.hasNewer.value).toBe(true);
    h.owner.updateViewport(row(1).id, true);
    expect(h.owner.historical.value).toBe(true);
    h.read.mockResolvedValueOnce(page([row(1), row(2)], { newer_cursor: null, revision: 2 }));
    await h.owner.newer();
    h.owner.updateViewport(row(2).id, true);
    h.event(3, { method: 'item/started', item_turns: [row(3)] });
    expect(h.owner.turns.value.map(row => row.itemId)).toEqual(['item-1', 'item-2', 'item-3']);
  });

  it('ignores a delayed head refresh when the user starts browsing', async () => {
    const h = harness(); await settle();
    const pending = deferred<FocusTranscriptPage>(); h.read.mockReturnValueOnce(pending.promise);
    const loading = h.owner.load();
    h.owner.updateViewport(row(1).id, false);
    pending.resolve(page([row(99)])); expect(await loading).toBe(false);
    expect(h.owner.turns.value.map(row => row.itemId)).toEqual(['item-1']);
  });
});
