import { describe, expect, it, vi } from 'vitest';
import { decodeFocusForkResult } from '../src/focus/httpResponseDecoder';
import type { FocusForkResult } from '../src/focus/types';
import { useFocusWebClient } from '../src/focus/useFocusWebClient';
import { deferred, harness, installMutationActionsTestHooks } from './focus_client/owners/mutation-actions-test-support';
import { FakeApi, installFocusClientTestHooks, snapshot, thread } from './focus_client/support';

describe('persistent thread fork', () => {
  installMutationActionsTestHooks();

  it('creates once and refreshes the list without submitting a prompt', async () => {
    const h = harness();
    expect(await h.actions.forkThread('thread-a')).toEqual({
      accepted: true, thread_id: 'fork-a', source_thread_id: 'thread-a', name_warning: '',
    });
    expect(h.api.forkThread).toHaveBeenCalledExactlyOnceWith('thread-a');
    expect(h.refreshThreads).toHaveBeenCalledOnce();
    expect(h.api.startThread).not.toHaveBeenCalled();
    expect(h.api.submitPrompt).not.toHaveBeenCalled();
  });

  it('does not duplicate an in-flight fork or replay an unknown result', async () => {
    const h = harness();
    const request = deferred<FocusForkResult>();
    h.api.forkThread.mockReturnValueOnce(request.promise);
    const first = h.actions.forkThread('thread-a');
    expect(await h.actions.forkThread('thread-a')).toBeNull();
    request.reject(new Error('Fork result unknown; refresh the session list.'));
    expect(await first).toBeNull();
    expect(h.api.forkThread).toHaveBeenCalledOnce();
    expect(h.reportError).toHaveBeenCalledOnce();
    expect(h.activeThreadId.value).toBe('thread-a');
  });

  it('keeps the known branch available to open when list refresh fails', async () => {
    const h = harness();
    h.refreshThreads.mockRejectedValueOnce(new Error('List unavailable'));
    h.api.forkThread.mockResolvedValueOnce({
      accepted: true, thread_id: 'fork-a', source_thread_id: 'thread-a', name_warning: 'Rename failed.',
    });
    expect(await h.actions.forkThread('thread-a')).toEqual({
      accepted: true, thread_id: 'fork-a', source_thread_id: 'thread-a', name_warning: 'Rename failed.',
    });
    expect(h.api.forkThread).toHaveBeenCalledOnce();
    expect(h.reportError).toHaveBeenCalledOnce();
  });

  it('rejects misdirected responses and rejects invalid wire results', async () => {
    const h = harness();
    h.api.forkThread.mockResolvedValue({ accepted: true, thread_id: 'fork-b', source_thread_id: 'other', name_warning: '' });
    expect(await h.actions.forkThread('thread-a')).toBeNull();
    const valid = { accepted: true, thread_id: 'fork', source_thread_id: 'parent', name_warning: '' };
    expect(decodeFocusForkResult({ ...valid, thread_id: 'parent' })).toBeNull();
    expect(decodeFocusForkResult({ ...valid, accepted: false })).toBeNull();
    expect(decodeFocusForkResult({ ...valid, name_warning: undefined })).toBeNull();
    expect(decodeFocusForkResult({ ...valid, name_warning: 42 })).toBeNull();
    expect(decodeFocusForkResult(valid)).toEqual(valid);
  });
});

describe('fork navigation and naming warnings', () => {
  installFocusClientTestHooks();

  const warning = 'Branch fork-a was created, but its automatic name could not be confirmed. You can rename it manually.';

  async function clientHarness(nameWarning = '', forkGate = Promise.resolve()) {
    const branch = { ...thread(), id: 'fork-a', name: 'Demo · 分支 fork-a', title: 'Demo · 分支 fork-a' };
    const api = Object.assign(new FakeApi(), {
      forkThread: vi.fn(async (_sourceId: string): Promise<FocusForkResult> => {
        await forkGate;
        api.threads.push(branch);
        return { accepted: true, thread_id: branch.id, source_thread_id: 'thread-1', name_warning: nameWarning };
      }),
    });
    api.threads.push({ ...thread(), id: 'other' });
    const read = api.readThread.bind(api);
    vi.spyOn(api, 'readThread').mockImplementation(async (id = 'thread-1') => {
      api.currentSnapshot = { ...snapshot('none', id), thread: api.threads.find(t => t.id === id)! };
      return read(id);
    });
    const client = useFocusWebClient(api);
    await client.load();
    api.emit({ type: 'hello', runtime_epoch: 'epoch-1', revision: 0 });
    await vi.advanceTimersByTimeAsync(0);
    expect(client.connection.value).toBe('connected');
    return { api, client, branch };
  }

  it.each(['', warning])('opens the created branch and retains the naming outcome: %s', async (nameWarning) => {
    const { api, client } = await clientHarness(nameWarning);
    await client.forkThread('thread-1');
    expect(client.activeThreadId.value).toBe('fork-a');
    expect(client.snapshot.value?.thread.id).toBe('fork-a');
    expect(client.errorMessage.value).toBe(nameWarning);
    expect(api.forkThread).toHaveBeenCalledExactlyOnceWith('thread-1');
    client.dispose();
  });

  it('keeps a newer selection while still presenting the branch naming warning', async () => {
    const gate = deferred<void>();
    const { api, client } = await clientHarness(warning, gate.promise);
    const forking = client.forkThread('thread-1');
    await client.selectThread('other');
    gate.resolve();
    await forking;
    expect(client.activeThreadId.value).toBe('other');
    expect(client.snapshot.value?.thread.id).toBe('other');
    expect(client.errorMessage.value).toBe(warning);
    expect(api.forkThread).toHaveBeenCalledOnce();
    client.dispose();
  });

  it('preserves an opening error alongside the naming warning without repeating fork', async () => {
    const { api, client } = await clientHarness(warning);
    const read = vi.mocked(api.readThread).getMockImplementation()!;
    vi.mocked(api.readThread).mockImplementation(async (id = 'thread-1') => {
      if (id === 'fork-a') throw new Error('Branch read unavailable');
      return read(id);
    });
    await client.forkThread('thread-1');
    expect(client.errorMessage.value).toContain('Branch read unavailable');
    expect(client.errorMessage.value).toContain(warning);
    expect(api.forkThread).toHaveBeenCalledOnce();
    client.dispose();
  });

  it('does not publish a late warning or navigate after disposal', async () => {
    const gate = deferred<void>();
    const { client } = await clientHarness(warning, gate.promise);
    const forking = client.forkThread('thread-1');
    client.dispose();
    gate.resolve();
    await forking;
    expect(client.errorMessage.value).toBe('');
    expect(client.activeThreadId.value).toBe('thread-1');
  });
});
