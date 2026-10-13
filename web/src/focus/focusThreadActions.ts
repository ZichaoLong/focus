import { chooseFileDestination, type FileDestination } from './browserFileSave';
import type { SummaryExportRequest } from '../types';
import type { FocusSummaryExportSelection } from './types';
import { downloadBlob } from '../lib/download';
import { normalizeExportFilename, suggestExportFilename } from './exportFilename';
import { normalizeSummaryTitle, titleSummaryMarkdown } from './summaryDocumentTitle';
import { openSummaryPrintWindow } from './summaryPrintWindow';

interface FocusThreadActionClient {
  readonly summaryExporting: { readonly value: boolean };
  readonly threadDataExporting: { readonly value: boolean };
  readonly errorMessage?: { readonly value: string };
  exportThreadSummary(threadId: string, selection?: FocusSummaryExportSelection): Promise<Blob | null>;
  exportThreadData(threadId: string): Promise<Blob | null>;
  archiveThread(threadId: string): Promise<boolean>;
}

export interface ExportOptionsRequest {
  format: 'markdown' | 'jsonl' | 'print';
  threadId: string;
  suggestedFilename: string;
  suggestedDocumentTitle?: string;
  /** Invoked synchronously by the dialog's submit gesture, before resolving. */
  onConfirm?: () => boolean;
}

export interface ExportOptionsChoice {
  filename: string;
  documentTitle?: string;
  selection?: FocusSummaryExportSelection;
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

async function saveExportBlob(destination: FileDestination, blob: Blob, filename: string): Promise<void> {
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
    load: (id: string, selection?: FocusSummaryExportSelection) => Promise<Blob | null>,
    format: 'markdown' | 'jsonl',
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
        format, threadId, suggestedFilename: suggestExportFilename(title, format),
        ...(format === 'markdown' ? { suggestedDocumentTitle: documentTitle } : {}),
      });
      if (chosen === null) return;
      const filename = normalizeExportFilename(chosen.filename, format);
      if (!filename) return;
      if (client.summaryExporting.value || client.threadDataExporting.value) {
        notify(translate(messageKeys.busy));
        return;
      }
      const destination = await chooseFileDestination(filename, format === 'markdown'
        ? [{ description: 'Markdown', accept: { 'text/markdown': ['.md'] } }]
        : [{ description: 'JSON Lines', accept: { 'application/x-ndjson': ['.jsonl'] } }]);
      if (destination === null) return;
      if (client.summaryExporting.value || client.threadDataExporting.value) {
        notify(translate(messageKeys.busy));
        return;
      }
      notify(translate(messageKeys.preparing));
      const blob = await load(threadId, chosen.selection);
      if (blob === null) {
        notify(client.errorMessage?.value || translate('focus.exportSaveFailed'));
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
      exportPending = true;
      const print = { preview: null as ReturnType<typeof openSummaryPrintWindow> };
      try {
        const chosen = await options.requestExportOptions({
          format, threadId, suggestedFilename: filename, suggestedDocumentTitle: documentTitle,
          onConfirm: () => {
            print.preview = openSummaryPrintWindow();
            if (!print.preview) notify(translate('focus.printPopupBlocked'));
            return print.preview !== null;
          },
        });
        if (!chosen || !print.preview) return;
        if (client.summaryExporting.value || client.threadDataExporting.value) {
          print.preview.fail();
          notify(translate('focus.summaryExportBusy'));
          return;
        }
        const blob = await client.exportThreadSummary(threadId, chosen.selection);
        if (blob === null) {
          print.preview.fail();
          notify(client.errorMessage?.value || translate('focus.exportSaveFailed'));
        }
        else print.preview.deliver(await blob.text(), filename, normalizeSummaryTitle(chosen.documentTitle ?? documentTitle));
      } catch {
        print.preview?.fail();
      } finally {
        exportPending = false;
      }
      return;
    }
    return runExport(
      threadId,
      (id, selection) => client.exportThreadSummary(id, selection),
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
