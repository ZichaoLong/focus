import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFocusThreadActions, type ExportOptionsChoice, type ExportOptionsRequest } from '../src/focus/focusThreadActions';
import { openSummaryPrintWindow } from '../src/focus/summaryPrintWindow';

vi.mock('../src/focus/summaryPrintWindow', () => ({ openSummaryPrintWindow: vi.fn() }));
afterEach(() => { vi.resetAllMocks(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function mockDownload() {
  vi.useFakeTimers();
  const anchor = { href: '', download: '', style: {}, click: vi.fn(), remove: vi.fn() };
  vi.stubGlobal('document', { createElement: () => anchor, body: { appendChild: vi.fn() } });
  vi.stubGlobal('window', { setTimeout });
  const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:export');
  const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  return { anchor, create, revoke };
}

function setup() {
  const preview = { deliver: vi.fn(), fail: vi.fn() };
  vi.mocked(openSummaryPrintWindow).mockReturnValue(preview);
  const client = {
    summaryExporting: { value: false }, threadDataExporting: { value: false },
    exportThreadSummary: vi.fn(async (): Promise<Blob | null> => new Blob(['Full history'])),
    exportThreadData: vi.fn(async (): Promise<Blob | null> => new Blob(['{"full":"record"}\n'])), archiveThread: vi.fn(),
  };
  const notify = vi.fn();
  const getThreadTitle = vi.fn(() => '目标会话');
  const requestExportOptions = vi.fn(async ({ suggestedFilename, suggestedDocumentTitle }: ExportOptionsRequest): Promise<ExportOptionsChoice | null> => ({ filename: suggestedFilename, documentTitle: suggestedDocumentTitle }));
  const actions = createFocusThreadActions({ client, notify, getThreadTitle, requestExportOptions, translate: (key) => key, confirm: vi.fn() });
  return { preview, client, notify, getThreadTitle, requestExportOptions, actions };
}

describe('Q&A print action', () => {
  it('opens synchronously before fetching the complete export and never claims a saved PDF', async () => {
    const { client, preview, actions, notify, requestExportOptions, getThreadTitle } = setup();
    client.exportThreadSummary.mockImplementation(async () => {
      expect(openSummaryPrintWindow).toHaveBeenCalledOnce();
      return new Blob(['Full history']);
    });
    await actions.exportThreadSummary({ threadId: 'not-the-active-thread', format: 'print' });
    expect(client.exportThreadSummary).toHaveBeenCalledExactlyOnceWith('not-the-active-thread');
    expect(preview.deliver).toHaveBeenCalledExactlyOnceWith('Full history', '目标会话.pdf', '目标会话');
    expect(getThreadTitle).toHaveBeenCalledExactlyOnceWith('not-the-active-thread');
    expect(requestExportOptions).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
  });

  it.each(['summaryExporting', 'threadDataExporting'] as const)('shares the export busy gate: %s', async (flag) => {
    const { client, actions, notify } = setup();
    client[flag].value = true;
    await actions.exportThreadSummary({ threadId: 'one', format: 'print' });
    expect(openSummaryPrintWindow).not.toHaveBeenCalled();
    expect(client.exportThreadSummary).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith('focus.summaryExportBusy');
  });

  it('does not fetch if the browser blocks the preview', async () => {
    const { client, actions, notify } = setup();
    vi.mocked(openSummaryPrintWindow).mockReturnValue(null);
    await actions.exportThreadSummary({ threadId: 'one', format: 'print' });
    expect(client.exportThreadSummary).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledWith('focus.printPopupBlocked');
  });

  it.each([false, true])('keeps the preview informed of export failure (throws: %s)', async (throws) => {
    const { client, actions, preview } = setup();
    client.exportThreadSummary.mockImplementation(async () => { if (throws) throw new Error('network'); return null; });
    await actions.exportThreadSummary({ threadId: 'one', format: 'print' });
    expect(preview.fail).toHaveBeenCalledOnce();
    expect(preview.deliver).not.toHaveBeenCalled();
  });

  it('snapshots the selected title before loading and holds the gate through Blob reading', async () => {
    const { client, actions, preview, getThreadTitle, requestExportOptions } = setup();
    const content = deferred<string>();
    client.exportThreadSummary.mockResolvedValue({ text: () => content.promise } as Blob);
    const printing = actions.exportThreadSummary({ threadId: 'one', format: 'print' });
    getThreadTitle.mockReturnValue('另一会话');
    await actions.exportThreadData('two');
    expect(requestExportOptions).not.toHaveBeenCalled();
    content.resolve('Full original Markdown');
    await printing;
    expect(preview.deliver).toHaveBeenCalledWith('Full original Markdown', '目标会话.pdf', '目标会话');
  });
});

describe('named Markdown and JSONL downloads', () => {
  it('waits for confirmation, keeps the exact target, and downloads the chosen document heading with the original body', async () => {
    const { client, actions, requestExportOptions, getThreadTitle } = setup();
    const { anchor, create, revoke } = mockDownload();
    const name = deferred<ExportOptionsChoice | null>();
    requestExportOptions.mockReturnValue(name.promise);
    const exporting = actions.exportThreadSummary({ threadId: 'sidebar-thread', format: 'markdown' });
    expect(getThreadTitle).toHaveBeenCalledExactlyOnceWith('sidebar-thread');
    expect(requestExportOptions).toHaveBeenCalledExactlyOnceWith({ format: 'markdown', suggestedFilename: '目标会话.md', suggestedDocumentTitle: '目标会话' });
    expect(client.exportThreadSummary).not.toHaveBeenCalled();
    getThreadTitle.mockReturnValue('Changed active thread');
    name.resolve({ filename: '我的归档', documentTitle: '独立标题' });
    await exporting;
    expect(client.exportThreadSummary).toHaveBeenCalledExactlyOnceWith('sidebar-thread');
    expect(anchor.download).toBe('我的归档.md');
    expect(anchor.click).toHaveBeenCalledOnce();
    expect(anchor.remove).toHaveBeenCalledOnce();
    expect(await create.mock.calls[0]![0].text()).toBe('# 独立标题\n\nFull history');
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:export');
  });

  it('uses the same naming flow for JSONL and preserves its content', async () => {
    const { actions, client, requestExportOptions } = setup();
    const { anchor, create } = mockDownload();
    requestExportOptions.mockResolvedValue({ filename: '工具/记录.JSONL', documentTitle: 'Ignored for JSONL' });
    await actions.exportThreadData('data-thread');
    expect(requestExportOptions).toHaveBeenCalledWith({ format: 'jsonl', suggestedFilename: '目标会话.jsonl' });
    expect(client.exportThreadData).toHaveBeenCalledExactlyOnceWith('data-thread');
    expect(anchor.download).toBe('工具-记录.jsonl');
    expect(await create.mock.calls[0]![0].text()).toBe('{"full":"record"}\n');
  });

  it.each([null, '', '   ', '.md'])('does not fetch or download on cancellation or an empty name: %s', async (choice) => {
    const { actions, client, requestExportOptions, notify } = setup();
    const { anchor } = mockDownload();
    requestExportOptions.mockResolvedValue(choice === null ? null : { filename: choice });
    await actions.exportThreadSummary({ threadId: 'one', format: 'markdown' });
    expect(client.exportThreadSummary).not.toHaveBeenCalled();
    expect(anchor.click).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
    // Cancelling releases the gate for another format.
    requestExportOptions.mockResolvedValue({ filename: 'retry' });
    await actions.exportThreadData('two');
    expect(client.exportThreadData).toHaveBeenCalledExactlyOnceWith('two');
  });

  it('prevents competing dialogs and print popups while choosing a filename', async () => {
    const { actions, client, requestExportOptions } = setup();
    const name = deferred<ExportOptionsChoice | null>();
    requestExportOptions.mockReturnValue(name.promise);
    const first = actions.exportThreadData('one');
    await actions.exportThreadSummary({ threadId: 'two', format: 'markdown' });
    await actions.exportThreadSummary({ threadId: 'three', format: 'print' });
    expect(requestExportOptions).toHaveBeenCalledOnce();
    expect(openSummaryPrintWindow).not.toHaveBeenCalled();
    name.resolve(null);
    await first;
    expect(client.exportThreadData).not.toHaveBeenCalled();
  });

  it.each(['summaryExporting', 'threadDataExporting'] as const)('checks %s before naming and again before fetching', async (flag) => {
    const { actions, client, requestExportOptions } = setup();
    client[flag].value = true;
    await actions.exportThreadData('one');
    expect(requestExportOptions).not.toHaveBeenCalled();
    client[flag].value = false;
    const name = deferred<ExportOptionsChoice | null>();
    requestExportOptions.mockReturnValue(name.promise);
    const exporting = actions.exportThreadData('one');
    client[flag].value = true;
    name.resolve({ filename: 'file' });
    await exporting;
    expect(client.exportThreadData).not.toHaveBeenCalled();
  });

  it.each([false, true])('does not download a failed read and permits retry (throws: %s)', async (throws) => {
    const { actions, client } = setup();
    const { anchor } = mockDownload();
    client.exportThreadData.mockImplementationOnce(async () => { if (throws) throw new Error('network'); return null; });
    const first = actions.exportThreadData('one');
    if (throws) await expect(first).rejects.toThrow('network');
    else await first;
    expect(anchor.click).not.toHaveBeenCalled();
    await actions.exportThreadData('one');
    expect(anchor.click).toHaveBeenCalledOnce();
  });
});
