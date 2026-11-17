interface ForegroundChecks {
  readonly pending: boolean;
  subscribe(check: () => void): () => void;
}

const foregroundChecks = new WeakMap<Document, ForegroundChecks>();

function checksFor(document: Document): ForegroundChecks {
  const existing = foregroundChecks.get(document);
  if (existing) return existing;
  const view = document.defaultView!;
  const checks = new Set<() => void>();
  let frame: number | null = null;
  function cancel() {
    if (frame !== null) view.cancelAnimationFrame(frame);
    frame = null;
  }
  function schedule() {
    if (document.visibilityState === 'hidden') { cancel(); return; }
    if (frame !== null) return;
    frame = view.requestAnimationFrame(() => {
      frame = null;
      for (const check of checks) check();
    });
  }
  function onPageShow(event: PageTransitionEvent) { if (event.persisted) schedule(); }
  document.addEventListener('visibilitychange', schedule);
  view.addEventListener('pageshow', onPageShow);
  const pool: ForegroundChecks = {
    get pending() { return frame !== null; },
    subscribe(check) {
      checks.add(check);
      return () => {
        checks.delete(check);
        if (checks.size) return;
        cancel();
        document.removeEventListener('visibilitychange', schedule);
        view.removeEventListener('pageshow', onPageShow);
        foregroundChecks.delete(document);
      };
    },
  };
  foregroundChecks.set(document, pool);
  return pool;
}

/** Own row/chunk intersection delivery and foreground rechecks, not scrolling
 * or height measurement. See docs/contracts/focus-web-transcript-window.zh-CN.md. */
export function observeTranscriptVisibility(element: HTMLElement, update: (visible: boolean) => void): () => void {
  const document = element.ownerDocument, view = document.defaultView;
  if (!view?.IntersectionObserver) { update(true); return () => {}; }
  const foreground = checksFor(document);
  let disposed = false;
  let refreshedAt = Number.NEGATIVE_INFINITY;
  const observer = new view.IntersectionObserver(entries => {
    // Background notifications must not replace the last visible content with
    // placeholders. A foreground pass retires queued evidence before rechecking.
    if (disposed || document.visibilityState === 'hidden' || foreground.pending) return;
    let latest: IntersectionObserverEntry | undefined;
    for (const entry of entries) {
      if (entry.target === element && (!latest || entry.time >= latest.time)) latest = entry;
    }
    if (latest && latest.time >= refreshedAt) update(latest.isIntersecting);
  }, { root: element.closest('.chat-scroll, .panes'), rootMargin: '900px 0px' });
  const stopForeground = foreground.subscribe(() => {
    refreshedAt = view.performance.now();
    observer.takeRecords();
    // Preserve mounted slots while native intersection geometry is recomputed;
    // this also recovers when the last enter notification was missed entirely.
    observer.unobserve(element);
    observer.observe(element);
  });
  observer.observe(element);
  return () => {
    if (disposed) return;
    disposed = true;
    observer.disconnect();
    stopForeground();
  };
}
