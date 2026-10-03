import { describe, expect, it, vi } from 'vitest';
import { createFocusReplyContent } from '../../../src/focus/focusReplyContent';
import type { ChatTurn } from '../../../src/types';

const turn = (id = 'reply'): ChatTurn => ({ id, itemId: id, rawTurnId: 'turn', role: 'assistant',
  no: 0, text: 'preview', contentDeferred: true, reply: { state: 'complete' } });
const settle = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };
function deferred() {
  let resolve!: (text: string) => void;
  const promise = new Promise<string>(done => { resolve = done; });
  return { promise, resolve };
}

describe('inline reply source reads', () => {
  it('shares a read, serializes nearby replies, and retains exact source for copying', async () => {
    const first = deferred(); const read = vi.fn(async () => 'second').mockReturnValueOnce(first.promise);
    const owner = createFocusReplyContent({ read });
    const a = owner.acquire(turn()); const b = owner.acquire(turn()); const c = owner.acquire(turn('another'));
    expect(read).toHaveBeenCalledOnce(); expect(a.state).toBe(b.state);
    first.resolve('**complete**\n\n| a | b |'); await settle();
    expect(read).toHaveBeenCalledTimes(2);
    expect(a.state.value.text).toBe('**complete**\n\n| a | b |');
    expect(c.state.value.text).toBe('second');
    a.release(); b.release(); c.release();
    const cached = owner.acquire(turn()); expect(read).toHaveBeenCalledTimes(2); cached.release();
  });

  it('cancels offscreen reads and rejects late content after a scope reset', async () => {
    const first = deferred(); const read = vi.fn((_turn: ChatTurn, _signal: AbortSignal) => first.promise);
    const owner = createFocusReplyContent({ read });
    const lease = owner.acquire(turn()); lease.release();
    expect(read.mock.calls[0]![1].aborted).toBe(true);
    owner.reset(); first.resolve('stale'); await settle();
    expect(lease.state.value.text).toBeNull();
    read.mockResolvedValue('new');
    const next = owner.acquire(turn()); await settle();
    expect(next.state.value.text).toBe('new'); owner.reset();
    expect(next.state.value.text).toBeNull(); next.release();
  });

  it('retains an error without automatic retries and allows an explicit retry', async () => {
    const read = vi.fn(async () => 'complete').mockRejectedValueOnce(new Error('offline'));
    const owner = createFocusReplyContent({ read });
    const lease = owner.acquire(turn()); await settle();
    expect(lease.state.value.error).toBe('offline'); expect(read).toHaveBeenCalledOnce();
    lease.release(); const reopened = owner.acquire(turn()); await settle();
    expect(read).toHaveBeenCalledOnce(); reopened.retry(); await settle();
    expect(reopened.state.value.text).toBe('complete'); reopened.release();
  });

  it('bounds inactive caches by both item count and bytes, allowing only active oversized source residency', async () => {
    const read = vi.fn(async () => 'x'); const owner = createFocusReplyContent({ read });
    for (let i = 0; i < 6; i += 1) {
      const lease = owner.acquire(turn(String(i))); await settle(); lease.release();
    }
    const old = owner.acquire(turn('0')); await settle(); old.release(); expect(read).toHaveBeenCalledTimes(7);
    read.mockResolvedValue('x'.repeat(3 * 1024 * 1024));
    const huge = owner.acquire(turn('huge')); await settle(); expect(huge.state.value.text?.length).toBe(3 * 1024 * 1024);
    huge.release(); const again = owner.acquire(turn('huge')); await settle();
    expect(read).toHaveBeenCalledTimes(9); again.release();
  });

  it('rereads a live reply when completion arrives and refuses tool auto-reads', async () => {
    const read = vi.fn(async () => 'partial'); const owner = createFocusReplyContent({ read });
    const partial = owner.acquire({ ...turn(), reply: { state: 'unknown' } }); await settle(); partial.release();
    read.mockResolvedValue('full'); const complete = owner.acquire(turn()); await settle();
    expect(complete.state.value.text).toBe('full'); expect(read).toHaveBeenCalledTimes(2); complete.release();
    expect(() => owner.acquire({ ...turn(), reply: undefined })).toThrow();
  });
});
