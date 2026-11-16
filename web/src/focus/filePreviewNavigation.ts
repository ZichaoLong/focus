/** Own the bounded preview trail; reads and resource lifetimes stay with download/preview owners. */
import { computed, shallowRef, watch } from 'vue';
import type { FilePreviewRequest } from '../types';
import type { createFileDownload } from './fileDownload';
import type { FilePreviewState } from './filePreview';
import type { FilePreviewViewState } from './filePreviewViewState';

export const FILE_PREVIEW_HISTORY_LIMIT = 20;
interface PreviousPreview extends FilePreviewRequest {
  view: FilePreviewViewState;
}

export function createFilePreviewNavigation(download: ReturnType<typeof createFileDownload>, preview: FilePreviewState) {
  const previous = shallowRef<PreviousPreview[]>([]);
  const restoreView = shallowRef<FilePreviewViewState | null>(null);
  const canGoBack = computed(() => previous.value.length > 0);
  let line: number | undefined, anchor: string | undefined;
  let generation = 0;

  function clear(): void {
    generation++;
    previous.value = [];
    restoreView.value = null;
  }
  function closeAll(): void {
    clear(); download.close(); preview.close();
  }
  function close(): void {
    // A save form overlays the current preview without adding a navigation step.
    if (download.opened.value && preview.opened.value) download.close();
    else closeAll();
  }
  function inspect(path: string, cwd: string, targetLine?: number, targetAnchor?: string): Promise<void> {
    generation++;
    restoreView.value = null;
    preview.close();
    line = targetLine; anchor = targetAnchor;
    return download.open(path, cwd);
  }
  function open(path: string, cwd: string, targetLine?: number, targetAnchor?: string): Promise<void> {
    clear();
    return inspect(path, cwd, targetLine, targetAnchor);
  }
  function openLinkedFile(target: FilePreviewRequest, view: FilePreviewViewState): Promise<void> {
    const file = preview.file.value;
    if (!file) return Promise.resolve();
    previous.value = [...previous.value, { path: file.path, line: preview.line.value, anchor: preview.anchor.value, view }]
      .slice(-FILE_PREVIEW_HISTORY_LIMIT);
    const separator = Math.max(file.path.lastIndexOf('/'), file.path.lastIndexOf('\\'));
    return inspect(target.path, file.path.slice(0, separator + 1), target.line, target.anchor);
  }
  function showPreview(view: FilePreviewViewState | null = null): Promise<void> {
    const file = download.info.value;
    if (!file) return Promise.resolve();
    restoreView.value = view;
    const reading = preview.open(file, line, anchor);
    download.close();
    return reading;
  }
  async function back(): Promise<void> {
    const entry = previous.value.at(-1);
    if (!entry) return;
    previous.value = previous.value.slice(0, -1);
    const inspecting = inspect(entry.path, '', entry.line, entry.anchor);
    const request = generation;
    await inspecting;
    if (request !== generation || !download.info.value) return;
    // Back is an explicit request to read the latest file, including fresh size checks.
    await showPreview(entry.view);
  }
  function showDownload(): void {
    if (preview.file.value) void download.open(preview.file.value.path, '');
  }
  // A successful save can close the last info form without an explicit close action.
  watch([download.opened, preview.opened], ([infoOpen, previewOpen]) => {
    if (!infoOpen && !previewOpen) clear();
  });

  return { canGoBack, restoreView, open, openLinkedFile, showPreview, back, showDownload, close, closeAll,
    restored: () => { restoreView.value = null; } };
}
