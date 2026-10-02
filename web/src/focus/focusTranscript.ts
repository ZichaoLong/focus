import { computed, ref, shallowRef, watch, type Ref } from 'vue';
import type { ChatTurn } from '../types';
import type { FocusWebApiPort } from './api';
import { type FocusProjectionEvent, type FocusThreadDeltaDetail,
  type FocusThreadSnapshot, type FocusTranscriptQuery } from './types';
import { appendTranscriptDelta } from './transcriptItems';
import { focusPerformance } from './focusPerformance';
import { readTranscriptTarget } from './transcriptRead';
import { TranscriptPageWindow } from './transcriptPageWindow';

type BufferedDelta = { event: FocusProjectionEvent; detail: FocusThreadDeltaDetail };

/** One bounded visible item window; navigation never accumulates full turns. */
export function createFocusTranscript(options: {
  api: Pick<FocusWebApiPort, 'readTranscriptWindow'>;
  snapshot: Readonly<Ref<FocusThreadSnapshot | null>>;
  activeThreadId: Readonly<Ref<string>>;
  isDisposed(): boolean;
  reportFatalError?(error: unknown): boolean;
}) {
  const turns = shallowRef<ChatTurn[]>([]);
  const cache = new TranscriptPageWindow();
  const edges = shallowRef({ older: null as string | null, newer: null as string | null, atTail: false });
  const unseenNewer = ref(false);
  let protectedRow: string | null = null;
  let lastDirection: 'older' | 'newer' = 'newer';
  function publishWindow() {
    turns.value = cache.rows;
    edges.value = { older: cache.older, newer: cache.newer, atTail: cache.atTail };
  }
  const loading = ref(false);
  const error = ref('');
  const historical = ref(false);
  const fullText = shallowRef<string | null>(null);
  const fullLoading = ref(false);
  const fullError = ref('');
  const enabled = computed(() => options.snapshot.value?.thread.id === options.activeThreadId.value
    && options.snapshot.value?.thread.history_mode === 'paginated' && !options.snapshot.value?.thread.ephemeral);
  let generation = 0;
  let detailGeneration = 0;
  let buffer: BufferedDelta[] = [];
  let bufferBytes = 0;
  let overflowed = false;
  const needsHead = ref(false);
  let pendingHead = false;
  let automaticAttempts = 0;
  let controller: AbortController | null = null;
  let fullController: AbortController | null = null;
  let refreshTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  let activeMode = 'head';
  const hasOlder = computed(() => !needsHead.value && !!edges.value.older);
  const hasNewer = computed(() => turns.value.length > 0 && (!edges.value.atTail || unseenNewer.value));

  function identity() {
    return `${options.activeThreadId.value}\n${options.snapshot.value?.runtime_epoch ?? ''}\n${options.isDisposed()}`;
  }

  function cancel() {
    generation += 1;
    controller?.abort();
    controller = null;
    loading.value = false;
    buffer = [];
    bufferBytes = 0;
    if (refreshTimer !== null) clearTimeout(refreshTimer);
    refreshTimer = null;
    pendingHead = false;
  }

  function closeFull() {
    detailGeneration += 1;
    fullController?.abort();
    fullController = null;
    fullText.value = null;
    fullLoading.value = false;
    fullError.value = '';
  }

  function cancelTarget() { if (activeMode === 'target' && loading.value) cancel(); }

  function reset() {
    cancel();
    closeFull();
    turns.value = [];
    cache.clear(); publishWindow(); unseenNewer.value = false; protectedRow = null;
    historical.value = false;
    error.value = '';
    needsHead.value = false;
    automaticAttempts = 0;
  }

  function scheduleHead() {
    if (historical.value || disposed || options.isDisposed() || automaticAttempts >= 3) return;
    pendingHead = true;
    if (loading.value || refreshTimer !== null) return;
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      pendingHead = false;
      if (historical.value || disposed || options.isDisposed()) return;
      automaticAttempts += 1;
      void load({}, 'head', true);
    }, 1000 * 2 ** automaticAttempts);
  }

  function applyDelta(event: FocusProjectionEvent, detail: FocusThreadDeltaDetail) {
    let next = turns.value;
    for (const incoming of detail.item_turns ?? []) {
      const index = next.findIndex((turn) => turn.id === incoming.id);
      if (index >= 0) {
        next = [...next];
        const previous = next[index]!;
        // A delayed start skeleton cannot erase text already streamed for the
        // same item. Completed snapshots remain authoritative, including edits.
        next[index] = detail.method === 'item/started' && previous.text.length > incoming.text.length
          && previous.text.startsWith(incoming.text) ? previous : incoming;
      } else if (!historical.value && (detail.method === 'item/started' || detail.method === 'item/completed')) {
        next = [...next, incoming];
      } else if (!historical.value) scheduleHead();
      else unseenNewer.value = true;
    }
    const stream = detail.stream_delta;
    if (detail.item_order && !historical.value) {
      const order = new Set(detail.item_order);
      const byId = new Map(next.map((turn) => [turn.id, turn]));
      next = [...next.filter((turn) => !order.has(turn.id)),
        ...detail.item_order.flatMap((id) => byId.has(id) ? [byId.get(id)!] : [])];
    }
    if (stream) {
      const index = next.findIndex((turn) => turn.rawTurnId === stream.turn_id && turn.itemId === stream.item_id);
      if (index >= 0 || !historical.value) {
        const updated = appendTranscriptDelta(next[index], stream);
        if (updated) {
          next = [...next];
          if (index < 0) next.push(updated);
          else next[index] = updated;
        } else scheduleHead();
      } else unseenNewer.value = true;
    }
    if (detail.method === 'turn/completed' && detail.turn_id) {
      next = next.map((turn) => turn.rawTurnId === detail.turn_id ? { ...turn, status: 'completed' } : turn);
    }
    if (cache.update(next, lastDirection, protectedRow)) {
      needsHead.value = true;
      scheduleHead();
    }
    publishWindow();
    void event;
  }

  function handleDelta(event: FocusProjectionEvent, detail: FocusThreadDeltaDetail) {
    if (!enabled.value || disposed || event.thread_id !== options.activeThreadId.value) return;
    if (loading.value) {
      if (overflowed) return;
      bufferBytes += JSON.stringify(detail).length * 2;
      if (buffer.length >= 256 || bufferBytes > 512 * 1024) {
        overflowed = true;
        focusPerformance.record('transcript_overflow', { bytes: bufferBytes });
        buffer = [];
      } else buffer.push({ event, detail });
      return;
    }
    applyDelta(event, detail);
  }

  async function load(query: FocusTranscriptQuery = {}, mode: 'head' | 'older' | 'newer' | 'target' = 'head', automatic = false): Promise<boolean> {
    if (!enabled.value || disposed || options.isDisposed()) return false;
    if (refreshTimer !== null) clearTimeout(refreshTimer);
    refreshTimer = null;
    pendingHead = false;
    if (!automatic) automaticAttempts = 0;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    const request = ++generation;
    activeMode = mode;
    const startedAt = Date.now();
    const scope = identity();
    const threadId = options.activeThreadId.value;
    const browsingAtStart = historical.value;
    loading.value = true;
    error.value = '';
    buffer = [];
    bufferBytes = 0;
    overflowed = false;
    const current = () => request === generation && scope === identity() && !disposed && !options.isDisposed();
    try {
      const result = await readTranscriptTarget(options.api, threadId,
        options.snapshot.value?.runtime_epoch ?? '', query, requestController.signal, current);
      if (!current()) return false;
      if (mode === 'head' && !browsingAtStart && historical.value && turns.value.length) {
        for (const pending of buffer) applyDelta(pending.event, pending.detail);
        return false;
      }
      if (result.thread_id !== threadId || result.runtime_epoch !== options.snapshot.value?.runtime_epoch
        || result.turn_id !== (query.turn_id ?? null)) throw new Error('Transcript identity changed.');
      if (overflowed) {
        needsHead.value = true;
        error.value = 'Live updates exceeded the loading buffer. Reload recent messages.';
        return false;
      }
      if (query.cursor && (mode === 'older' ? result.older_cursor : result.newer_cursor) === query.cursor) {
        throw new Error('Transcript cursor did not advance.');
      }
      if (mode === 'target' && query.item_id && !result.turns.some(turn =>
        turn.rawTurnId === query.turn_id && turn.itemId === query.item_id)) {
        throw new Error('Transcript target was not found.');
      }
      if (mode === 'older' || mode === 'newer') {
        lastDirection = mode;
        cache.extend(result, mode, protectedRow);
      } else {
        lastDirection = 'newer';
        cache.replace(result, mode === 'head' || !result.newer_cursor);
      }
      focusPerformance.record('transcript', { durationMs: Date.now() - startedAt });
      publishWindow();
      if (cache.atTail && mode !== 'older') unseenNewer.value = false;
      historical.value = mode !== 'head';
      needsHead.value = false;
      for (const pending of buffer) {
        if (pending.event.runtime_epoch === result.runtime_epoch && pending.event.revision > result.revision) {
          applyDelta(pending.event, pending.detail);
        }
      }
      if (!needsHead.value && !pendingHead) automaticAttempts = 0;
      return true;
    } catch (failure) {
      if (current()) {
        if (options.reportFatalError?.(failure)) return false;
        error.value = failure instanceof Error ? failure.message : String(failure);
        for (const pending of buffer) applyDelta(pending.event, pending.detail);
      }
      return false;
    } finally {
      if (current()) {
        loading.value = false;
        buffer = [];
        bufferBytes = 0;
        controller = null;
        if (needsHead.value && automaticAttempts >= 3 && !error.value) {
          error.value = 'Live updates changed the page too quickly. Reload recent messages.';
        }
        if (overflowed || needsHead.value || pendingHead) scheduleHead();
      }
    }
  }

  function older() {
    if (!hasOlder.value || loading.value) return Promise.resolve(false);
    return load({ cursor: edges.value.older!, direction: 'desc' }, 'older');
  }

  function newer() {
    if (!hasNewer.value || loading.value) return Promise.resolve(false);
    const last = turns.value.at(-1);
    const query: FocusTranscriptQuery = edges.value.newer
      ? { cursor: edges.value.newer, direction: 'asc' }
      : { turn_id: last?.rawTurnId, item_id: last?.itemId, direction: 'asc' };
    return load(query, 'newer');
  }

  function updateViewport(anchorId: string | null, following: boolean) {
    protectedRow = anchorId;
    if (!following) historical.value = true;
    else if (!hasNewer.value) historical.value = false;
  }

  async function locate(turnId: string, itemId?: string): Promise<string | null> {
    if (!await load({ turn_id: turnId, direction: 'asc', ...(itemId ? { item_id: itemId } : {}) }, 'target')) return null;
    return turns.value.find((turn) => turn.rawTurnId === turnId && (!itemId || turn.itemId === itemId))?.id ?? null;
  }

  async function openFull(turn: ChatTurn) {
    if (!turn.rawTurnId || !turn.itemId) return;
    closeFull();
    const request = detailGeneration;
    const scope = identity();
    const threadId = options.activeThreadId.value;
    fullController = new AbortController();
    fullLoading.value = true;
    try {
      const result = await readTranscriptTarget(options.api, threadId, options.snapshot.value?.runtime_epoch ?? '', {
        turn_id: turn.rawTurnId, item_id: turn.itemId, full: true,
        ...(turn.sourceCursor ? { source_cursor: turn.sourceCursor } : {}),
      }, fullController.signal, () => request === detailGeneration && scope === identity() && !disposed);
      if (request !== detailGeneration || scope !== identity() || disposed) return;
      if (result.thread_id !== threadId || result.turn_id !== turn.rawTurnId
        || result.runtime_epoch !== options.snapshot.value?.runtime_epoch || result.full_text === null) {
        throw new Error('Full message content did not match the selected thread.');
      }
      fullText.value = result.full_text;
    } catch (failure) {
      if (request === detailGeneration && scope === identity() && !disposed) {
        if (options.reportFatalError?.(failure)) return;
        fullError.value = failure instanceof Error ? failure.message : String(failure);
      }
    } finally {
      if (request === detailGeneration) fullLoading.value = false;
    }
  }

  const stopIdentity = watch(identity, reset, { flush: 'sync' });
  const stopSnapshot = watch([enabled, () => options.snapshot.value?.revision], () => {
    if (enabled.value && !historical.value) void load();
  }, { immediate: true });
  function dispose() { disposed = true; reset(); stopIdentity(); stopSnapshot(); }

  return { enabled, turns, loading, error, historical, hasOlder, hasNewer,
    fullText, fullLoading, fullError, openFull, closeFull,
    handleDelta, load, older, newer, locate, updateViewport, cancelTarget, reset, dispose };
}
