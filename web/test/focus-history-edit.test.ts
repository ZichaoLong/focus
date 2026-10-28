import { describe, expect, it, vi } from 'vitest';
import { decodeFocusHistoryEditPrompt } from '../src/focus/httpResponseDecoder';
import { deferred, harness, installMutationActionsTestHooks } from './focus_client/owners/mutation-actions-test-support';

describe('native Web history edit', () => {
  installMutationActionsTestHooks();
  const target = { turn_id: 'original-turn', item_id: 'original-item' };

  it('retains the verified original before one revert, without creating a branch or sending', async () => {
    const h = harness(), retain = vi.fn();
    h.api.revertThread.mockImplementation(async (thread_id) => {
      expect(retain).toHaveBeenCalledExactlyOnceWith({ thread_id, ...target, text: 'Original prompt' });
      return { accepted: true, thread_id };
    });
    expect(await h.actions.editPrompt('thread-a', target, retain)).toBe(true);
    expect(h.api.readHistoryEditPrompt).toHaveBeenCalledExactlyOnceWith('thread-a', target);
    expect(h.api.revertThread).toHaveBeenCalledExactlyOnceWith('thread-a', target.turn_id);
    expect(h.api.forkThread).not.toHaveBeenCalled();
    expect(h.api.submitPrompt).not.toHaveBeenCalled();
    expect(h.refreshThreads).not.toHaveBeenCalled();
  });

  it('does not revert when original preparation fails or returns another identity', async () => {
    const h = harness(), retain = vi.fn();
    h.api.readHistoryEditPrompt.mockRejectedValueOnce(new Error('Original unavailable'));
    expect(await h.actions.editPrompt('thread-a', target, retain)).toBe(false);
    h.api.readHistoryEditPrompt.mockResolvedValueOnce({ thread_id: 'other', ...target, text: 'Wrong original' });
    expect(await h.actions.editPrompt('thread-a', target, retain)).toBe(false);
    expect(retain).not.toHaveBeenCalled();
    expect(h.api.revertThread).not.toHaveBeenCalled();
  });

  it('keeps the full original after transport loss and never automatically repeats the mutation', async () => {
    const h = harness(), retain = vi.fn();
    const result = deferred<never>();
    h.api.revertThread.mockReturnValueOnce(result.promise);
    const editing = h.actions.editPrompt('thread-a', target, retain);
    await Promise.resolve();
    expect(await h.actions.editPrompt('thread-a', target, retain)).toBe(false);
    result.reject(new Error('Response lost'));
    expect(await editing).toBe(false);
    expect(retain).toHaveBeenCalledOnce();
    expect(h.api.revertThread).toHaveBeenCalledOnce();
    expect(h.reportError.mock.calls[0]![0].message).toContain('Revert result could not be confirmed');
  });

  it('rejects incomplete or empty original-prompt responses', () => {
    const original = { thread_id: 'thread-a', ...target, text: 'Original' };
    expect(decodeFocusHistoryEditPrompt(original)).toEqual(original);
    expect(decodeFocusHistoryEditPrompt({ ...original, thread_id: undefined })).toBeNull();
    expect(decodeFocusHistoryEditPrompt({ ...original, text: '' })).toBeNull();
  });
});
