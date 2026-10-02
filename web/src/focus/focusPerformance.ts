import { shallowRef } from 'vue';

type Sample = { at: number; kind: string; durationMs?: number; bytes?: number; code?: number };
const samples = shallowRef<Sample[]>([]);
let enabled = false;
let longTasks: PerformanceObserver | null = null;

/** Default-off, document-local numeric evidence; never record content or URLs. */
export const focusPerformance = {
  samples,
  get enabled() { return enabled; },
  record(kind: 'socket_open' | 'socket_close' | 'event' | 'socket_backpressure'
    | 'transcript' | 'transcript_overflow' | 'projection_overflow' | 'long_task',
  data: Omit<Sample, 'at' | 'kind'> = {}) {
    if (!enabled) return;
    samples.value = [...samples.value.slice(-63), { at: Date.now(), kind, ...data }];
  },
  start() {
    this.stop();
    samples.value = [];
    enabled = true;
    if (typeof PerformanceObserver !== 'undefined' && PerformanceObserver.supportedEntryTypes.includes('longtask')) {
      longTasks = new PerformanceObserver(list => {
        for (const entry of list.getEntries()) this.record('long_task', { durationMs: Math.round(entry.duration) });
      });
      longTasks.observe({ type: 'longtask' });
    }
  },
  stop() { enabled = false; longTasks?.disconnect(); longTasks = null; },
};
