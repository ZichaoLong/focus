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
const observationStages = new Set(['intent-start', 'intent-returned', 'intent-no-activity', 'intent-denied', 'intent-send-error',
  'intent-error', 'window-initial-focused', 'window-initial-unfocused', 'window-focused', 'window-unfocused',
  'activity-paused', 'activity-resumed', 'job-query-start', 'job-created', 'job-queued', 'job-started', 'job-blocked',
  'job-completed', 'job-failed', 'job-canceled', 'job-unknown', 'job-not-listed', 'job-query-error', 'job-sample-limit']);

type NativeEvents = {
  droppedEvents: number;
  events: { ms: number; attempt: number; source: MobilePrintSource; event: string }[];
};
type NativeObservations = { status: 'unavailable' } | ({ status: 'collected' } & NativeEvents);
type NativeReport = { status: 'recording' | 'unavailable' } | ({
  status: 'collected'; sdk: number; elapsedMs: number; observations?: NativeObservations;
} & NativeEvents);

function within(value: unknown, max: number): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 && value <= max;
}

function readNativeEvents(raw: unknown, elapsedMs: number, attempts: number, stages: Set<string>): NativeEvents | null {
  if (!raw || typeof raw !== 'object' || !('droppedEvents' in raw) || !within(raw.droppedEvents, Number.MAX_SAFE_INTEGER)
      || !('events' in raw) || !Array.isArray(raw.events) || raw.events.length > 40) return null;
  const events = [];
  for (const row of raw.events) {
    if (!Array.isArray(row) || row.length !== 4) return null;
    const [ms, attempt, source, event] = row;
    if (!within(ms, elapsedMs) || !within(attempt, attempts) || attempt < 1
        || (source !== 'webview' && source !== 'native-test') || !stages.has(event)) return null;
    events.push({ ms, attempt, source, event });
  }
  return { droppedEvents: raw.droppedEvents, events };
}

function finishNativeReport(session: string, attempts: number): NativeReport {
  const raw = mobilePrintRecording('stop', session);
  if (!raw || raw.length > 8192) return { status: 'unavailable' };
  try {
    const snapshot = JSON.parse(raw);
    if (!snapshot || !within(snapshot.sdk, 1000) || !within(snapshot.elapsedMs, recordingLimitMs)) return { status: 'unavailable' };
    const base = readNativeEvents(snapshot, snapshot.elapsedMs, attempts, nativeStages);
    if (!base) return { status: 'unavailable' };
    const report: NativeReport = { status: 'collected', sdk: snapshot.sdk, elapsedMs: snapshot.elapsedMs, ...base };
    if (hasMobileFeature('print-job-diagnostics')) {
      const observations = readNativeEvents(snapshot.observations, snapshot.elapsedMs, attempts, observationStages);
      report.observations = observations ? { status: 'collected', ...observations } : { status: 'unavailable' };
    }
    return report;
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
