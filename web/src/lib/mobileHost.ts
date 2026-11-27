import { openMobilePresentation, persistMobilePresentation } from './mobilePresentation';

// The native half installs an offer only in the configured top document.
// No business requests, cookie values or document capabilities cross this boundary.
interface MobileOffer {
  version: number;
  instance: string;
  ticket: string;
  features: string[];
  name?: string;
}
declare global { interface Window {
  __focusMobile?: MobileOffer;
  __focusCanRebuild?: () => boolean;
  __focusSetTabActive?: (active: boolean) => boolean;
  __focusBack?: () => boolean;
} }

let host: MobileOffer | undefined;
const uuid = new RegExp('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$', 'i');

export async function negotiateMobileHost(): Promise<void> {
  if (window !== window.top || location.pathname !== '/') return;
  const loopback = location.protocol === 'http:' && ['127.0.0.1', 'localhost', '[::1]'].includes(location.hostname);
  if (location.protocol !== 'https:' && !loopback) return;
  function accept(): boolean {
    const offer = window.__focusMobile;
    if (offer?.version !== 1 || !uuid.test(offer.instance) || !uuid.test(offer.ticket)
      || !Array.isArray(offer.features)) return false;
    host = offer;
    return true;
  }
  if (!accept() && new URLSearchParams(location.search).has('focusApp')) await new Promise<void>(resolve => {
    const finish = () => {
      clearTimeout(timer);
      window.removeEventListener('focus-host-ready', ready);
      resolve();
    };
    const ready = () => { if (accept()) finish(); };
    const timer = setTimeout(finish, 2500);
    window.addEventListener('focus-host-ready', ready);
    // Ask the host to inspect the top document now, even when subresources
    // delay its navigation-complete callback. This carries no authority.
    console.debug('focus-host-request/1');
  });
  if (host && hasMobileFeature('resume')) await openMobilePresentation(host.instance).catch(() => {});
}

export function hasMobileFeature(feature: string): boolean {
  return host?.features.includes(feature) === true;
}

/** Only actual link activations in the negotiated top document use the guest browser. */
export function installMobileNavigation(back: () => boolean): () => void {
  if (!host || !hasMobileFeature('navigation')) return () => {};
  const ticket = host.ticket;
  function openLink(event: MouseEvent): void {
    if (!event.isTrusted || event.defaultPrevented || event.button !== 0 || !(event.target instanceof Element)) return;
    const link = event.target.closest('a[href]');
    if (!(link instanceof HTMLAnchorElement) || link.hasAttribute('download') || link.protocol !== 'https:'
      || link.origin === location.origin || link.username || link.password) return;
    event.preventDefault();
    event.stopPropagation();
    window.prompt('focus/1/' + ticket + '/external', link.href);
  }
  window.__focusBack = back;
  document.addEventListener('click', openLink, true);
  return () => {
    document.removeEventListener('click', openLink, true);
    if (window.__focusBack === back) delete window.__focusBack;
  };
}

export function mobileInstanceName(): string {
  return typeof host?.name === 'string' ? host.name : '';
}

export function showMobileInstances(): void {
  if (!host || !hasMobileFeature('tabs')) return;
  const scheme = hasMobileFeature('drawer') ? document.documentElement.dataset.colorScheme : '';
  const dark = scheme === 'dark' || (scheme !== 'light' && window.matchMedia?.('(prefers-color-scheme: dark)').matches);
  window.prompt('focus/1/' + host.ticket + '/instances', hasMobileFeature('drawer') ? (dark ? 'dark' : 'light') : '');
}

export function showMobileWebChrome(available: boolean): void {
  if (host && hasMobileFeature('tabs')) window.prompt('focus/1/' + host.ticket + '/chrome', available ? 'web' : 'native');
}

export type MobilePrintReply = 'ok' | 'error' | 'no-reply' | 'unexpected-reply' | 'exception' | 'unavailable';
export type MobilePrintSource = 'webview' | 'native-test';
interface MobilePrintTrace { session: string; attempt: number; source: MobilePrintSource }

export function mobilePrintRecording(action: 'start' | 'stop', session = ''): string | null {
  if (!host || !hasMobileFeature('print-diagnostics')) return null;
  try {
    const value = action === 'start' && hasMobileFeature('print-job-diagnostics') ? 'print-job-diagnostics' : session;
    const reply = window.prompt('focus/1/' + host.ticket + '/print-diag-' + action, value);
    return reply && (action === 'stop' || uuid.test(reply)) ? reply : null;
  } catch { return null; }
}

export function printMobileSummary(filename: string, observe?: (reply: MobilePrintReply) => void, trace?: MobilePrintTrace): boolean {
  let result: MobilePrintReply = 'unavailable';
  if (host && hasMobileFeature('print') && (!trace || hasMobileFeature('print-diagnostics'))) {
    try {
      const name = filename.slice(0, 255);
      const op = trace ? 'print-diag-run' : 'print';
      const value = trace ? JSON.stringify({ ...trace, name: trace.source === 'webview' ? name : undefined }) : name;
      const reply = window.prompt('focus/1/' + host.ticket + '/' + op, value);
      if (reply === 'ok' || reply === 'error') result = reply;
      else result = reply === null ? 'no-reply' : 'unexpected-reply';
    } catch { result = 'exception'; }
  }
  observe?.(result);
  return result === 'ok';
}

let lastThreadHint: string | undefined;
export function checkpointThread(thread: string): void {
  if (!host || !hasMobileFeature('resume') || lastThreadHint === thread) return;
  try {
    recoveryStorage().setItem('focus-web.last-thread', thread);
    if (hasMobileFeature('thread') && window.prompt('focus/1/' + host.ticket + '/thread', thread) !== 'ok') return;
    lastThreadHint = thread;
  } catch { /* An unavailable checkpoint cannot block Web navigation. */ }
}

// Unsent text and visual bookmarks may follow the confirmed thread/workspace
// across writer reissuance. Attachment tokens and submission scopes never do.
export function presentationScope(composerScope: string | undefined): string | undefined {
  if (!composerScope) return composerScope;
  const match = new RegExp('^([^:]+):generation:[0-9]+:((?:thread|draft):.+)$', 's').exec(composerScope);
  if (!match) return composerScope;
  if (host && hasMobileFeature('resume')) return 'mobile:' + host.instance + ':' + match[2];
  // Unsent thread text belongs to this browser client across navigation. Keep
  // workspace drafts and all server-signed attachment scopes generation-bound.
  return match[2]!.startsWith('thread:') ? 'browser:' + match[1] + ':' + match[2] : composerScope;
}

// Browser tabs keep independent sessionStorage. A shell has one Web document per
// instance and can resume these same owner records after the renderer disappears.
export function recoveryStorage(): Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> {
  if (!host || !hasMobileFeature('resume')) return sessionStorage;
  const prefix = 'focus-mobile.' + host.instance + '.';
  return {
    getItem: key => localStorage.getItem(prefix + key),
    setItem: (key, value) => { localStorage.setItem(prefix + key, value); persistMobilePresentation(prefix + key, value); },
    removeItem: key => { localStorage.removeItem(prefix + key); persistMobilePresentation(prefix + key, null); },
  };
}

function requestFile(operation: string, value = ''): string | null {
  if (!host || !hasMobileFeature('save')) throw new Error('File picker unavailable.');
  // Both platforms support completing a JS prompt after the native picker or
  // write finishes. The reply supplies backpressure, one bounded chunk at a time.
  const reply = window.prompt('focus/1/' + host.ticket + '/' + operation, value);
  if (reply === 'error') throw new Error('File write failed.');
  return reply;
}

export interface MobileFileDestination {
  kind: 'mobile';
  filename: string;
}

export function chooseMobileFile(filename: string): MobileFileDestination | null {
  if (requestFile('choose', filename) !== 'ok') return null;
  return { kind: 'mobile', filename };
}

export async function saveMobileFile(response: Response, signal?: AbortSignal, progress?: (bytes: number) => void): Promise<void> {
  const reader = response.body?.getReader();
  let received = 0;
  try {
    if (!reader) throw new Error('Missing file content.');
    for (;;) {
      signal?.throwIfAborted();
      const result = await reader.read();
      if (result.done) break;
      for (let start = 0; start < result.value.length; start += 24576) {
        signal?.throwIfAborted();
        const chunk = result.value.subarray(start, start + 24576);
        if (requestFile('write', btoa(String.fromCharCode(...chunk))) !== 'ok') throw new Error('File write failed.');
        received += chunk.length;
        progress?.(received);
      }
    }
    signal?.throwIfAborted();
    if (requestFile('finish') !== 'ok') throw new Error('File save failed.');
  } catch (error) {
    cancelMobileFile();
    throw error;
  } finally {
    await reader?.cancel().catch(() => {});
    reader?.releaseLock();
  }
}

export function cancelMobileFile(): void { requestFile('abort'); }

export function mobileApkRequest(action: 'info' | 'begin' | 'write' | 'finish' | 'save' | 'abort', value = ''): string {
  if (!host || !hasMobileFeature('android-update')) throw new Error('Android installer unavailable');
  const reply = window.prompt('focus/1/' + host.ticket + '/apk-' + action, value);
  if (reply === null || reply.startsWith('error')) throw new Error(reply?.slice(6) || 'Android installer unavailable');
  return reply;
}

/** Native storage accepts versioned operations only in the elected Focus root. */
export function mobileRecords(op: string, data: object = {}): string | null {
  if (!host || !hasMobileFeature('records-v1')) return null;
  try { return window.prompt('focus/1/' + host.ticket + '/records-' + op, JSON.stringify(data)); }
  catch { return null; }
}
