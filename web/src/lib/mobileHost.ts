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
  if (accept() || !new URLSearchParams(location.search).has('focusApp')) return;
  await new Promise<void>(resolve => {
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
}

export function hasMobileFeature(feature: string): boolean {
  return host?.features.includes(feature) === true;
}

export function mobileInstanceName(): string {
  return typeof host?.name === 'string' ? host.name : '';
}

export function showMobileInstances(): void {
  if (host && hasMobileFeature('tabs')) window.prompt('focus/1/' + host.ticket + '/instances', '');
}

export function showMobileWebChrome(available: boolean): void {
  if (host && hasMobileFeature('tabs')) window.prompt('focus/1/' + host.ticket + '/chrome', available ? 'web' : 'native');
}

export function mobileReadingThread(): string {
  try { return hasMobileFeature('resume') ? recoveryStorage().getItem('focus-web.reading-thread') ?? '' : ''; }
  catch { return ''; }
}

export function rememberMobileReadingThread(thread: string): void {
  if (!hasMobileFeature('resume')) return;
  try {
    if (thread) recoveryStorage().setItem('focus-web.reading-thread', thread);
    else recoveryStorage().removeItem('focus-web.reading-thread');
  } catch { /* Presentation persistence is optional. */ }
}

export function printMobileSummary(filename: string): boolean {
  return !!host && hasMobileFeature('print') && window.prompt('focus/1/' + host.ticket + '/print', filename.slice(0, 255)) === 'ok';
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
  if (!host || !hasMobileFeature('resume') || !composerScope) return composerScope;
  const target = new RegExp('^[^:]+:generation:[0-9]+:((?:thread|draft):.+)$', 's').exec(composerScope)?.[1];
  return target ? 'mobile:' + host.instance + ':' + target : composerScope;
}

// Browser tabs keep independent sessionStorage. A shell has one Web document per
// instance and can resume these same owner records after the renderer disappears.
export function recoveryStorage(): Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> {
  if (!host || !hasMobileFeature('resume')) return sessionStorage;
  const prefix = 'focus-mobile.' + host.instance + '.';
  return {
    getItem: key => localStorage.getItem(prefix + key),
    setItem: (key, value) => localStorage.setItem(prefix + key, value),
    removeItem: key => localStorage.removeItem(prefix + key),
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
