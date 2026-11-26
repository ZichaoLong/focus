import { ref } from 'vue';
import { hasMobileFeature, mobileApkRequest, type MobilePrintReply } from '../lib/mobileHost';

type PreviewStatus = 'loading' | 'ready' | 'error';
type PrintEvent = 'print-click' | `bridge-${MobilePrintReply}` | 'host-pause' | 'host-resume'
  | 'page-visible' | 'page-hidden' | 'window-focus' | 'window-blur';

const versionNumber = '[0-9]{1,5}(?:[.][0-9]{1,5}){0,3}';
const appVersionPattern = new RegExp('^' + versionNumber + '$');
const androidVersionPattern = new RegExp('\\bAndroid (' + versionNumber + ')\\b');
const chromiumVersionPattern = new RegExp('\\bChrome/(' + versionNumber + ')\\b');
const recordingLimitMs = 5 * 60_000;

function environment() {
  let appVersion: string | null = null;
  if (hasMobileFeature('android-update')) {
    try {
      const version = JSON.parse(mobileApkRequest('info'))?.version;
      if (typeof version === 'string' && appVersionPattern.test(version)) appVersion = version;
    } catch { /* The print bridge can still be observed without version information. */ }
  }
  const ua = navigator.userAgent;
  return {
    appVersion,
    reportedAndroid: androidVersionPattern.exec(ua)?.[1] ?? null,
    reportedChromium: chromiumVersionPattern.exec(ua)?.[1] ?? null,
    printNegotiated: hasMobileFeature('print'),
    hostLifecycleNegotiated: hasMobileFeature('wake'),
  };
}

interface PrintReport {
  format: 'focus-mobile-print/v1';
  environment: ReturnType<typeof environment>;
  initialPreview: PreviewStatus;
  initialVisibility: DocumentVisibilityState;
  attempts: number;
  elapsedMs: number;
  droppedEvents: number;
  events: { ms: number; attempt: number; event: PrintEvent }[];
}

/** One preview owns the recording. All listeners exist only between start and stop. */
export function createSummaryPrintDiagnostics() {
  const report = ref<PrintReport | null>(null);
  const recording = ref(false);
  let started = 0;
  let listeners: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const elapsed = () => Math.round(performance.now() - started);

  function record(event: PrintEvent): void {
    const current = report.value;
    if (!recording.value || !current) return;
    const ms = elapsed();
    // A suspended WebView can deliver its resume signal before an overdue timer.
    if (ms >= recordingLimitMs) { stop(); return; }
    if (event === 'print-click') current.attempts++;
    if (current.events.length === 40) {
      current.events.shift();
      current.droppedEvents++;
    }
    current.elapsedMs = ms;
    current.events.push({ ms, attempt: current.attempts, event });
  }

  function stop(): void {
    if (!recording.value) return;
    listeners?.abort();
    listeners = undefined;
    clearTimeout(timer);
    report.value!.elapsedMs = Math.min(elapsed(), recordingLimitMs);
    recording.value = false;
  }

  function start(status: PreviewStatus): void {
    stop();
    report.value = {
      format: 'focus-mobile-print/v1', environment: environment(), initialPreview: status,
      initialVisibility: document.visibilityState, attempts: 0, elapsedMs: 0, droppedEvents: 0, events: [],
    };
    started = performance.now();
    recording.value = true;
    listeners = new AbortController();
    const options = { signal: listeners.signal };
    window.addEventListener('focus-host-pause', () => record('host-pause'), options);
    window.addEventListener('focus-host-resume', () => record('host-resume'), options);
    window.addEventListener('blur', () => record('window-blur'), options);
    window.addEventListener('focus', () => record('window-focus'), options);
    document.addEventListener('visibilitychange', () => record(document.hidden ? 'page-hidden' : 'page-visible'), options);
    timer = setTimeout(stop, recordingLimitMs);
  }

  return {
    report, recording, start, stop,
    click: () => record('print-click'),
    reply: (value: MobilePrintReply) => record(`bridge-${value}`),
  };
}
