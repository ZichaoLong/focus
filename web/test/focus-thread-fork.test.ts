import { describe, expect, it, vi } from 'vitest';
import { decodeFocusForkResult } from '../src/focus/httpResponseDecoder';
import type { FocusForkResult, FocusThreadSnapshot } from '../src/focus/types';
import { FocusApiError } from '../src/focus/types';
import { useFocusWebClient } from '../src/focus/useFocusWebClient';
import { deferred, harness, installMutationActionsTestHooks } from './focus_client/owners/mutation-actions-test-support';
import { FakeApi, installFocusClientTestHooks, snapshot, thread } from './focus_client/support';

describe('persistent thread fork', () => {
  installMutationActionsTestHooks();

  it('creates once and refreshes the list without submitting a prompt', async () => {
    const h = harness();
    expect(await h.actions.forkThread('thread-a')).toEqual({
      accepted: true, thread_id: 'fork-a', list_visibility: 'found', visibility_diagnostic: '', source_thread_id: 'thread-a', name_warning: '',
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
      accepted: true, thread_id: 'fork-a', list_visibility: 'found', visibility_diagnostic: '', source_thread_id: 'thread-a', name_warning: 'Rename failed.',
    });
    expect(await h.actions.forkThread('thread-a')).toMatchObject({
      accepted: true, thread_id: 'fork-a', visibility_diagnostic: expect.stringContaining('List unavailable'), name_warning: 'Rename failed.',
    });
    expect(h.api.forkThread).toHaveBeenCalledOnce();
    expect(h.reportError).not.toHaveBeenCalled();
  });

  it.each([{}, { thread_id: 'created-before-error' }])('preserves ambiguous or known creation after a server error: %o', async details => {
    const h = harness();
    h.api.forkThread.mockRejectedValueOnce(new FocusApiError('Server unavailable', { status: 503, code: 'failure', details }));
    expect(await h.actions.forkThread('thread-a')).toBeNull();
    expect(h.api.forkThread).toHaveBeenCalledOnce();
    const error = h.reportError.mock.calls[0]![0] as Error;
    expect(error.message).toContain('thread_id' in details ? 'Thread ID: created-before-error' : 'Fork result could not be confirmed');
  });

  it('rejects misdirected responses and rejects invalid wire results', async () => {
    const h = harness();
    h.api.forkThread.mockResolvedValue({ accepted: true, thread_id: 'fork-b', list_visibility: 'found', visibility_diagnostic: '', source_thread_id: 'other', name_warning: '' });
    expect(await h.actions.forkThread('thread-a')).toBeNull();
    const valid = { accepted: true, thread_id: 'fork', list_visibility: 'found', visibility_diagnostic: '', source_thread_id: 'parent', name_warning: '' };
    expect(decodeFocusForkResult({ ...valid, thread_id: 'parent' })).toBeNull();
    expect(decodeFocusForkResult({ ...valid, accepted: false })).toBeNull();
    expect(decodeFocusForkResult({ ...valid, name_warning: undefined })).toBeNull();
    expect(decodeFocusForkResult({ ...valid, name_warning: 42 })).toBeNull();
    expect(decodeFocusForkResult(valid)).toEqual(valid);
  });
});

describe('fork and history edit navigation', () => {
  installFocusClientTestHooks();

  const warning = 'Branch fork-a was created, but its automatic name could not be confirmed. You can rename it manually.';

  async function clientHarness(nameWarning = '', forkGate = Promise.resolve(), visibility: FocusForkResult['list_visibility'] = 'found') {
    const branch = { ...thread(), id: 'fork-a', name: 'Demo · 分支 fork-a', title: 'Demo · 分支 fork-a' };
    const api = Object.assign(new FakeApi(), {
      readHistoryEditPrompt: vi.fn(async (thread_id, target) => ({ thread_id, ...target, text: 'Full original\n  preserved  ' })),
      revertThread: vi.fn(async (thread_id) => { await forkGate; return { accepted: true as const, thread_id }; }),
      forkThread: vi.fn(async (_sourceId: string): Promise<FocusForkResult> => {
        await forkGate;
        api.threads.push(branch);
        return { accepted: true, thread_id: branch.id, list_visibility: visibility, visibility_diagnostic: '',
          source_thread_id: 'thread-1', name_warning: nameWarning };
      }),
    });
    api.threads.push({ ...thread(), id: 'other' });
    const read = api.readThread.bind(api);
    vi.spyOn(api, 'readThread').mockImplementation(async (id = 'thread-1') => {
      api.currentSnapshot = { ...snapshot('none', id), revision: api.metaValue.revision, thread: api.threads.find(t => t.id === id)! };
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
    expect(client.errorMessage.value).toBe('');
    expect(client.forkNote.value?.name_warning ?? '').toBe(nameWarning);
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
    expect(client.errorMessage.value).toBe('');
    expect(client.forkNote.value).toBeNull();
    await client.selectThread('fork-a');
    expect(client.forkNote.value?.name_warning).toBe(warning);
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
    expect(client.errorMessage.value).not.toContain(warning);
    expect(client.forkNote.value).toBeNull();
    vi.mocked(api.readThread).mockImplementation(read);
    await client.selectThread('fork-a');
    expect(client.forkNote.value?.name_warning).toBe(warning);
    expect(api.forkThread).toHaveBeenCalledOnce();
    client.dispose();
  });

  it('keeps a missing-page note until dismissed, scoped to the new branch', async () => {
    const gate = deferred<void>();
    const { api, client } = await clientHarness('', gate.promise, 'not_found');
    const forking = client.forkThread('thread-1');
    await client.selectThread('other');
    gate.resolve();
    await forking;
    expect(client.forkNote.value).toBeNull();
    await client.selectThread('fork-a');
    expect(client.forkNote.value?.list_visibility).toBe('not_found');
    await vi.advanceTimersByTimeAsync(10_000);
    expect(client.forkNote.value?.thread_id).toBe('fork-a');
    client.dismissForkNote('fork-a');
    await client.selectThread('other');
    await client.selectThread('fork-a');
    expect(client.forkNote.value).toBeNull();
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

  it('retains the original during revert without changing a newer thread selection', async () => {
    const gate = deferred<void>();
    const { api, client } = await clientHarness('', gate.promise);
    const target = { turn_id: 'inherited-turn', item_id: 'actual-item' };
    const creating = client.editPrompt('thread-1', target);
    await vi.advanceTimersByTimeAsync(0);
    await client.selectThread('other');
    gate.resolve(); await creating;
    expect(client.activeThreadId.value).toBe('other');
    expect(client.historyEditPrompt.value).toBeNull();
    await client.selectThread('thread-1');
    const prompt = client.historyEditPrompt.value!;
    expect(prompt).toEqual({ thread_id: 'thread-1', ...target, text: 'Full original\n  preserved  ' });
    expect(client.historyEditReady.value).toBe(false);
    client.consumeHistoryEditPrompt('other', prompt);
    expect(client.historyEditPrompt.value).toBe(prompt);
    client.consumeHistoryEditPrompt('thread-1', prompt);
    expect(client.historyEditPrompt.value).toBeNull();
    expect(api.revertThread).toHaveBeenCalledExactlyOnceWith('thread-1', target.turn_id);
    expect(api.forkThread).not.toHaveBeenCalled();
    expect(api.submitPromptCalls).toEqual([]);
    client.dispose();
  });

  it('keeps the original pending when repeated stale reads cannot install the reverted snapshot', async () => {
    const { api, client } = await clientHarness();
    const previous = client.snapshot.value;
    vi.mocked(api.readThread).mockClear().mockRejectedValue(new FocusApiError('Stale snapshot', {
      status: 409, code: 'stale_thread_read',
    }));
    await client.editPrompt('thread-1', { turn_id: 'turn', item_id: 'item' });
    expect(api.readThread).toHaveBeenCalledTimes(2);
    expect(client.snapshot.value).toBe(previous);
    expect(client.historyEditPrompt.value?.text).toBe('Full original\n  preserved  ');
    expect(client.historyEditReady.value).toBe(false);
    expect(client.errorMessage.value).toBe('');
    expect(api.revertThread).toHaveBeenCalledOnce();
    expect(api.submitPromptCalls).toEqual([]);
    client.dispose();
  });

  it('reports a current revert-refresh error while retaining the original for recovery', async () => {
    const { api, client } = await clientHarness();
    vi.mocked(api.readThread).mockRejectedValueOnce(new Error('Source refresh failed'));
    await client.editPrompt('thread-1', { turn_id: 'turn', item_id: 'item' });
    expect(client.errorMessage.value).toBe('Source refresh failed');
    expect(client.historyEditPrompt.value?.text).toBe('Full original\n  preserved  ');
    expect(client.historyEditReady.value).toBe(false);
    expect(api.revertThread).toHaveBeenCalledOnce();
    client.dispose();
  });

  it.each(['other', 'thread-1'])('drops a late revert-refresh error after navigation to %s', async destination => {
    const { api, client } = await clientHarness();
    const started = deferred<void>(), refresh = deferred<FocusThreadSnapshot>();
    vi.mocked(api.readThread).mockImplementationOnce(() => { started.resolve(); return refresh.promise; });
    const editing = client.editPrompt('thread-1', { turn_id: 'turn', item_id: 'item' });
    await started.promise;
    await client.selectThread('other');
    if (destination === 'thread-1') await client.selectThread('thread-1');
    const selected = client.snapshot.value;
    refresh.reject(new Error('Source refresh failed'));
    await editing;
    expect(client.activeThreadId.value).toBe(destination);
    expect(client.snapshot.value).toBe(selected);
    expect(client.errorMessage.value).toBe('');
    if (destination === 'other') await client.selectThread('thread-1');
    expect(client.historyEditPrompt.value?.text).toBe('Full original\n  preserved  ');
    expect(client.historyEditReady.value).toBe(false);
    expect(api.revertThread).toHaveBeenCalledOnce();
    client.dispose();
  });

  it('does not automatically restore from a superseded refresh after navigating away and back', async () => {
    const { api, client } = await clientHarness();
    const started = deferred<void>(), refresh = deferred<FocusThreadSnapshot>();
    const previous = client.snapshot.value!;
    vi.mocked(api.readThread).mockImplementationOnce(() => { started.resolve(); return refresh.promise; });
    const editing = client.editPrompt('thread-1', { turn_id: 'turn', item_id: 'item' });
    await started.promise;
    await client.selectThread('other');
    await client.selectThread('thread-1');
    const selected = client.snapshot.value;
    refresh.resolve(previous);
    await editing;
    expect(client.snapshot.value).toBe(selected);
    expect(client.historyEditPrompt.value?.text).toBe('Full original\n  preserved  ');
    expect(client.historyEditReady.value).toBe(false);
    expect(api.revertThread).toHaveBeenCalledOnce();
    client.dispose();
  });

  it.each([
    { status: 401, code: 'unauthorized', state: 'authRequired' as const },
    { status: 409, code: 'document_replaced', state: 'documentReloadRequired' as const },
  ])('keeps global $code handling for a late revert-refresh error', async ({ status, code, state }) => {
    const { api, client } = await clientHarness();
    const started = deferred<void>(), refresh = deferred<FocusThreadSnapshot>();
    vi.mocked(api.readThread).mockImplementationOnce(() => { started.resolve(); return refresh.promise; });
    const editing = client.editPrompt('thread-1', { turn_id: 'turn', item_id: 'item' });
    await started.promise;
    await client.selectThread('other');
    refresh.reject(new FocusApiError('Access expired', { status, code }));
    await editing;
    expect(client[state].value).toBe(true);
    expect(client.errorMessage.value).toBe('');
    expect(client.activeThreadId.value).toBe('other');
    client.dispose();
  });

  it('keeps failed visibility checks in runtime details without a failure banner', async () => {
    const { api, client } = await clientHarness('', Promise.resolve(), 'check_failed');
    const fork = api.forkThread.getMockImplementation()!;
    api.forkThread.mockImplementation(async (...args) => ({ ...await fork(...args), visibility_diagnostic: 'thread/list check timed out' }));
    await client.forkThread('thread-1');
    expect(client.errorMessage.value).toBe('');
    expect(client.forkNote.value).toBeNull();
    expect(client.runtimeNoticePresentation.value.notices.some(n => n.message.includes('timed out'))).toBe(true);
    client.dispose();
  });

  it('drops history caches only for an admitted revert notification on the current thread', async () => {
    const { api, client } = await clientHarness();
    const reset = vi.spyOn(client.transcript, 'reset');
    api.emit({ type: 'thread_invalidated', reason: 'thread/reverted', runtime_epoch: 'epoch-1', revision: 1, thread_id: 'thread-1' });
    expect(reset).toHaveBeenCalledOnce();
    api.emit({ type: 'thread_invalidated', reason: 'thread/reverted', runtime_epoch: 'epoch-1', revision: 0, thread_id: 'thread-1' });
    api.emit({ type: 'thread_invalidated', reason: 'thread/reverted', runtime_epoch: 'epoch-1', revision: 2, thread_id: 'other' });
    expect(reset).toHaveBeenCalledOnce();
    client.dispose();
  });

  it('retires a historical body window and prompt locators when reconnecting after a missed revert', async () => {
    const { api, client } = await clientHarness();
    api.threads[0]!.history_mode = 'paginated';
    const oldRow = { id: 'old-row', rawTurnId: 'old-turn', itemId: 'old-item', role: 'user' as const, no: 0, text: 'Removed prompt' };
    let reverted = false;
    vi.spyOn(api, 'readTranscriptWindow').mockImplementation(async (id, query = {}) => ({
      runtime_epoch: 'epoch-1', revision: api.metaValue.revision, thread_id: id,
      turn_id: query.turn_id ?? null, turns: reverted ? [] : [oldRow], view: query.view ?? 'transcript',
      target_pending: false, older_cursor: null, newer_cursor: query.turn_id ? 'newer-page' : null, full_text: null,
    }));
    await client.reloadAll(); await vi.advanceTimersByTimeAsync(0);
    await client.transcript.locate('old-turn', 'old-item');
    client.setHistoryOutlineVisible(true); await vi.advanceTimersByTimeAsync(0);
    expect(client.transcript.historical.value).toBe(true);
    expect(client.historyOutline.value.some(p => p.id === 'old-row')).toBe(true);
    // An ordinary reconnect with the same revision must still rehydrate the view.
    await client.reloadAll(); await vi.advanceTimersByTimeAsync(0);
    expect(client.transcript.turns.value).toEqual([oldRow]);
    expect(client.historyOutline.value.some(p => p.id === 'old-row')).toBe(true);
    await client.transcript.locate('old-turn', 'old-item');
    reverted = true;
    api.setRuntimeCoordinates('epoch-1', 2);
    api.emit({ type: 'hello', runtime_epoch: 'epoch-1', revision: 2 });
    await client.reloadAll(); await vi.advanceTimersByTimeAsync(0);
    expect(client.transcript.turns.value).toEqual([]);
    expect(client.historyOutline.value).toEqual([]);
    client.dispose();
  });
});
