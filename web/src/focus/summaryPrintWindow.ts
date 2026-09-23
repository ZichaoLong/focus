/** Ephemeral, same-origin handoff to the standalone Q&A print document. */
const CHANNEL = 'focus-summary-print';
const HANDOFF_TIMEOUT_MS = 90_000;

type PrintPayload = { markdown: string } | { error: true };

export function openSummaryPrintWindow(): {
  deliver(markdown: string): void;
  fail(): void;
} | null {
  const token = [...crypto.getRandomValues(new Uint8Array(16))]
    .map((byte) => byte.toString(16).padStart(2, '0')).join('');
  const url = new URL(window.location.href);
  url.search = '?print=summary';
  url.hash = token;
  const child = window.open(url.href, '_blank');
  if (!child) return null;
  let ready = false;
  let finished = false;
  let payload: PrintPayload | null = null;

  function cleanup(): void {
    finished = true;
    window.removeEventListener('message', receive);
    window.clearInterval(timer);
  }
  function send(): void {
    if (finished || !ready || !payload || child!.closed) return;
    child!.postMessage({ channel: CHANNEL, token, ...payload }, url.origin);
    cleanup();
    payload = null;
  }
  function receive(event: MessageEvent): void {
    if (event.origin !== url.origin || event.source !== child) return;
    if (event.data?.channel !== CHANNEL || event.data?.token !== token || event.data?.ready !== true) return;
    ready = true;
    send();
  }
  const deadline = Date.now() + HANDOFF_TIMEOUT_MS;
  const timer = window.setInterval(() => {
    if (child.closed || Date.now() >= deadline) {
      cleanup();
      payload = null;
    }
  }, 1000);
  window.addEventListener('message', receive);
  return {
    deliver(markdown) { if (!finished) { payload = { markdown }; send(); } },
    fail() { if (!finished) { payload = { error: true }; send(); } },
  };
}

export function receiveSummaryPrint(
  onContent: (markdown: string) => void,
  onError: () => void,
): () => void {
  const token = window.location.hash.slice(1);
  const opener = window.opener as Window | null;
  // The URL contains neither conversation content nor credentials. Remove the
  // one-use rendezvous ID so a refreshed/shared URL cannot replay the export.
  window.history.replaceState(null, '', `${window.location.pathname}?print=summary`);
  if (!token || !opener) {
    onError();
    return () => {};
  }
  const origin = window.location.origin;
  function cleanup(): void {
    window.clearTimeout(timer);
    window.removeEventListener('message', receive);
    window.opener = null;
  }
  function receive(event: MessageEvent): void {
    if (event.origin !== origin || event.source !== opener) return;
    if (event.data?.channel !== CHANNEL || event.data?.token !== token) return;
    if (typeof event.data.markdown === 'string') {
      cleanup();
      onContent(event.data.markdown);
    } else if (event.data.error === true) {
      cleanup();
      onError();
    }
  }
  const timer = window.setTimeout(() => { cleanup(); onError(); }, HANDOFF_TIMEOUT_MS);
  window.addEventListener('message', receive);
  opener.postMessage({ channel: CHANNEL, token, ready: true }, origin);
  return cleanup;
}
