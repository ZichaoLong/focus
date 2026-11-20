import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const id = '167cd970-48fd-4171-9952-cc61c304a106';
const ticket = 'a1e39586-8f3c-4645-83a3-166aba3b67e2';
function memory() {
  const data = new Map<string, string>();
  return { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => data.set(k, v),
    removeItem: (k: string) => data.delete(k) };
}
function setup(instance = id) {
  const win = Object.assign(new EventTarget(), { top: {}, __focusMobile: { version: 1, instance, ticket, features: ['resume', 'save', 'wake'] }, prompt: vi.fn(() => 'ok') });
  win.top = win;
  vi.stubGlobal('window', win);
  vi.stubGlobal('location', new URL('https://site.test/?focusApp=1'));
  return win;
}

describe('negotiated mobile host', () => {
  beforeEach(() => { vi.resetModules(); vi.stubGlobal('localStorage', memory()); vi.stubGlobal('sessionStorage', memory()); });
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
  it('keeps browser tabs, unknown protocols and nested previews on browser storage', async () => {
    const win = setup();
    const host = await import('../src/lib/mobileHost');
    win.top = {};
    await host.negotiateMobileHost();
    expect(host.recoveryStorage()).toBe(sessionStorage);
    win.top = win;
    win.__focusMobile.version = 2;
    vi.useFakeTimers();
    const result = host.negotiateMobileHost();
    await vi.advanceTimersByTimeAsync(2600);
    await result;
    expect(host.hasMobileFeature('save')).toBe(false);
    expect(win.prompt).not.toHaveBeenCalled();
  });
  it('restores presentation across writer rotation and isolates instance ids and tab receipts', async () => {
    setup(); let host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    const scope = host.presentationScope('writer:generation:1:thread:T');
    expect(host.presentationScope('new:generated:1:thread:T')).not.toBe(scope);
    expect(host.presentationScope('next:generation:5:thread:T')).toBe(scope);
    host.recoveryStorage().setItem('locator', 'A');
    expect(sessionStorage.getItem('locator')).toBeNull();
    vi.resetModules(); setup(ticket); host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    expect(host.recoveryStorage().getItem('locator')).toBeNull();
    expect(host.presentationScope('next:generation:5:thread:T')).not.toBe(scope);
  });
  it('restores the reading choice only for the confirmed instance and readable thread', async () => {
    const { ref, effectScope, nextTick } = await import('vue');
    setup();
    let host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    host.rememberMobileReadingThread('thread-A');
    vi.resetModules();
    setup(ticket);
    host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    expect(host.mobileReadingThread()).toBe('');
    vi.resetModules();
    setup();
    host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    const { useFocusReadingMode } = await import('../src/focus/focusReadingMode');
    const scope = effectScope();
    const thread = ref(''), readable = ref(false);
    const mode = scope.run(() => useFocusReadingMode({
      confirmedThread: thread, canEnter: readable, documentAccessAvailable: ref(true), initialized: ref(true),
      meta: ref({}), conversationLoading: ref(false), turns: ref([{}]), dismissSwitcher: vi.fn(), dismissChrome: vi.fn(),
    }))!;
    thread.value = 'thread-A';
    await nextTick();
    expect(mode.readingMode.value).toBe(false);
    readable.value = true;
    await nextTick();
    expect(mode.readingMode.value).toBe(true);
    mode.chooseNormalMode();
    expect(host.mobileReadingThread()).toBe('');
    await nextTick();
    expect(mode.readingMode.value).toBe(false);
    scope.stop();
  });
  it('keeps browser mode local and offers the picker only to a host with tabs', async () => {
    const win = setup();
    const host = await import('../src/lib/mobileHost');
    host.rememberMobileReadingThread('T');
    expect(host.mobileReadingThread()).toBe('');
    await host.negotiateMobileHost();
    host.showMobileInstances();
    expect(win.prompt).not.toHaveBeenCalled();
    win.__focusMobile.features.push('tabs');
    host.showMobileInstances();
    host.showMobileWebChrome(true);
    expect(win.prompt.mock.calls).toEqual([['focus/1/' + ticket + '/instances', ''], ['focus/1/' + ticket + '/chrome', 'web']]);
  });
  it.each([['127.0.0.1', true], ['localhost', true], ['[::1]', true], ['192.168.1.1', false],
    ['localhost.example', false]] as const)('negotiates cleartext only on an exact loopback host: %s', async (name, trusted) => {
    setup();
    vi.stubGlobal('location', new URL('http://' + name + ':8123/?focusApp=1'));
    const host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    expect(host.hasMobileFeature('resume')).toBe(trusted);
  });
  it('delivers exact bounded file chunks and aborts a failed write', async () => {
    const win = setup();
    const host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    expect(host.chooseMobileFile('file.bin')).toEqual({ kind: 'mobile', filename: 'file.bin' });
    const bytes = Uint8Array.from({ length: 65_701 }, (_, i) => i % 251);
    await host.saveMobileFile(new Response(bytes));
    const calls = win.prompt.mock.calls as unknown as [string, string][];
    const chunks = calls.filter(([op]) => op.endsWith('/write')).map(([, data]) => data);
    expect(chunks.every(v => v.length <= 32768)).toBe(true);
    expect(Buffer.concat(chunks.map(data => Buffer.from(data, 'base64')))).toEqual(Buffer.from(bytes));
    win.prompt.mockReturnValueOnce('error');
    await expect(host.saveMobileFile(new Response(bytes))).rejects.toThrow();
    expect(win.prompt).toHaveBeenLastCalledWith('focus/1/' + ticket + '/abort', '');
  });
  it('checkpoints a thread hint once per change in a negotiated root', async () => {
    const win = setup();
    win.__focusMobile.features.push('thread');
    const host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    host.checkpointThread('thread-1');
    host.checkpointThread('thread-1');
    host.checkpointThread('');
    expect(win.prompt.mock.calls).toEqual([['focus/1/' + ticket + '/thread', 'thread-1'], ['focus/1/' + ticket + '/thread', '']]);
  });
  it('holds the mobile print preview in memory and returns to the same document', async () => {
    const win = setup();
    win.__focusMobile.features.push('print');
    const history = { state: { focusSummaryPrint: true }, pushState: vi.fn(), back: vi.fn(() => win.dispatchEvent(new Event('popstate'))) };
    vi.stubGlobal('history', history);
    const host = await import('../src/lib/mobileHost');
    await host.negotiateMobileHost();
    const { openSummaryPrintWindow, mobilePrintPreview, closeMobilePrintPreview } = await import('../src/focus/summaryPrintWindow');
    const preview = openSummaryPrintWindow()!;
    preview.deliver('Complete answer', 'summary.pdf', 'Summary');
    expect(mobilePrintPreview.value?.content).toMatchObject({ markdown: 'Complete answer' });
    expect(history.pushState).toHaveBeenCalledWith({ focusSummaryPrint: true }, '');
    expect(host.printMobileSummary('summary')).toBe(true);
    expect(win.prompt).toHaveBeenCalledWith('focus/1/' + ticket + '/print', 'summary');
    closeMobilePrintPreview();
    expect(mobilePrintPreview.value).toBeNull();
  });
});

describe('whole-document access recovery', () => {
  it('recognizes an HTTP challenge even when the proxy uses a Focus-shaped JSON error', async () => {
    vi.resetModules();
    const win = setup();
    Object.assign(win, { location: new URL('https://site.test/') });
    vi.stubGlobal('sessionStorage', memory());
    const { FocusWebApi } = await import('../src/focus/api');
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
      error: { code: 'unauthorized', message: 'Sign in', details: {} },
    }), { status: 401, headers: { 'WWW-Authenticate': 'Basic realm="entry"' } })));
    try {
      await expect(new FocusWebApi().initialize()).rejects.toMatchObject({ status: 401, code: 'http_401', effectEvidence: 'unknown' });
    } finally { vi.unstubAllGlobals(); }
  });
  it('bounds reload across documents and distinguishes a proxy 401 from a Focus rejection', async () => {
    vi.resetModules();
    vi.stubGlobal('sessionStorage', memory());
    const { reserveDocumentReload, isFocusSessionRejection } = await import('../src/focus/documentRecovery');
    const { FocusApiError } = await import('../src/focus/types');
    expect(reserveDocumentReload(100_000)).toBe(true);
    expect(reserveDocumentReload(100_001)).toBe(false);
    expect(reserveDocumentReload(160_000)).toBe(true);
    expect(isFocusSessionRejection(new FocusApiError('proxy', { status: 401, code: 'http_401' }))).toBe(false);
    expect(isFocusSessionRejection(new FocusApiError('session', { status: 401, code: 'unauthorized' }))).toBe(true);
    expect(isFocusSessionRejection(new FocusApiError('used authorization link', { status: 401, code: 'invalid_bootstrap' }))).toBe(true);
    vi.unstubAllGlobals();
  });
});
