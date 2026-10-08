/** Shared native save-picker policy; callers own content and fallback UX. */
export type FileDestination = { kind: 'download' } | { kind: 'file'; handle: FileSystemFileHandle };
type FilePickerType = { description: string; accept: Record<string, string[]> };
type SavePickerWindow = Window & {
  showSaveFilePicker?: (options: {
    suggestedName: string;
    types?: FilePickerType[];
  }) => Promise<FileSystemFileHandle>;
};

export function canChooseFileDestination(): boolean {
  if (typeof window === 'undefined') return false;
  const browser = window as SavePickerWindow;
  return !!browser.isSecureContext && typeof browser.showSaveFilePicker === 'function';
}

export async function chooseFileDestination(
  filename: string, types?: FilePickerType[],
): Promise<FileDestination | null> {
  const browser = window as SavePickerWindow;
  if (!canChooseFileDestination()) return { kind: 'download' };
  try {
    // Must run inside the confirmation gesture, before any network read.
    const handle = await browser.showSaveFilePicker!({ suggestedName: filename, ...(types ? { types } : {}) });
    return { kind: 'file', handle };
  } catch (error) {
    if (error instanceof DOMException) {
      if (error.name === 'AbortError') return null;
      if (error.name === 'SecurityError' || error.name === 'NotSupportedError') return { kind: 'download' };
    }
    throw error;
  }
}

/** Stream a response to staged disk writes, with cancellation and backpressure. */
export async function saveFileResponse(
  handle: FileSystemFileHandle, response: Response, signal: AbortSignal,
  progress: (bytes: number) => void,
): Promise<void> {
  if (!response.body) throw new Error('Missing file content.');
  const reader = response.body.getReader();
  let stream: FileSystemWritableFileStream | undefined;
  try {
    signal.throwIfAborted();
    stream = await handle.createWritable();
    signal.throwIfAborted();
    let received = 0;
    for (;;) {
      signal.throwIfAborted();
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      await stream.write(value);
      received += value.byteLength;
      progress(received);
    }
    await stream.close();
  } catch (error) {
    await stream?.abort().catch(() => {});
    throw error;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
