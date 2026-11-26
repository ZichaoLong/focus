import { ref } from 'vue';
import { hasMobileFeature, mobileApkRequest, mobilePrintRecording, printMobileSummary, type MobilePrintReply, type MobilePrintSource } from '../lib/mobileHost';

type PreviewStatus = 'loading' | 'ready' | 'error';
type PrintEvent = 'print-click' | 'native-test-click' | `bridge-${MobilePrintReply}` | 'host-pause' | 'host-resume'
  | 'page-visible' | 'page-hidden' | 'window-focus' | 'window-blur';

const versionNumber = '[0-9]{1,5}(?:[.][0-9]{1,5}){0,3}';
const appVersionPattern = new RegExp('^' + versionNumber + '$');
const androidVersionPattern = new RegExp('\\bAndroid (' + versionNumber + ')\\b');
const chromiumVersionPattern = new RegExp('\\bChrome/(' + versionNumber + ')\\b');
const recordingLimitMs = 5 * 60_000;
const nativeStages = new Set(['request', 'printing-restricted', 'no-service', 'invalid-name', 'no-adapter', 'adapter-created',
  'job-returned', 'no-job', 'security-exception', 'exception', 'start', 'layout', 'write', 'finish']);

type NativeReport = { status: 'recording' | 'unavailable' } | {
  status: 'collected'; sdk: number; elapsedMs: number; droppedEvents: number;
  events: { ms: number; attempt: number; source: MobilePrintSource; event: string }[];
};

function within(value: unknown, max: number): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;
}

function finishNativeReport(session: string, attempts: number): NativeReport {
  const raw = mobilePrintRecording('stop', session);
  if (!raw || raw.length > 8192) return { status: 'unavailable' };
  try {
    const snapshot = JSON.parse(raw);
    if (!snapshot || !within(snapshot.sdk, 1000) || !within(snapshot.elapsedMs, recordingLimitMs)
        || !within(snapshot.droppedEvents, Number.MAX_SAFE_INTEGER) || !Array.isArray(snapshot.events)
        || snapshot.events.length > 40) return { status: 'unavailable' };
    const events = [];
    for (const row of snapshot.events) {
      if (!Array.isArray(row) || row.length !== 4) return { status: 'unavailable' };
      const [ms, attempt, source, event] = row;
      if (!within(ms, snapshot.elapsedMs) || !within(attempt, attempts) || attempt < 1
          || (source !== 'webview' && source !== 'native-test') || !nativeStages.has(event)) return { status: 'unavailable' };
      events.push({ ms, attempt, source, event });
    }
    return { status: 'collected', sdk: snapshot.sdk, elapsedMs: snapshot.elapsedMs, droppedEvents: snapshot.droppedEvents, events };
  } catch { return { status: 'unavailable' }; }
}

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
  native?: NativeReport;
}

/** One preview owns the recording. All listeners exist only between start and stop. */
export function createSummaryPrintDiagnostics() {
  const report = ref<PrintReport | null>(null);
  const recording = ref(false);
  let started = 0;
  let listeners: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let nativeSession: string | null = null;
  const elapsed = () => Math.round(performance.now() - started);

  function record(event: PrintEvent): void {
    const current = report.value;
    if (!recording.value || !current) return;
    const ms = elapsed();
    // A suspended WebView can deliver its resume signal before an overdue timer.
    if (ms >= recordingLimitMs) { stop(); return; }
    if (event === 'print-click' || event === 'native-test-click') current.attempts++;
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
    if (nativeSession) report.value!.native = finishNativeReport(nativeSession, report.value!.attempts);
    nativeSession = null;
  }

  function start(status: PreviewStatus): void {
    stop();
    report.value = {
      format: 'focus-mobile-print/v1', environment: environment(), initialPreview: status,
      initialVisibility: document.visibilityState, attempts: 0, elapsedMs: 0, droppedEvents: 0, events: [],
    };
    started = performance.now();
    if (hasMobileFeature('print-diagnostics')) {
      nativeSession = mobilePrintRecording('start');
      report.value.native = { status: nativeSession ? 'recording' : 'unavailable' };
    }
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

  function print(name: string, source: MobilePrintSource = 'webview'): boolean {
    record(source === 'native-test' ? 'native-test-click' : 'print-click');
    const trace = nativeSession && recording.value && report.value
      ? { session: nativeSession, attempt: report.value.attempts, source } : undefined;
    if (source === 'native-test' && !trace) return false;
    return printMobileSummary(name, reply => record(`bridge-${reply}`), trace);
  }
  return { report, recording, start, stop, print };
}
