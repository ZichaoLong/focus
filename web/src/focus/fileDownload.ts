import { computed, ref, shallowRef } from 'vue';
import type { FocusWebApiPort } from './api';
import { canChooseFileDestination, chooseFileDestination, saveFileResponse } from './browserFileSave';
import { normalizeDownloadFilename } from './exportFilename';
import { FocusApiError, type FocusFileInfo } from './types';

export type FileDownloadApi = Pick<FocusWebApiPort, 'fileInfo' | 'fileContent' | 'fileDownloadUrl'>;

export function fileDownloadErrorKey(error: unknown): string {
  if (error instanceof FocusApiError) {
    const keys: Record<string, string> = {
      file_not_found: 'focus.fileNotFound',
      file_not_regular: 'focus.fileNotRegular',
      file_unreadable: 'focus.fileUnreadable',
      file_base_required: 'focus.fileBaseRequired',
      file_unavailable: 'focus.fileUnavailablePath',
      invalid_file_request: 'focus.fileUnavailablePath',
      unauthorized: 'focus.fileLoginRequired',
    };
    return keys[error.code] ?? 'focus.fileDownloadFailed';
  }
  return 'focus.fileDownloadFailed';
}

export function formatFileSize(bytes: number): string {
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) { bytes /= 1024; index += 1; }
  return `${index ? bytes.toFixed(1) : bytes} ${units[index]}`;
}

export function createFileDownload(api: FileDownloadApi) {
  const opened = ref(false);
  const path = ref('');
  const info = shallowRef<FocusFileInfo | null>(null);
  const name = ref('');
  const filename = computed(() => normalizeDownloadFilename(name.value));
  const loading = ref(false);
  const busy = ref(false);
  const errorKey = ref('');
  const statusKey = ref('');
  const received = ref(0);
  const nativePicker = ref(canChooseFileDestination());
  let operation: AbortController | null = null;

  function close(): void {
    operation?.abort();
    operation = null;
    opened.value = false;
    loading.value = false;
    busy.value = false;
    info.value = null;
    path.value = '';
    name.value = '';
    errorKey.value = '';
    statusKey.value = '';
    received.value = 0;
  }

  async function open(filePath: string, cwd: string): Promise<void> {
    close();
    const controller = new AbortController();
    operation = controller;
    opened.value = true;
    path.value = filePath;
    name.value = '';
    errorKey.value = '';
    statusKey.value = '';
    received.value = 0;
    loading.value = true;
    nativePicker.value = canChooseFileDestination();
    try {
      const result = await api.fileInfo(filePath, cwd, controller.signal);
      if (controller.signal.aborted) return;
      info.value = result;
      path.value = result.path;
      name.value = result.name;
    } catch (error) {
      if (!controller.signal.aborted) errorKey.value = fileDownloadErrorKey(error);
    } finally {
      if (!controller.signal.aborted) loading.value = false;
    }
  }

  async function save(): Promise<void> {
    const target = info.value;
    const saveName = filename.value;
    if (!target || !saveName || loading.value || busy.value) return;
    const controller = new AbortController();
    operation = controller;
    busy.value = true;
    errorKey.value = '';
    statusKey.value = '';
    received.value = 0;
    try {
      const destination = nativePicker.value ? await chooseFileDestination(saveName) : { kind: 'download' as const };
      if (destination === null || controller.signal.aborted) return;
      if (destination.kind === 'download') {
        if (nativePicker.value) {
          // Capability can be present but unavailable in this context. A second
          // explicit click accepts the newly disclosed browser-download path.
          nativePicker.value = false;
          return;
        }
        await api.fileInfo(target.path, '', controller.signal);
        if (controller.signal.aborted) return;
        const anchor = document.createElement('a');
        anchor.href = api.fileDownloadUrl(target.path, saveName);
        anchor.download = saveName;
        anchor.target = '_blank';
        anchor.rel = 'noopener';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        close();
        statusKey.value = 'focus.fileDownloadHandedOff';
      } else {
        const response = await api.fileContent(target.path, controller.signal);
        await saveFileResponse(destination.handle, response, controller.signal, (bytes) => {
          if (!controller.signal.aborted) received.value = bytes;
        });
        if (!controller.signal.aborted) {
          close();
          statusKey.value = 'focus.fileSaved';
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) errorKey.value = fileDownloadErrorKey(error);
    } finally {
      if (!controller.signal.aborted) busy.value = false;
    }
  }
  return { opened, path, info, name, filename, loading, busy, errorKey, statusKey, received, nativePicker, open, close, save };
}
