import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFileDownload, type FileDownloadApi } from '../src/focus/fileDownload';
import { saveFileResponse } from '../src/focus/browserFileSave';
import { normalizeDownloadFilename } from '../src/focus/exportFilename';
import { parseLocalFileHref } from '../src/lib/filePathLinks';
import { FocusApiError } from '../src/focus/types';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function setup(picker = true) {
  const stream = { write: vi.fn(async (_value: Uint8Array) => {}), close: vi.fn(async () => {}), abort: vi.fn(async () => {}) };
  const handle = { createWritable: vi.fn(async () => stream) };
  const showSaveFilePicker = vi.fn(async () => handle);
  vi.stubGlobal('window', { isSecureContext: true, ...(picker ? { showSaveFilePicker } : {}) });
  const anchor = { href: '', download: '', target: '', rel: '', click: vi.fn(), remove: vi.fn() };
  vi.stubGlobal('document', { createElement: () => anchor, body: { appendChild: vi.fn() } });
  const api = {
    fileInfo: vi.fn<FileDownloadApi['fileInfo']>(async () => ({ path: '/work/report.txt', name: 'report.txt', size: 5 })),
    fileContent: vi.fn<FileDownloadApi['fileContent']>(async () => new Response('hello')),
    fileDownloadUrl: vi.fn<FileDownloadApi['fileDownloadUrl']>(() => '/download-url'),
  };
  return { stream, handle, showSaveFilePicker, anchor, api, state: createFileDownload(api) };
}

describe('single-file saving', () => {
  it('inspects only on click, invokes picker before fetching and streams into the chosen file', async () => {
    const { api, state, showSaveFilePicker, stream } = setup();
    expect(api.fileInfo).not.toHaveBeenCalled();
    await state.open('./report.txt', '/work');
    expect(api.fileContent).not.toHaveBeenCalled();
    state.name.value = '自定文件.txt';
    api.fileContent.mockImplementation(async () => {
      expect(showSaveFilePicker).toHaveBeenCalledExactlyOnceWith({ suggestedName: '自定文件.txt' });
      return new Response('hello');
    });
    await state.save();
    expect(api.fileContent.mock.calls[0]?.[0]).toBe('/work/report.txt');
    expect(stream.write).toHaveBeenCalledExactlyOnceWith(new TextEncoder().encode('hello'));
    expect(stream.close).toHaveBeenCalledOnce();
    expect(state.statusKey.value).toBe('focus.fileSaved');
    expect(state.opened.value).toBe(false);
    expect(state.info.value).toBeNull();
    expect(state.path.value).toBe('');
  });

  it('cancelling the picker does not fetch or start an alternative download', async () => {
    const { state, api, showSaveFilePicker, anchor } = setup();
    await state.open('/a', '');
    showSaveFilePicker.mockRejectedValueOnce(new DOMException('cancelled', 'AbortError'));
    await state.save();
    expect(api.fileContent).not.toHaveBeenCalled();
    expect(anchor.click).not.toHaveBeenCalled();
    expect(state.errorKey.value).toBe('');
    expect(state.statusKey.value).toBe('');
    expect(state.opened.value).toBe(true);
  });

  it('exposes browser fallback and requires another click if native saving is denied', async () => {
    const { state, api, showSaveFilePicker, anchor } = setup();
    await state.open('/a', '');
    showSaveFilePicker.mockRejectedValueOnce(new DOMException('not allowed', 'SecurityError'));
    await state.save();
    expect(state.nativePicker.value).toBe(false);
    expect(anchor.click).not.toHaveBeenCalled();
    await state.save();
    expect(anchor.click).toHaveBeenCalledOnce();
    expect(api.fileContent).not.toHaveBeenCalled();
    expect(state.statusKey.value).toBe('focus.fileDownloadHandedOff');
    expect(state.opened.value).toBe(false);
  });

  it('rechecks a native browser download without buffering it in JavaScript', async () => {
    const { state, api, anchor } = setup(false);
    await state.open('report.txt', '/work');
    state.name.value = 'final.txt';
    await state.save();
    expect(api.fileInfo.mock.calls[1]?.slice(0, 2)).toEqual(['/work/report.txt', '']);
    expect(api.fileDownloadUrl).toHaveBeenCalledWith('/work/report.txt', 'final.txt');
    expect(anchor.download).toBe('final.txt');
    expect(api.fileContent).not.toHaveBeenCalled();
    expect(state.statusKey.value).toBe('focus.fileDownloadHandedOff');
  });

  it('keeps file errors in the dialog without navigating or claiming success', async () => {
    const { state, api, anchor } = setup(false);
    await state.open('/a', '');
    api.fileInfo.mockRejectedValue(new FocusApiError('missing', { status: 404, code: 'file_not_found' }));
    await state.save();
    expect(state.errorKey.value).toBe('focus.fileNotFound');
    expect(anchor.click).not.toHaveBeenCalled();
    expect(state.statusKey.value).toBe('');
    expect(state.opened.value).toBe(true);
  });

  it('ignores a late metadata response after another link is opened', async () => {
    const { state, api } = setup();
    let finish!: (value: Awaited<ReturnType<FileDownloadApi['fileInfo']>>) => void;
    api.fileInfo.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const first = state.open('/old', '');
    const firstSignal = api.fileInfo.mock.calls[0]?.[2];
    await state.open('/new', '');
    finish({ path: '/old', name: 'old', size: 99 });
    await first;
    expect(firstSignal?.aborted).toBe(true);
    expect(state.info.value?.path).toBe('/work/report.txt');
  });

  it('ignores a picker result after the dialog is closed', async () => {
    const { state, api, showSaveFilePicker, handle } = setup();
    let finish!: (value: typeof handle) => void;
    await state.open('/a', '');
    showSaveFilePicker.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const saving = state.save();
    state.close();
    finish(handle);
    await saving;
    expect(api.fileContent).not.toHaveBeenCalled();
    expect(state.opened.value).toBe(false);
  });

  it('aborts staged writes on failure, without falling back or reporting success', async () => {
    const { state, stream, anchor } = setup();
    await state.open('/a', '');
    stream.write.mockRejectedValueOnce(new Error('disk full'));
    await state.save();
    expect(stream.abort).toHaveBeenCalledOnce();
    expect(stream.close).not.toHaveBeenCalled();
    expect(anchor.click).not.toHaveBeenCalled();
    expect(state.errorKey.value).toBe('focus.fileDownloadFailed');
    expect(state.statusKey.value).toBe('');
  });

  it('cancels a pending transfer and discards partial writes', async () => {
    const controller = new AbortController();
    const { handle, stream } = setup();
    stream.write.mockImplementationOnce(async () => { controller.abort(); });
    await expect(saveFileResponse(handle as unknown as FileSystemFileHandle, new Response('hello'), controller.signal, () => {})).rejects.toThrow();
    expect(stream.abort).toHaveBeenCalledOnce();
    expect(stream.close).not.toHaveBeenCalled();
  });

  it('waits for successful disk close before dismissing the dialog', async () => {
    const { state, stream } = setup();
    let finish!: () => void;
    stream.close.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await state.open('/a', '');
    const saving = state.save();
    await vi.waitFor(() => expect(stream.close).toHaveBeenCalledOnce());
    expect(state.opened.value).toBe(true);
    expect(state.received.value).toBe(5);
    expect(state.statusKey.value).toBe('');
    finish();
    await saving;
    expect(state.opened.value).toBe(false);
    expect(state.statusKey.value).toBe('focus.fileSaved');
  });

  it('keeps failed disk-close attempts open for retry', async () => {
    const { state, stream } = setup();
    stream.close.mockRejectedValueOnce(new Error('close failed'));
    await state.open('/a', '');
    await state.save();
    expect(state.opened.value).toBe(true);
    expect(state.info.value).not.toBeNull();
    expect(state.statusKey.value).toBe('');
    expect(state.errorKey.value).toBe('focus.fileDownloadFailed');
  });

  it('does not close a new file dialog when an older disk close resolves', async () => {
    const { state, stream } = setup();
    let finish!: () => void;
    stream.close.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    await state.open('/a', '');
    const saving = state.save();
    await vi.waitFor(() => expect(stream.close).toHaveBeenCalledOnce());
    await state.open('/b', '');
    finish();
    await saving;
    expect(state.opened.value).toBe(true);
    expect(state.statusKey.value).toBe('');
  });
});

describe('file references and names', () => {
  it.each([
    ['/home/me/report.pdf', '/home/me/report.pdf', undefined],
    ['../report%20%E4%B8%AD%E6%96%87.pdf#L12', '../report 中文.pdf', 12],
    ['/tmp/a.py:12:4', '/tmp/a.py', 12],
    ['report.py:12', 'report.py', 12],
    ['file:///C:/work/a.txt#L2', 'C:/work/a.txt', 2],
    ['C:\\work\\a.txt:10', 'C:\\work\\a.txt', 10],
    ['./a%23b%3Fc.txt', './a#b?c.txt', undefined],
  ])('resolves %s without treating a line reference as part of the file', (href, path, line) => {
    expect(parseLocalFileHref(href)).toEqual({ path, ...(line ? { line } : {}) });
  });
  it.each(['https://example.com/a', '//example.com/a', '#anchor', 'mailto:user@example.com', 'javascript:alert(1)', 'file://other-host/share'])('leaves nonlocal destinations alone: %s', href => {
    expect(parseLocalFileHref(href)).toBeNull();
  });
  it('bounds Unicode names while retaining extensions and protecting Windows names', () => {
    const value = normalizeDownloadFilename('报告'.repeat(200) + '.zip');
    expect(new TextEncoder().encode(value).length).toBeLessThanOrEqual(200);
    expect(value.endsWith('.zip')).toBe(true);
    expect(normalizeDownloadFilename('NUL.txt')).toBe('_NUL.txt');
    expect(normalizeDownloadFilename('archive.tar.gz')).toBe('archive.tar.gz');
    expect(normalizeDownloadFilename(' ../test.txt ')).toBe('-test.txt');
  });
});
