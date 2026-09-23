import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { openSummaryPrintWindow, receiveSummaryPrint } from '../src/focus/summaryPrintWindow';

function mockWindow() {
  const listeners = new Set<(event: MessageEvent) => void>();
  const child = { closed: false, postMessage: vi.fn() };
  const opener = { postMessage: vi.fn() };
  const browser = {
    location: new URL('https://focus.test/?token=secret#rendezvous'),
    history: { replaceState: vi.fn() },
    opener,
    open: vi.fn(() => child),
    setInterval, clearInterval, setTimeout, clearTimeout,
    addEventListener: vi.fn((_type: string, fn: (event: MessageEvent) => void) => listeners.add(fn)),
    removeEventListener: vi.fn((_type: string, fn: (event: MessageEvent) => void) => listeners.delete(fn)),
  };
  vi.stubGlobal('window', browser);
  function message(data: unknown, source: unknown = child, origin = 'https://focus.test') {
    for (const receive of [...listeners]) receive({ data, source, origin } as MessageEvent);
  }
  return { browser, child, opener, message, listeners };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('standalone print handoff', () => {
  it.each([true, false])('only delivers to the exact ready child, content first: %s', (contentFirst) => {
    const { browser, child, message, listeners } = mockWindow();
    const preview = openSummaryPrintWindow()!;
    const url = new URL(browser.open.mock.calls[0]![0] as unknown as string);
    expect(url.search).toBe('?print=summary');
    expect(url.href).not.toContain('secret');
    const ready = { channel: 'focus-summary-print', token: url.hash.slice(1), ready: true };
    message(ready, child, 'https://attacker.test');
    message(ready, {}, 'https://focus.test');
    message({ ...ready, token: 'wrong' });
    if (contentFirst) preview.deliver('Complete original Q&A');
    expect(child.postMessage).not.toHaveBeenCalled();
    message(ready);
    if (!contentFirst) preview.deliver('Complete original Q&A');
    expect(child.postMessage).toHaveBeenCalledExactlyOnceWith({
      channel: 'focus-summary-print', token: ready.token, markdown: 'Complete original Q&A',
    }, 'https://focus.test');
    expect(listeners.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('reports a blocked popup without keeping listeners', () => {
    const { browser, listeners } = mockWindow();
    browser.open.mockReturnValue(null as never);
    expect(openSummaryPrintWindow()).toBeNull();
    expect(listeners.size).toBe(0);
  });

  it.each(['closed', 'timeout'])('releases the handoff after %s and ignores late content', (reason) => {
    const { child, listeners } = mockWindow();
    const preview = openSummaryPrintWindow()!;
    if (reason === 'closed') child.closed = true;
    vi.advanceTimersByTime(90_000);
    preview.deliver('Late');
    expect(child.postMessage).not.toHaveBeenCalled();
    expect(listeners.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('accepts content only from the exact opener, forgets the token and detaches', () => {
    const { browser, opener, message, listeners } = mockWindow();
    const content = vi.fn(); const error = vi.fn();
    receiveSummaryPrint(content, error);
    const data = { channel: 'focus-summary-print', token: 'rendezvous', markdown: '# Q&A' };
    message(data);
    message(data, opener, 'https://attacker.test');
    message({ ...data, token: 'bad' }, opener);
    expect(content).not.toHaveBeenCalled();
    message(data, opener);
    expect(content).toHaveBeenCalledExactlyOnceWith('# Q&A');
    expect(error).not.toHaveBeenCalled();
    expect(browser.history.replaceState).toHaveBeenCalledWith(null, '', '/?print=summary');
    expect(browser.opener).toBeNull();
    expect(listeners.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['expired', 'server', 'direct'])('fails visibly when content is unavailable: %s', (reason) => {
    const { browser, opener, message } = mockWindow();
    if (reason === 'direct') browser.opener = null as never;
    const content = vi.fn(); const error = vi.fn();
    receiveSummaryPrint(content, error);
    if (reason === 'server') message({ channel: 'focus-summary-print', token: 'rendezvous', error: true }, opener);
    if (reason === 'expired') vi.advanceTimersByTime(90_000);
    expect(error).toHaveBeenCalledOnce();
    expect(content).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});
