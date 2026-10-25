import { describe, expect, it, vi } from 'vitest';
import type { FocusWebApiPort } from '../../src/focus/api';
import { FocusApiError, type FocusPromptResultReceipt } from '../../src/focus/types';
import { useFocusWebClient } from '../../src/focus/useFocusWebClient';
import { FakeApi, installFocusClientTestHooks, snapshot, thread } from './support';
import { deferred } from './owners/mutation-actions-test-support';

installFocusClientTestHooks();
const key = 'focus-web.prompt-result-locators';
const mutationId = '00000000-0000-4000-8000-000000000001';
const secondMutationId = '00000000-0000-4000-8000-000000000002';

function remember(...ids: string[]) {
  sessionStorage.setItem(key, JSON.stringify({ schemaVersion: 1,
    locators: ids.map((id) => ({ threadId: 'thread-1', mutationId: id })),
  }));
}

function connect(api: FakeApi, client: ReturnType<typeof useFocusWebClient>) {
  api.handlers?.open?.();
  api.emit({ type: 'hello', runtime_epoch: 'epoch-1', revision: client.revision.value });
}

function receipt(status: FocusPromptResultReceipt['status'], id = mutationId): FocusPromptResultReceipt {
  return { thread_id: 'thread-1', mutation_id: id, client_user_message_id: `focus-web:${id}`,
    status, mode: 'start', turn_id: status === 'succeeded' ? 'turn-1' : '', reason_code: '',
    diagnostic_stage: 'upstream', observed_thread_status: null, recorded_at: 1_790_550_000 };
}

function disconnectedError() {
  return new FocusApiError('document disconnected', {
    status: 409, code: 'web_writer_disconnected', effectEvidence: 'pre_effect',
  });
}

describe('Prompt result reconciliation at browser boundaries', () => {
  it('waits for hello, then queries saved locators without replaying or blocking new input', async () => {
    remember(mutationId);
    const api = new FakeApi();
    const read = vi.spyOn(api as FocusWebApiPort, 'readPromptResult').mockResolvedValue(receipt('outcome_unknown'));
    const client = useFocusWebClient(api);
    await client.load();
    expect(read).not.toHaveBeenCalled();
    api.handlers?.open?.();
    expect(read).not.toHaveBeenCalled();
    connect(api, client);
    await vi.advanceTimersByTimeAsync(100);
    expect(read).toHaveBeenCalledOnce();
    expect(client.errorMessage.value).toBe('');
    expect(client.promptResultNotices.value).toHaveLength(1);
    expect(client.canSubmit.value).toBe(true);
    expect(api.submitPromptCalls).toHaveLength(0);
    await expect(client.submit('new request')).resolves.toBe(true);
    expect(api.submitPromptCalls).toHaveLength(1);
    client.dispose();
  });

  it('repairs a disconnected writer through the connection status and retries after hello', async () => {
    remember(mutationId);
    const api = new FakeApi();
    const read = vi.spyOn(api, 'readPromptResult').mockRejectedValueOnce(disconnectedError());
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    await vi.advanceTimersByTimeAsync(100);
    expect(client.connection.value).toBe('connecting');
    expect(client.errorMessage.value).toBe('');
    expect(client.promptResultNotices.value).toEqual([]);
    expect(sessionStorage.getItem(key)).toContain(mutationId);
    await client.reloadAll();
    expect(read).toHaveBeenCalledOnce();
    connect(api, client);
    await vi.advanceTimersByTimeAsync(100);
    expect(read).toHaveBeenCalledTimes(2);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(client.canSubmit.value).toBe(true);
    expect(api.submitPromptCalls).toHaveLength(0);
    client.dispose();
  });

  it('clears the exact ambiguous POST warning when its background GET confirms success', async () => {
    const api = new FakeApi();
    const response = deferred<FocusPromptResultReceipt>();
    vi.spyOn(api as FocusWebApiPort, 'readPromptResult').mockReturnValueOnce(response.promise);
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    const submit = vi.spyOn(api, 'submitPrompt').mockRejectedValueOnce(new TypeError('lost response'));
    await expect(client.submit('possibly sent')).resolves.toBe(true);
    const id = String(submit.mock.calls[0]![1].mutationId);
    expect(JSON.parse(client.errorPresentation.value.diagnostic).diagnostic_id).toBe(id);
    response.resolve(receipt('succeeded', id));
    await vi.advanceTimersByTimeAsync(100);
    expect(client.errorMessage.value).toBe('');
    expect(client.promptResultNotices.value).toEqual([]);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(submit).toHaveBeenCalledOnce();
    client.dispose();
  });

  it('defers result notifications until live POST settlement, then clears a lost-response warning', async () => {
    const api = new FakeApi();
    const post = deferred<FocusPromptResultReceipt>();
    const submit = vi.spyOn(api as FocusWebApiPort, 'submitPrompt').mockReturnValueOnce(post.promise);
    const read = vi.spyOn(api, 'readPromptResult');
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    const submitting = client.submit('delayed POST');
    expect(submit).toHaveBeenCalledOnce();
    api.emit({ type: 'thread_invalidated', runtime_epoch: 'epoch-1', revision: client.revision.value + 1,
      thread_id: 'thread-1', reason: 'web_prompt_succeeded' });
    await client.reloadAll();
    expect(read).not.toHaveBeenCalled();
    post.reject(new TypeError('lost response after server success'));
    await expect(submitting).resolves.toBe(true);
    await vi.advanceTimersByTimeAsync(100);
    expect(read).toHaveBeenCalledOnce();
    expect(client.errorMessage.value).toBe('');
    expect(sessionStorage.getItem(key)).toBeNull();
    client.dispose();
  });

  it('rechecks an observed result even when an older GET is still pending', async () => {
    remember(mutationId);
    const api = new FakeApi();
    const older = deferred<FocusPromptResultReceipt>();
    const read = vi.spyOn(api as FocusWebApiPort, 'readPromptResult')
      .mockReturnValueOnce(older.promise).mockResolvedValue(receipt('succeeded'));
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    api.emit({ type: 'thread_invalidated', runtime_epoch: 'epoch-1', revision: client.revision.value + 1,
      thread_id: 'thread-1', reason: 'web_prompt_result_observed' });
    await vi.advanceTimersByTimeAsync(100);
    expect(read).toHaveBeenCalledTimes(2);
    expect(sessionStorage.getItem(key)).toBeNull();
    older.resolve(receipt('pending'));
    await vi.advanceTimersByTimeAsync(100);
    expect(client.promptResultNotices.value).toEqual([]);
    client.dispose();
  });

  it('does not clear an unrelated newer error when an older result succeeds', async () => {
    remember(mutationId);
    const api = new FakeApi();
    const response = deferred<FocusPromptResultReceipt>();
    vi.spyOn(api as FocusWebApiPort, 'readPromptResult').mockReturnValueOnce(response.promise);
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    vi.spyOn(api, 'exportThreadSummary').mockRejectedValueOnce(new Error('export failed'));
    await client.exportThreadSummary('thread-1');
    response.resolve(receipt('succeeded'));
    await vi.advanceTimersByTimeAsync(100);
    expect(client.errorMessage.value).toBe('export failed');
    expect(sessionStorage.getItem(key)).toBeNull();
    client.dispose();
  });

  it('keeps a newer submission error when an older submission is confirmed', async () => {
    const api = new FakeApi();
    const response = deferred<FocusPromptResultReceipt>();
    vi.spyOn(api as FocusWebApiPort, 'readPromptResult').mockReturnValueOnce(response.promise);
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    const submit = vi.spyOn(api, 'submitPrompt').mockRejectedValueOnce(new TypeError('lost response'));
    await client.submit('older request');
    const id = String(submit.mock.calls[0]![1].mutationId);
    submit.mockRejectedValueOnce(new FocusApiError('cannot send', {
      code: 'invalid_prompt', status: 400, effectEvidence: 'pre_effect',
    }));
    await expect(client.submit('newer request')).resolves.toBe(false);
    const newerError = client.errorPresentation.value;
    response.resolve(receipt('succeeded', id));
    await vi.advanceTimersByTimeAsync(100);
    expect(client.errorPresentation.value).toEqual(newerError);
    expect(JSON.parse(newerError.diagnostic).reason_code).toBe('invalid_prompt');
    client.dispose();
  });

  it('coalesces repeated reload lookups and drops an in-flight lookup after disposal', async () => {
    remember(mutationId);
    const api = new FakeApi();
    const response = deferred<FocusPromptResultReceipt>();
    const read = vi.spyOn(api as FocusWebApiPort, 'readPromptResult').mockReturnValue(response.promise);
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    await client.reloadAll();
    await client.reloadAll();
    expect(read).toHaveBeenCalledOnce();
    client.dispose();
    response.resolve(receipt('succeeded'));
    await vi.advanceTimersByTimeAsync(100);
    expect(client.promptResultNotices.value).toEqual([]);
    expect(client.errorMessage.value).toBe('');
    expect(sessionStorage.getItem(key)).toContain(mutationId);
  });

  it.each(['failure', 'unknown', 'unavailable'] as const)(
    'drops a late %s lookup after switching threads, including a return to the same thread', async (outcome) => {
      remember(mutationId);
      const api = new FakeApi();
      const late = deferred<FocusPromptResultReceipt>();
      const latest = deferred<FocusPromptResultReceipt>();
      vi.spyOn(api as FocusWebApiPort, 'readPromptResult')
        .mockReturnValueOnce(late.promise).mockReturnValue(latest.promise);
      const client = useFocusWebClient(api);
      await client.load();
      connect(api, client);
      api.threads = [thread(), { ...thread(), id: 'thread-2' }];
      api.currentSnapshot = snapshot('none', 'thread-2', 3);
      await client.selectThread('thread-2');
      expect(client.promptResultNotices.value).toEqual([]);
      api.currentSnapshot = snapshot('none', 'thread-1', 4);
      await client.selectThread('thread-1');
      if (outcome === 'unknown') late.resolve(receipt('outcome_unknown'));
      else late.reject(outcome === 'failure' ? disconnectedError() : new FocusApiError('evicted', {
        code: 'prompt_result_unavailable', status: 404, effectEvidence: 'pre_effect',
      }));
      await vi.advanceTimersByTimeAsync(100);
      expect(client.errorMessage.value).toBe('');
      expect(client.connection.value).toBe('connected');
      expect(client.promptResultNotices.value).toEqual([]);
      expect(sessionStorage.getItem(key)).toContain(mutationId);
      latest.resolve(receipt('succeeded'));
      await vi.advanceTimersByTimeAsync(100);
      expect(sessionStorage.getItem(key)).toBeNull();
      client.dispose();
    },
  );

  it('keeps dismissals local to presentation, and reconciles each exact result on reload', async () => {
    remember(mutationId, secondMutationId);
    const api = new FakeApi();
    const read = vi.spyOn(api as FocusWebApiPort, 'readPromptResult')
      .mockImplementation(async (_thread, id) => receipt('outcome_unknown', id));
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    await vi.advanceTimersByTimeAsync(100);
    expect(client.promptResultNotices.value).toHaveLength(2);
    client.dismissPromptResultNotice(mutationId);
    expect(client.promptResultNotices.value.map((notice) => notice.mutationId)).toEqual([secondMutationId]);
    expect(sessionStorage.getItem(key)).toContain(mutationId);
    await client.reloadAll();
    await vi.advanceTimersByTimeAsync(100);
    expect(client.promptResultNotices.value).toHaveLength(1);
    read.mockImplementation(async (_thread, id) => receipt(id === mutationId ? 'succeeded' : 'outcome_unknown', id));
    await client.reloadAll();
    await vi.advanceTimersByTimeAsync(100);
    expect(client.promptResultNotices.value.map((notice) => notice.mutationId)).toEqual([secondMutationId]);
    expect(sessionStorage.getItem(key)).not.toContain(mutationId);
    read.mockImplementation(async (_thread, id) => receipt('succeeded', id));
    api.handlers?.close?.();
    await vi.advanceTimersByTimeAsync(1_000);
    connect(api, client);
    await vi.advanceTimersByTimeAsync(100);
    expect(client.promptResultNotices.value).toEqual([]);
    expect(sessionStorage.getItem(key)).toBeNull();
    expect(api.submitPromptCalls).toHaveLength(0);
    client.dispose();
  });

  it('does not hide an authentication failure or turn it into a historical prompt notice', async () => {
    remember(mutationId);
    const api = new FakeApi();
    vi.spyOn(api, 'readPromptResult').mockRejectedValueOnce(new FocusApiError('login required', {
      status: 401, code: 'unauthorized',
    }));
    const client = useFocusWebClient(api);
    await client.load();
    connect(api, client);
    await vi.advanceTimersByTimeAsync(100);
    expect(client.authRequired.value).toBe(true);
    expect(client.promptResultNotices.value).toEqual([]);
    expect(sessionStorage.getItem(key)).toContain(mutationId);
    client.dispose();
  });
});
