import { describe, expect, it } from 'vitest';
import { decodeFocusForkResult } from '../src/focus/httpResponseDecoder';
import { deferred, harness, installMutationActionsTestHooks } from './focus_client/owners/mutation-actions-test-support';

installMutationActionsTestHooks();

describe('persistent thread fork', () => {
  it('creates once and refreshes the list without submitting a prompt', async () => {
    const h = harness();
    expect(await h.actions.forkThread('thread-a')).toBe('fork-a');
    expect(h.api.forkThread).toHaveBeenCalledExactlyOnceWith('thread-a');
    expect(h.refreshThreads).toHaveBeenCalledOnce();
    expect(h.api.startThread).not.toHaveBeenCalled();
    expect(h.api.submitPrompt).not.toHaveBeenCalled();
  });

  it('does not duplicate an in-flight fork or replay an unknown result', async () => {
    const h = harness();
    const request = deferred<{ accepted: true; thread_id: string; source_thread_id: string }>();
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
    expect(await h.actions.forkThread('thread-a')).toBe('fork-a');
    expect(h.api.forkThread).toHaveBeenCalledOnce();
    expect(h.reportError).toHaveBeenCalledOnce();
  });

  it('rejects misdirected responses and rejects invalid wire results', async () => {
    const h = harness();
    h.api.forkThread.mockResolvedValue({ accepted: true, thread_id: 'fork-b', source_thread_id: 'other' });
    expect(await h.actions.forkThread('thread-a')).toBeNull();
    expect(decodeFocusForkResult({ accepted: true, thread_id: 'parent', source_thread_id: 'parent' })).toBeNull();
    expect(decodeFocusForkResult({ accepted: false, thread_id: 'fork', source_thread_id: 'parent' })).toBeNull();
    expect(decodeFocusForkResult({ accepted: true, thread_id: 'fork', source_thread_id: 'parent' })).toEqual({ accepted: true, thread_id: 'fork', source_thread_id: 'parent' });
  });
});
