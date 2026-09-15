interface FocusThreadActionClient {
  readonly summaryExporting: { readonly value: boolean };
  readonly threadDataExporting: { readonly value: boolean };
  exportThreadSummary(threadId: string): Promise<Blob | null>;
  exportThreadData(threadId: string): Promise<Blob | null>;
  archiveThread(threadId: string): Promise<boolean>;
}

interface FocusThreadActionsOptions {
  client: FocusThreadActionClient;
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

const SUMMARY_EXPORT_FILENAME = 'codex-conversation-summary.md';
const THREAD_DATA_EXPORT_FILENAME = 'codex-thread-data.jsonl';

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

export function createFocusThreadActions(options: FocusThreadActionsOptions) {
  const { client, notify, translate } = options;

  async function runExport(
    threadId: string,
    load: (id: string) => Promise<Blob | null>,
    filename: string,
    messageKeys: { busy: string; preparing: string; complete: string },
  ): Promise<void> {
    if (client.summaryExporting.value || client.threadDataExporting.value) {
      notify(translate(messageKeys.busy));
      return;
    }
    notify(translate(messageKeys.preparing));
    const blob = await load(threadId);
    if (blob === null) return;
    downloadBlob(blob, filename);
    notify(translate(messageKeys.complete));
  }

  function exportThreadSummary(threadId: string): Promise<void> {
    return runExport(
      threadId,
      (id) => client.exportThreadSummary(id),
      SUMMARY_EXPORT_FILENAME,
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
      THREAD_DATA_EXPORT_FILENAME,
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
