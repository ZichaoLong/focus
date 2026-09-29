import type { SummaryExportRequest } from '../types';
import { normalizeExportFilename, suggestExportFilename } from './exportFilename';
import { normalizeSummaryTitle, titleSummaryMarkdown } from './summaryDocumentTitle';
import { openSummaryPrintWindow } from './summaryPrintWindow';

interface FocusThreadActionClient {
  readonly summaryExporting: { readonly value: boolean };
  readonly threadDataExporting: { readonly value: boolean };
  exportThreadSummary(threadId: string): Promise<Blob | null>;
  exportThreadData(threadId: string): Promise<Blob | null>;
  archiveThread(threadId: string): Promise<boolean>;
}

export interface ExportOptionsRequest {
  format: 'markdown' | 'jsonl';
  suggestedFilename: string;
  suggestedDocumentTitle?: string;
}

export interface ExportOptionsChoice {
  filename: string;
  documentTitle?: string;
}

export interface FocusThreadActionsOptions {
  client: FocusThreadActionClient;
  getThreadTitle(threadId: string): string;
  requestExportOptions(options: ExportOptionsRequest): Promise<ExportOptionsChoice | null>;
  confirm(options: {
    title: string;
    message: string;
    confirmLabel: string;
    cancelLabel: string;
    variant: 'danger';
  }): Promise<boolean>;
  notify(message: string): void;
  translate(key: string): string;
}

type ExportDestination = { kind: 'download' } | { kind: 'file'; handle: FileSystemFileHandle };
type SavePickerWindow = Window & {
  showSaveFilePicker?: (options: {
    suggestedName: string;
    types: { description: string; accept: Record<string, string[]> }[];
  }) => Promise<FileSystemFileHandle>;
};

async function chooseExportDestination(
  filename: string, format: ExportOptionsRequest['format'],
): Promise<ExportDestination | null> {
  const browser = window as SavePickerWindow;
  if (!browser.isSecureContext || typeof browser.showSaveFilePicker !== 'function') {
    return { kind: 'download' };
  }
  try {
    // Still in the naming dialog's confirmation gesture, before any export fetch.
    const handle = await browser.showSaveFilePicker({
      suggestedName: filename,
      types: format === 'markdown'
        ? [{ description: 'Markdown', accept: { 'text/markdown': ['.md'] } }]
        : [{ description: 'JSON Lines', accept: { 'application/x-ndjson': ['.jsonl'] } }],
    });
    return { kind: 'file', handle };
  } catch (error) {
    if (error instanceof DOMException) {
      if (error.name === 'AbortError') return null;
      if (error.name === 'SecurityError' || error.name === 'NotSupportedError') return { kind: 'download' };
    }
    throw error;
  }
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function saveExportBlob(destination: ExportDestination, blob: Blob, filename: string): Promise<void> {
  if (destination.kind === 'download') {
    downloadBlob(blob, filename);
    return;
  }
  // Do not open a writable stream until the complete export is available.
  const stream = await destination.handle.createWritable();
  try {
    await stream.write(blob);
    await stream.close();
  } catch (error) {
    // Discard staged writes where possible, preserving the original failure.
    await stream.abort().catch(() => {});
    throw error;
  }
}

export function createFocusThreadActions(options: FocusThreadActionsOptions) {
  const { client, notify, translate } = options;
  let exportPending = false;

  function exportBusy(): boolean {
    return exportPending || client.summaryExporting.value || client.threadDataExporting.value;
  }

  async function runExport(
    threadId: string,
    load: (id: string) => Promise<Blob | null>,
    format: ExportOptionsRequest['format'],
    messageKeys: { busy: string; preparing: string; complete: string },
  ): Promise<void> {
    if (exportBusy()) {
      notify(translate(messageKeys.busy));
      return;
    }
    exportPending = true;
    try {
      const title = options.getThreadTitle(threadId);
      const documentTitle = normalizeSummaryTitle(title);
      const chosen = await options.requestExportOptions({
        format, suggestedFilename: suggestExportFilename(title, format),
        ...(format === 'markdown' ? { suggestedDocumentTitle: documentTitle } : {}),
      });
      if (chosen === null) return;
      const filename = normalizeExportFilename(chosen.filename, format);
      if (!filename) return;
      if (client.summaryExporting.value || client.threadDataExporting.value) {
        notify(translate(messageKeys.busy));
        return;
      }
      const destination = await chooseExportDestination(filename, format);
      if (destination === null) return;
      if (client.summaryExporting.value || client.threadDataExporting.value) {
        notify(translate(messageKeys.busy));
        return;
      }
      notify(translate(messageKeys.preparing));
      const blob = await load(threadId);
      if (blob === null) {
        notify(translate('focus.exportSaveFailed'));
        return;
      }
      const download = format === 'markdown'
        ? new Blob([titleSummaryMarkdown(await blob.text(), chosen.documentTitle ?? documentTitle)], { type: blob.type })
        : blob;
      await saveExportBlob(destination, download, filename);
      notify(translate(messageKeys.complete));
    } catch {
      notify(translate('focus.exportSaveFailed'));
    } finally {
      exportPending = false;
    }
  }

  async function exportThreadSummary({ threadId, format }: SummaryExportRequest): Promise<void> {
    if (format === 'print') {
      if (exportBusy()) {
        notify(translate('focus.summaryExportBusy'));
        return;
      }
      const title = options.getThreadTitle(threadId);
      const filename = suggestExportFilename(title, 'print');
      const documentTitle = normalizeSummaryTitle(title);
      // Open within the click's user activation, before fetching any history.
      const preview = openSummaryPrintWindow();
      if (!preview) {
        notify(translate('focus.printPopupBlocked'));
        return;
      }
      exportPending = true;
      try {
        const blob = await client.exportThreadSummary(threadId);
        if (blob === null) preview.fail();
        else preview.deliver(await blob.text(), filename, documentTitle);
      } catch {
        preview.fail();
      } finally {
        exportPending = false;
      }
      return;
    }
    return runExport(
      threadId,
      (id) => client.exportThreadSummary(id),
      'markdown',
      {
        busy: 'focus.summaryExportBusy',
        preparing: 'focus.summaryExportPreparing',
        complete: 'focus.summaryExportComplete',
      },
    );
  }

  function exportThreadData(threadId: string): Promise<void> {
    return runExport(
      threadId,
      (id) => client.exportThreadData(id),
      'jsonl',
      {
        busy: 'focus.threadDataExportBusy',
        preparing: 'focus.threadDataExportPreparing',
        complete: 'focus.threadDataExportComplete',
      },
    );
  }

  async function confirmArchiveThread(threadId: string): Promise<void> {
    const approved = await options.confirm({
      title: translate('sidebar.archive'),
      message: translate('sidebar.archiveConfirm'),
      confirmLabel: translate('sidebar.archive'),
      cancelLabel: translate('focus.cancel'),
      variant: 'danger',
    });
    if (approved) await client.archiveThread(threadId);
  }

  return { exportThreadSummary, exportThreadData, confirmArchiveThread };
}
