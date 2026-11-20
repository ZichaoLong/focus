/** Ephemeral, same-origin handoff to the standalone Q&A print document. */
import { shallowReactive, shallowRef } from 'vue';
import { hasMobileFeature } from '../lib/mobileHost';
import { DEFAULT_SUMMARY_TITLE } from './summaryDocumentTitle';

const CHANNEL = 'focus-summary-print';
const HANDOFF_TIMEOUT_MS = 90_000;

export type PrintPayload = { markdown: string; suggestedFilename: string; documentTitle: string } | { error: true };
export const mobilePrintPreview = shallowRef<{ content: PrintPayload | null } | null>(null);

export function closeMobilePrintPreview(): void {
  if (mobilePrintPreview.value && history.state?.focusSummaryPrint) history.back();
}

export function openSummaryPrintWindow(): {
  deliver(markdown: string, suggestedFilename: string, documentTitle: string): void;
  fail(): void;
} | null {
  if (hasMobileFeature('print')) {
    if (mobilePrintPreview.value) return null;
    const preview = shallowReactive<{ content: PrintPayload | null }>({ content: null });
    history.pushState({ ...history.state, focusSummaryPrint: true }, '');
    mobilePrintPreview.value = preview;
    window.addEventListener('popstate', () => { mobilePrintPreview.value = null; }, { once: true });
    return {
      deliver(markdown, suggestedFilename, documentTitle) { preview.content = { markdown, suggestedFilename, documentTitle }; },
      fail() { preview.content = { error: true }; },
    };
  }
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
    deliver(markdown, suggestedFilename, documentTitle) { if (!finished) { payload = { markdown, suggestedFilename, documentTitle }; send(); } },
    fail() { if (!finished) { payload = { error: true }; send(); } },
  };
}

export function receiveSummaryPrint(
  onContent: (markdown: string, suggestedFilename: string, documentTitle: string) => void,
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
      onContent(event.data.markdown, typeof event.data.suggestedFilename === 'string'
        ? event.data.suggestedFilename : 'codex-conversation-summary.pdf',
      typeof event.data.documentTitle === 'string' ? event.data.documentTitle : DEFAULT_SUMMARY_TITLE);
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
