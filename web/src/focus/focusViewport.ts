import { computed, nextTick, shallowRef, watch, type InjectionKey, type Ref } from 'vue';
import { focusPerformance } from './focusPerformance';

export interface FocusViewportDiagnostics {
  readonly enabled: Readonly<Ref<boolean>>;
  readonly report: Readonly<Ref<string>>;
  start(): void;
  stop(): void;
}

export const focusViewportDiagnosticKey: InjectionKey<Readonly<Ref<FocusViewportDiagnostics | null>>> = Symbol('focusViewportDiagnostic');

const MAX_TRANSITIONS = 6;
const MAX_VIEWPORT_CHANGES = 6;
const SETTLE_MS = 250;

function finite(value: number): number | null {
  return Number.isFinite(value) ? Math.round(value * 100) / 100 : null;
}

/** Own the fixed shell's viewport sizing and bounded, document-local evidence.
 * See docs/contracts/focus-web-reading-mode.zh-CN.md. */
export function createFocusViewport(shell: HTMLElement, readingMode: Readonly<Ref<boolean>>) {
  const doc = shell.ownerDocument;
  const view = doc.defaultView!;
  const style = doc.documentElement.style;
  let disposed = false;
  let generation = 0;
  let viewportFrame = 0;
  let transitionFrame = 0;
  let settleTimer = 0;

  function viewport() {
    const visual = view.visualViewport;
    return {
      width: finite(view.innerWidth), height: finite(view.innerHeight),
      visual: visual ? {
        width: finite(visual.width), height: finite(visual.height),
        top: finite(visual.offsetTop), left: finite(visual.offsetLeft), scale: finite(visual.scale),
      } : null,
      orientation: view.screen.orientation?.type ?? '',
      pixelRatio: finite(view.devicePixelRatio),
    };
  }

  function elementBox(element: Element | null) {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    const css = view.getComputedStyle(element);
    return {
      x: finite(rect.x), y: finite(rect.y), width: finite(rect.width), height: finite(rect.height),
      scrollTop: finite(element.scrollTop), scrollLeft: finite(element.scrollLeft),
      clientHeight: finite(element.clientHeight), scrollHeight: finite(element.scrollHeight),
      display: css.display, visibility: css.visibility, opacity: css.opacity, overflow: css.overflow,
      position: css.position, zIndex: css.zIndex, transform: css.transform,
      contentVisibility: css.contentVisibility,
    };
  }

  function hitTest(element: Element | null) {
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const x = Math.max(0, Math.min(view.innerWidth - 1, rect.x + rect.width / 2));
    const y = Math.max(0, Math.min(view.innerHeight - 1, rect.y + rect.height / 2));
    const target = doc.elementFromPoint(x, y);
    return {
      x: finite(x), y: finite(y), tag: target?.tagName ?? '',
      insideExpected: target !== null && element.contains(target),
      insideShell: target !== null && shell.contains(target),
      inDialog: Boolean(target?.closest('dialog, [role="dialog"]')),
    };
  }

  function capture(phase: string) {
    // Read only known layout nodes and numeric viewport data, never text,
    // attributes carrying session data, URLs, drafts, or transcript contents.
    const controls = shell.querySelector('.reading-mode-controls');
    const transcript = shell.querySelector('.panes.chat-scroll');
    return {
      phase, at: Date.now(), reading: readingMode.value, visibility: doc.visibilityState,
      viewport: viewport(),
      applied: { height: style.getPropertyValue('--app-height'), top: style.getPropertyValue('--app-top') },
      activeElement: doc.activeElement?.tagName ?? '',
      boxes: {
        document: elementBox(doc.documentElement), body: elementBox(doc.body),
        root: elementBox(doc.getElementById('app')), shell: elementBox(shell),
        app: elementBox(shell.querySelector('.focus-app')),
        main: elementBox(shell.querySelector('.focus-main')),
        controls: elementBox(controls),
        conversation: elementBox(shell.querySelector('.con')),
        transcript: elementBox(transcript),
      },
      hitTests: { controls: hitTest(controls), transcript: hitTest(transcript) },
    };
  }

  type Sample = ReturnType<typeof capture>;
  const diagnosticEnabled = shallowRef(false);
  const initial = shallowRef<Sample | null>(null);
  const transitions = shallowRef<Array<{ id: number; from: boolean; to: boolean; samples: Sample[] }>>([]);
  const viewportChanges = shallowRef<Array<{ before: Sample; after: Sample }>>([]);
  let lastViewport = '';

  function positiveHeight(value: number | undefined): number | undefined {
    return value !== undefined && Number.isFinite(value) && value > 0 ? value : undefined;
  }

  function applyViewport(): void {
    const visual = view.visualViewport;
    const height = positiveHeight(visual?.height) ?? positiveHeight(view.innerHeight)
      ?? positiveHeight(doc.documentElement.clientHeight);
    // A transient zero/invalid visual viewport must not collapse the whole app.
    // If all readings are invalid, retain the last size (or the CSS fallback).
    if (height !== undefined) style.setProperty('--app-height', `${height}px`);
    const top = visual?.offsetTop ?? 0;
    style.setProperty('--app-top', `${Number.isFinite(top) ? Math.max(0, top) : 0}px`);
  }

  function sampleTransition(id: number, phase: string): void {
    // Recording may have stopped or restarted while reconciliation was pending.
    if (!diagnosticEnabled.value || !transitions.value.some((item) => item.id === id)) return;
    const sample = capture(phase);
    transitions.value = transitions.value.map((item) => item.id === id
      ? { ...item, samples: [...item.samples, sample] } : item);
  }

  function cancelTransition(): void {
    if (transitionFrame) view.cancelAnimationFrame(transitionFrame);
    if (settleTimer) view.clearTimeout(settleTimer);
    transitionFrame = 0;
    settleTimer = 0;
  }

  const stopWatching = watch(readingMode, (to, from) => {
    if (disposed) return;
    cancelTransition();
    const id = ++generation;
    if (diagnosticEnabled.value) {
      transitions.value = [...transitions.value.slice(-(MAX_TRANSITIONS - 1)), {
        id, from, to, samples: [capture('before')],
      }];
    }
    void nextTick(() => {
      if (disposed || id !== generation) return;
      applyViewport();
      sampleTransition(id, 'after-dom');
      transitionFrame = view.requestAnimationFrame(() => {
        transitionFrame = 0;
        if (disposed || id !== generation) return;
        applyViewport();
        sampleTransition(id, 'after-frame');
        // A keyboard/address-bar animation may settle after the first frame.
        // One trailing check, not a polling or forced-remount loop.
        settleTimer = view.setTimeout(() => {
          settleTimer = 0;
          if (disposed || id !== generation) return;
          applyViewport();
          sampleTransition(id, 'settled');
        }, SETTLE_MS);
      });
    });
  });

  applyViewport();

  function onViewportChange(): void {
    if (disposed || viewportFrame) return;
    viewportFrame = view.requestAnimationFrame(() => {
      viewportFrame = 0;
      if (disposed) return;
      const signature = diagnosticEnabled.value ? JSON.stringify(viewport()) : '';
      const before = diagnosticEnabled.value && signature !== lastViewport ? capture('viewport-before') : null;
      applyViewport();
      if (before) {
        viewportChanges.value = [...viewportChanges.value.slice(-(MAX_VIEWPORT_CHANGES - 1)), {
          before, after: capture('viewport-after'),
        }];
        lastViewport = signature;
      }
    });
  }

  function onVisibilityChange(): void {
    if (doc.visibilityState === 'visible') onViewportChange();
  }

  view.visualViewport?.addEventListener('resize', onViewportChange);
  view.visualViewport?.addEventListener('scroll', onViewportChange);
  view.addEventListener('resize', onViewportChange);
  view.addEventListener('pageshow', onViewportChange);
  doc.addEventListener('visibilitychange', onVisibilityChange);

  const diagnostics: FocusViewportDiagnostics = {
    enabled: computed(() => diagnosticEnabled.value),
    report: computed(() => initial.value === null ? '' : JSON.stringify({
      schema: 'focus-viewport-v2', userAgent: view.navigator.userAgent.slice(0, 512),
      initial: initial.value, transitions: transitions.value, viewportChanges: viewportChanges.value,
      performance: focusPerformance.samples.value,
    }, null, 2)),
    start(): void {
      if (disposed || diagnosticEnabled.value) return;
      transitions.value = [];
      viewportChanges.value = [];
      initial.value = capture('recording-start');
      lastViewport = JSON.stringify(initial.value.viewport);
      diagnosticEnabled.value = true;
      focusPerformance.start();
    },
    stop(): void {
      diagnosticEnabled.value = false;
      focusPerformance.stop();
    },
  };

  return {
    diagnostics,
    dispose(): void {
      if (disposed) return;
      disposed = true;
      diagnostics.stop();
      stopWatching();
      cancelTransition();
      if (viewportFrame) view.cancelAnimationFrame(viewportFrame);
      view.visualViewport?.removeEventListener('resize', onViewportChange);
      view.visualViewport?.removeEventListener('scroll', onViewportChange);
      view.removeEventListener('resize', onViewportChange);
      view.removeEventListener('pageshow', onViewportChange);
      doc.removeEventListener('visibilitychange', onVisibilityChange);
      style.removeProperty('--app-height');
      style.removeProperty('--app-top');
    },
  };
}
