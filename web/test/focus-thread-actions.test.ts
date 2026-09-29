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

function mockSavePicker() {
  const download = mockDownload();
  const stream = { write: vi.fn(async (_blob: Blob) => {}), close: vi.fn(async () => {}), abort: vi.fn(async () => {}) };
  const handle = { createWritable: vi.fn(async () => stream) };
  const picker = vi.fn(async (_options: unknown) => handle);
  vi.stubGlobal('window', { setTimeout, isSecureContext: true, showSaveFilePicker: picker });
  return { ...download, stream, handle, picker };
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
    const { actions, client, notify } = setup();
    const { anchor } = mockDownload();
    client.exportThreadData.mockImplementationOnce(async () => { if (throws) throw new Error('network'); return null; });
    await actions.exportThreadData('one');
    expect(anchor.click).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalledWith('focus.threadDataExportComplete');
    expect(notify).toHaveBeenCalledWith('focus.exportSaveFailed');
    await actions.exportThreadData('one');
    expect(anchor.click).toHaveBeenCalledOnce();
  });
});

describe('system Save As for Markdown and JSONL', () => {
  it.each(['markdown', 'jsonl'] as const)('selects a %s file before fetching and writes the complete content', async (format) => {
    const { actions, client, requestExportOptions, notify } = setup();
    const { picker, handle, stream, anchor, create } = mockSavePicker();
    const choice = deferred<ExportOptionsChoice | null>();
    requestExportOptions.mockReturnValue(choice.promise);
    const load = format === 'markdown' ? client.exportThreadSummary : client.exportThreadData;
    const blob = new Blob([format === 'markdown' ? '# Codex conversation summary\n\n正文' : '{"原始":"数据"}\n']);
    load.mockImplementation(async () => {
      expect(picker).toHaveBeenCalledOnce();
      expect(handle.createWritable).not.toHaveBeenCalled();
      return blob;
    });
    const exporting = format === 'markdown'
      ? actions.exportThreadSummary({ threadId: 'selected-thread', format })
      : actions.exportThreadData('selected-thread');
    expect(picker).not.toHaveBeenCalled();
    choice.resolve({ filename: '自定/文件', documentTitle: '独立文档标题' });
    await exporting;
    expect(picker).toHaveBeenCalledExactlyOnceWith({
      suggestedName: format === 'markdown' ? '自定-文件.md' : '自定-文件.jsonl',
      types: format === 'markdown'
        ? [{ description: 'Markdown', accept: { 'text/markdown': ['.md'] } }]
        : [{ description: 'JSON Lines', accept: { 'application/x-ndjson': ['.jsonl'] } }],
    });
    expect(load).toHaveBeenCalledExactlyOnceWith('selected-thread');
    expect(await stream.write.mock.calls[0]![0].text()).toBe(format === 'markdown'
      ? '# 独立文档标题\n\n正文' : '{"原始":"数据"}\n');
    expect(stream.close).toHaveBeenCalledOnce();
    expect(stream.abort).not.toHaveBeenCalled();
    expect(anchor.click).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    expect(notify).toHaveBeenLastCalledWith(format === 'markdown'
      ? 'focus.summaryExportComplete' : 'focus.threadDataExportComplete');
  });

  it('cancels without fetching or downloading and releases the export gate', async () => {
    const { actions, client, notify } = setup();
    const { picker, handle, anchor } = mockSavePicker();
    picker.mockRejectedValueOnce(new DOMException('Cancelled', 'AbortError'));
    await actions.exportThreadData('one');
    expect(client.exportThreadData).not.toHaveBeenCalled();
    expect(handle.createWritable).not.toHaveBeenCalled();
    expect(anchor.click).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalled();
    await actions.exportThreadData('two');
    expect(client.exportThreadData).toHaveBeenCalledExactlyOnceWith('two');
  });

  it('holds the export gate through the picker and final close, keeping the original target and title', async () => {
    const { actions, client, notify, getThreadTitle, requestExportOptions } = setup();
    const { picker, handle, stream } = mockSavePicker();
    const selection = deferred<typeof handle>();
    const closed = deferred<void>();
    picker.mockReturnValueOnce(selection.promise);
    stream.close.mockReturnValueOnce(closed.promise);
    const exporting = actions.exportThreadSummary({ threadId: 'original', format: 'markdown' });
    await vi.waitFor(() => expect(picker).toHaveBeenCalledOnce());
    getThreadTitle.mockReturnValue('Changed thread');
    await actions.exportThreadData('other');
    await actions.exportThreadSummary({ threadId: 'other', format: 'print' });
    expect(client.exportThreadSummary).not.toHaveBeenCalled();
    expect(openSummaryPrintWindow).not.toHaveBeenCalled();
    selection.resolve(handle);
    await vi.waitFor(() => expect(stream.close).toHaveBeenCalledOnce());
    await actions.exportThreadData('other');
    expect(requestExportOptions).toHaveBeenCalledOnce();
    expect(client.exportThreadSummary).toHaveBeenCalledExactlyOnceWith('original');
    expect(await stream.write.mock.calls[0]![0].text()).toBe('# 目标会话\n\nFull history');
    expect(notify).not.toHaveBeenCalledWith('focus.summaryExportComplete');
    closed.resolve();
    await exporting;
    expect(notify).toHaveBeenLastCalledWith('focus.summaryExportComplete');
  });

  it.each(['insecure', 'missing', 'SecurityError', 'NotSupportedError'])('uses ordinary downloads when the picker is unavailable: %s', async (reason) => {
    const { actions, client } = setup();
    const { picker, handle, anchor } = mockSavePicker();
    if (reason === 'insecure') vi.stubGlobal('window', { setTimeout, isSecureContext: false, showSaveFilePicker: picker });
    else if (reason === 'missing') vi.stubGlobal('window', { setTimeout, isSecureContext: true });
    else picker.mockRejectedValueOnce(new DOMException('Unavailable', reason));
    await actions.exportThreadData('one');
    if (reason === 'insecure' || reason === 'missing') expect(picker).not.toHaveBeenCalled();
    expect(handle.createWritable).not.toHaveBeenCalled();
    expect(client.exportThreadData).toHaveBeenCalledExactlyOnceWith('one');
    expect(anchor.download).toBe('目标会话.jsonl');
    expect(anchor.click).toHaveBeenCalledOnce();
  });

  it.each(['NotAllowedError', 'UnknownError'])('reports other picker errors without fetching or silently downloading: %s', async (reason) => {
    const { actions, client, notify } = setup();
    const { picker, anchor } = mockSavePicker();
    picker.mockRejectedValueOnce(new DOMException('Failed', reason));
    await actions.exportThreadData('one');
    expect(client.exportThreadData).not.toHaveBeenCalled();
    expect(anchor.click).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledExactlyOnceWith('focus.exportSaveFailed');
    await actions.exportThreadData('two');
    expect(client.exportThreadData).toHaveBeenCalledExactlyOnceWith('two');
  });

  it.each([false, true])('never opens a writable stream on a failed export (throws: %s)', async (throws) => {
    const { actions, client, notify } = setup();
    const { handle, anchor } = mockSavePicker();
    client.exportThreadData.mockImplementationOnce(async () => { if (throws) throw new Error('network'); return null; });
    await actions.exportThreadData('one');
    expect(handle.createWritable).not.toHaveBeenCalled();
    expect(anchor.click).not.toHaveBeenCalled();
    expect(notify).not.toHaveBeenCalledWith('focus.threadDataExportComplete');
    expect(notify).toHaveBeenLastCalledWith('focus.exportSaveFailed');
  });

  it.each(['createWritable', 'write', 'close'] as const)('reports a %s failure without claiming success or starting a second download', async (step) => {
    const { actions, notify } = setup();
    const { handle, stream, anchor } = mockSavePicker();
    const fail = step === 'createWritable' ? handle.createWritable : stream[step];
    fail.mockRejectedValueOnce(new DOMException('Cannot save', 'NotAllowedError'));
    await actions.exportThreadData('one');
    expect(anchor.click).not.toHaveBeenCalled();
    expect(notify).toHaveBeenLastCalledWith('focus.exportSaveFailed');
    expect(notify).not.toHaveBeenCalledWith('focus.threadDataExportComplete');
    if (step !== 'createWritable') expect(stream.abort).toHaveBeenCalledOnce();
    if (step === 'write') expect(stream.close).not.toHaveBeenCalled();
    await actions.exportThreadData('two');
    expect(notify).toHaveBeenLastCalledWith('focus.threadDataExportComplete');
  });
});
