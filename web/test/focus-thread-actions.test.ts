import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFocusThreadActions } from '../src/focus/focusThreadActions';
import { openSummaryPrintWindow } from '../src/focus/summaryPrintWindow';

vi.mock('../src/focus/summaryPrintWindow', () => ({ openSummaryPrintWindow: vi.fn() }));
afterEach(() => vi.resetAllMocks());

function setup() {
  const preview = { deliver: vi.fn(), fail: vi.fn() };
  vi.mocked(openSummaryPrintWindow).mockReturnValue(preview);
  const client = {
    summaryExporting: { value: false }, threadDataExporting: { value: false },
    exportThreadSummary: vi.fn(async (): Promise<Blob | null> => new Blob(['Full history'])),
    exportThreadData: vi.fn(), archiveThread: vi.fn(),
  };
  const notify = vi.fn();
  return { preview, client, notify, actions: createFocusThreadActions({ client, notify, translate: (key) => key, confirm: vi.fn() }) };
}

describe('Q&A print action', () => {
  it('opens synchronously before fetching the complete export and never claims a saved PDF', async () => {
    const { client, preview, actions, notify } = setup();
    client.exportThreadSummary.mockImplementation(async () => {
      expect(openSummaryPrintWindow).toHaveBeenCalledOnce();
      return new Blob(['Full history']);
    });
    await actions.exportThreadSummary({ threadId: 'not-the-active-thread', format: 'print' });
    expect(client.exportThreadSummary).toHaveBeenCalledExactlyOnceWith('not-the-active-thread');
    expect(preview.deliver).toHaveBeenCalledExactlyOnceWith('Full history');
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
});
