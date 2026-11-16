import { effectScope, nextTick } from 'vue';
import { afterEach, expect, it, vi } from 'vitest';
import { resolve, basename } from 'node:path';
import { createFileDownload, type FileDownloadApi } from '../src/focus/fileDownload';
import { createFilePreview } from '../src/focus/filePreview';
import { createFilePreviewNavigation } from '../src/focus/filePreviewNavigation';
import { FocusApiError } from '../src/focus/types';

const scopes: ReturnType<typeof effectScope>[] = [];
afterEach(() => { scopes.splice(0).forEach(scope => scope.stop()); vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const view = { sourceMode: false, wrapped: true, scrollTop: 540, scrollLeft: 12 };
function setup() {
  vi.stubGlobal('window', { isSecureContext: false });
  const api = {
    fileInfo: vi.fn<FileDownloadApi['fileInfo']>(async (path, cwd) => ({ path: resolve(cwd || '/', path), name: basename(path), size: 20 })),
    fileContent: vi.fn<FileDownloadApi['fileContent']>(async path => new Response(`# ${path}`)),
    fileDownloadUrl: vi.fn<FileDownloadApi['fileDownloadUrl']>(() => '/download'),
  };
  const scope = effectScope(); scopes.push(scope);
  const state = scope.run(() => {
    const download = createFileDownload(api), preview = createFilePreview(api);
    return { download, preview, navigation: createFilePreviewNavigation(download, preview) };
  })!;
  async function open(path = '/work/docs/index.md') { await state.navigation.open(path, '/work'); await state.navigation.showPreview(); }
  async function follow(path: string) { await state.navigation.openLinkedFile({ path }, view); await state.navigation.showPreview(); }
  return { api, ...state, open, follow };
}

it('returns directly to the latest parent contents with its position and original resolved path', async () => {
  const { api, navigation, preview, download, open, follow } = setup();
  await open();
  await navigation.openLinkedFile({ path: 'nested/chapter.md', anchor: 'section' }, view);
  expect(preview.content.value).toBeNull();
  expect(api.fileContent).toHaveBeenCalledTimes(1);
  expect(api.fileInfo.mock.calls.at(-1)?.slice(0, 2)).toEqual(['nested/chapter.md', '/work/docs/']);
  await navigation.showPreview();
  await follow('../picture.txt');
  await navigation.back();
  expect(preview.file.value?.path).toBe('/work/docs/nested/chapter.md');
  expect(preview.anchor.value).toBe('section');
  api.fileContent.mockResolvedValueOnce(new Response('# Updated directory'));
  await navigation.back();
  expect(api.fileInfo.mock.calls.at(-1)?.slice(0, 2)).toEqual(['/work/docs/index.md', '']);
  expect(preview.content.value?.text).toBe('# Updated directory');
  expect(navigation.restoreView.value).toEqual(view);
  expect(download.opened.value).toBe(false);
  expect(navigation.canGoBack.value).toBe(false);
  navigation.restored();
  expect(navigation.restoreView.value).toBeNull();
});

it('keeps a route back from missing, unsupported and newly oversized files', async () => {
  const { api, navigation, preview, download, open } = setup();
  await open();
  api.fileInfo.mockRejectedValueOnce(new FocusApiError('missing', { status: 404, code: 'file_not_found' }));
  await navigation.openLinkedFile({ path: 'missing.md' }, view);
  expect(download.errorKey.value).toBe('focus.fileNotFound');
  await navigation.back();
  expect(preview.file.value?.name).toBe('index.md');
  await navigation.openLinkedFile({ path: 'archive.zip' }, view);
  expect(api.fileContent.mock.calls.map(call => call[0])).not.toContain('/work/docs/archive.zip');
  await navigation.back();
  await navigation.openLinkedFile({ path: 'child.md' }, view);
  await navigation.showPreview();
  const reads = api.fileContent.mock.calls.length;
  api.fileInfo.mockResolvedValueOnce({ path: '/work/docs/index.md', name: 'index.md', size: 2 * 1024 * 1024 });
  await navigation.back();
  expect(preview.errorKey.value).toBe('focus.filePreviewTooLarge');
  expect(api.fileContent).toHaveBeenCalledTimes(reads);
});

it('fences late metadata when another back action or close supersedes a pending return', async () => {
  const { api, navigation, preview, download, open, follow } = setup();
  await open(); await follow('chapter.md'); await follow('leaf.md');
  let finish!: (value: Awaited<ReturnType<FileDownloadApi['fileInfo']>>) => void;
  api.fileInfo.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const first = navigation.back();
  const signal = api.fileInfo.mock.calls.at(-1)?.[2];
  await navigation.back();
  finish({ path: '/work/docs/chapter.md', name: 'chapter.md', size: 20 });
  await first;
  expect(signal?.aborted).toBe(true);
  expect(preview.file.value?.name).toBe('index.md');
  await follow('leaf.md');
  api.fileInfo.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const closing = navigation.back();
  navigation.closeAll();
  finish({ path: '/work/docs/index.md', name: 'index.md', size: 20 });
  await closing;
  expect(download.opened.value || preview.opened.value).toBe(false);
  expect(navigation.canGoBack.value).toBe(false);
});

it('aborts a child body stream when returning without leaking its partial contents', async () => {
  const { api, navigation, preview, open } = setup();
  await open();
  await navigation.openLinkedFile({ path: 'slow.md' }, view);
  const cancel = vi.fn();
  api.fileContent.mockResolvedValueOnce(new Response(new ReadableStream({
    start(controller) { controller.enqueue(new TextEncoder().encode('# Partial child')); }, cancel,
  })));
  const reading = navigation.showPreview();
  await nextTick();
  await navigation.back();
  await reading;
  expect(cancel).toHaveBeenCalledOnce();
  expect(preview.content.value?.text).toBe('# /work/docs/index.md');
});

it('keeps only twenty previous files and resets the trail on close or a new conversation link', async () => {
  const { navigation, preview, open, follow } = setup();
  await open('/work/0.md');
  for (let i = 1; i <= 22; i++) await follow(`${i}.md`);
  let steps = 0;
  while (navigation.canGoBack.value) { await navigation.back(); steps++; }
  expect(steps).toBe(20);
  expect(preview.file.value?.name).toBe('2.md');
  await follow('leaf.md');
  navigation.close();
  expect(navigation.canGoBack.value).toBe(false);
  await open(); await follow('leaf.md');
  await open('/other/new.md');
  expect(navigation.canGoBack.value).toBe(false);
});

it('does not record download overlays and clears the trail when the last info form closes after saving', async () => {
  const { navigation, preview, download, open, follow } = setup();
  await open(); await follow('leaf.md');
  const content = preview.content.value;
  navigation.showDownload();
  await nextTick();
  navigation.close();
  expect(preview.content.value).toBe(content);
  expect(navigation.canGoBack.value).toBe(true);
  await navigation.back();
  expect(preview.file.value?.name).toBe('index.md');
  await navigation.openLinkedFile({ path: 'archive.zip' }, view);
  download.close();
  await nextTick();
  expect(navigation.canGoBack.value).toBe(false);
});
