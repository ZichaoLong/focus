import { computed, ref, shallowRef, watch, type Ref } from 'vue';
import type { ChatTurn, ToolCall } from '../types';
import type { FocusWebApiPort } from './api';
import { FocusApiError, isStaleWebReadError, type FocusProjectionEvent, type FocusThreadDeltaDetail,
  type FocusThreadSnapshot, type FocusTranscriptQuery } from './types';
import { appendTranscriptDelta } from './transcriptItems';
import { readSavedWindow, savedTurns, saveConversationWindow, type SavedWindow } from './mobileConversation';
import { focusPerformance } from './focusPerformance';
import { readTranscriptTarget } from './transcriptRead';
import { MAX_TAIL_FILL_READS, TranscriptPageWindow, TRANSCRIPT_CACHE_BYTES, TRANSCRIPT_CACHE_PAGES } from './transcriptPageWindow';

type BufferedDelta = { event: FocusProjectionEvent; detail: FocusThreadDeltaDetail };
type InstanceReturn = {
  threadId: string;
  scope: string | null;
  recoveryStarted: boolean;
  wake: 'none' | 'pending' | 'confirmed';
};

/** One bounded visible item window; navigation never accumulates full turns. */
export function createFocusTranscript(options: {
  api: Pick<FocusWebApiPort, 'readTranscriptWindow' | 'mobileReadScope'>;
  acceptedHead?(page: import('./types').FocusTranscriptPage): void;
  snapshot: Readonly<Ref<FocusThreadSnapshot | null>>;
  activeThreadId: Readonly<Ref<string>>;
  isDisposed(): boolean;
  reportFatalError?(error: unknown): boolean;
  savedReadingItem?(thread: string): { turn: string; item: string } | null;
  forgetReadingItem?(thread: string, turn: string, item: string): void;
}) {
  const turns = shallowRef<ChatTurn[]>([]);
  const cache = new TranscriptPageWindow();
  // Device rows are presentation only. They never mint a writer scope, a server cursor, or event revision evidence.
  const saved = shallowRef<{page: SavedWindow; rows: ChatTurn[]} | null>(null);
  const showingSaved = computed(() => !!saved.value && saved.value.page.thread === options.activeThreadId.value && !options.isDisposed());
  const visibleTurns = computed(() => showingSaved.value ? saved.value!.rows : turns.value);
  function restoreSaved(thread: string) {
    saved.value = null;
    if (options.isDisposed()) return;
    const page = readSavedWindow(thread,options.api.mobileReadScope,{direction:'open'});
    if (page) saved.value = {page, rows:savedTurns(page)};
  }
  function saveRows(rows: ChatTurn[], tail: boolean, older: boolean, newer: boolean) {
    const snapshot = options.snapshot.value;
    if (snapshot?.thread.id !== options.activeThreadId.value || !enabled.value || !snapshot) return;
    saveConversationWindow(snapshot.thread.id,snapshot.thread.title || snapshot.thread.name || snapshot.thread.id,
      options.api.mobileReadScope,rows,tail,older,newer);
  }
  let saveTimer: ReturnType<typeof setTimeout> | undefined;
  let pendingWrite: (()=>void) | undefined;
  function flushLive() {
    if (saveTimer === undefined) return;
    clearTimeout(saveTimer); saveTimer=undefined;
    const write=pendingWrite; pendingWrite=undefined; write?.();
  }
  const edges = shallowRef({ older: null as string | null, newer: null as string | null, atTail: false, needsOlderAnchor: false });
  const unseenNewer = ref(false);
  let protectedRow: string | null = null;
  let following = true;
  let eventRevision = -1;
  let tailReadRevision = -1;
  const rowReadRevisions = new Map<string, number>();
  let lastDirection: 'older' | 'newer' = 'newer';
  function publishWindow() {
    turns.value = cache.rows;
    edges.value = { older: cache.older, newer: cache.newer, atTail: cache.atTail, needsOlderAnchor: cache.needsOlderAnchor };
    historical.value = turns.value.length > 0 && !cache.atTail;
    const ids = new Set(turns.value.map(row => row.id));
    for (const id of rowReadRevisions.keys()) if (!ids.has(id)) rowReadRevisions.delete(id);
  }
  const loading = ref(false);
  const error = ref('');
  const historical = ref(false);
  const fullText = shallowRef<string | null>(null);
  const fullTool = shallowRef<Pick<ToolCall, 'name' | 'arg' | 'status'> | null>(null);
  let fullTarget: ChatTurn | null = null;
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
  let memberController: AbortController | null = null;
  let fullController: AbortController | null = null;
  let refreshTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  let awaitingProjection = false;
  let activeMode = 'head';
  let filling = false;
  let latestIntent: AbortSignal | undefined;
  let tailReadsLeft = MAX_TAIL_FILL_READS;
  let ordinaryTail = true;
  let budgetThread = options.activeThreadId.value;
  let pendingInstanceReturn: InstanceReturn | null = null;
  const tailContext = shallowRef<AbortController | null>(null);
  const hasOlder = computed(() => !needsHead.value && (!!edges.value.older || edges.value.needsOlderAnchor));
  const hasNewer = computed(() => turns.value.length > 0 && (!edges.value.atTail || unseenNewer.value));

  function identity() {
    return `${options.activeThreadId.value}\n${options.snapshot.value?.runtime_epoch ?? ''}\n${options.isDisposed()}`;
  }

  function retireConfirmedCursor() {
    const previous = tailContext.value;
    tailContext.value = null;
    previous?.abort();
  }

  function cancelTailContext() {
    ordinaryTail = false;
    pendingInstanceReturn = null;
    retireConfirmedCursor();
  }

  function startInstanceReturn(threadId: string, wake: 'none' | 'pending' = 'none') {
    cancelTailContext();
    const scope = enabled.value && threadId === options.activeThreadId.value ? identity() : null;
    const returning: InstanceReturn = { threadId, scope, recoveryStarted: false, wake };
    pendingInstanceReturn = returning;
    if (wake === 'none') tailReadsLeft = MAX_TAIL_FILL_READS;
    return returning;
  }

  function prepareInitialReturn() {
    // Startup navigation resolves its target asynchronously. A gesture or a
    // pause before that point must still be able to cancel this return.
    const returning = startInstanceReturn('');
    return (threadId: string) => {
      if (pendingInstanceReturn !== returning) return;
      if (!threadId) { cancelTailContext(); return; }
      returning.threadId = threadId;
    };
  }

  function expectInstanceReturn(threadId: string) {
    if (threadId) startInstanceReturn(threadId);
    else cancelTailContext();
  }

  function captureForegroundReturn() {
    if (!enabled.value || !following) return null;
    const scope = identity();
    return () => {
      if (scope === identity() && enabled.value && following) startInstanceReturn(options.activeThreadId.value, 'pending');
    };
  }

  function offerTailContext() {
    // Keep measuring a verified tail even after both reads were spent: new
    // content can fill the viewport. older() alone admits another request.
    if (!cache.atTail || !cache.older || tailContext.value) return;
    const context = new AbortController();
    latestIntent = context.signal;
    tailContext.value = context;
  }

  function confirmForegroundWake() {
    const returning = pendingInstanceReturn;
    if (returning?.wake !== 'pending' || returning.scope !== identity() || !following) return;
    returning.wake = 'confirmed';
    // A pong on the current socket also covers a head revalidated while the
    // app was hidden. A projection or transcript read in flight settles first.
    if (!awaitingProjection && !loading.value && !needsHead.value && !pendingHead && !error.value) offerTailContext();
  }

  function cancel() {
    generation += 1;
    latestIntent = undefined;
    retireConfirmedCursor();
    controller?.abort();
    memberController?.abort();
    memberController = null;
    controller = null;
    loading.value = false;
    filling = false;
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
    fullTool.value = null;
    fullTarget = null;
    fullLoading.value = false;
    fullError.value = '';
  }

  function cancelTarget() { if (activeMode === 'target' && loading.value) cancel(); }

  function reset() {
    // A cold thread hint precedes its first snapshot. Once bound, a change
    // of thread, epoch or access retires the entire return.
    if (pendingInstanceReturn?.scope) cancelTailContext();
    if (budgetThread !== options.activeThreadId.value) {
      budgetThread = options.activeThreadId.value;
      ordinaryTail = true;
      tailReadsLeft = MAX_TAIL_FILL_READS;
    }
    awaitingProjection = false;
    cancel();
    closeFull();
    turns.value = [];
    cache.clear(); publishWindow(); unseenNewer.value = false; protectedRow = null;
    following = true;
    eventRevision = -1;
    tailReadRevision = -1;
    rowReadRevisions.clear();
    historical.value = false;
    error.value = '';
    needsHead.value = false;
    automaticAttempts = 0;
  }

  function prepareReload() {
    cancel();
    closeFull();
    awaitingProjection = true;
    // Keep rendered rows/viewport while control state is replaced, but retire
    // all cursors and revision evidence: a missed revert may have removed them.
    cache.clear();
    edges.value = { ...edges.value, older: null, newer: null, needsOlderAnchor: false };
    rowReadRevisions.clear();
    eventRevision = tailReadRevision = -1;
  }

  function readingAnchor() {
    return following ? undefined : turns.value.find(row => row.id === protectedRow) ?? turns.value[0];
  }

  function resumeAfterReload() {
    awaitingProjection = false;
    return loadReadingWindow();
  }

  function loadReadingWindow(automatic = false) {
    const anchor = readingAnchor();
    if (anchor?.rawTurnId && anchor.itemId) {
      return load({ turn_id: anchor.rawTurnId, item_id: anchor.itemId, direction: 'asc' }, 'restore', automatic);
    }
    return loadInitialWindow(automatic);
  }

  function loadInitialWindow(automatic = false) {
    if (!turns.value.length) {
      const stored = showingSaved.value ? saved.value?.page.anchor : undefined;
      const bookmark = stored?.turn && stored.item ? stored : options.savedReadingItem?.(options.activeThreadId.value);
      if (bookmark?.turn && bookmark.item) return load({ turn_id: bookmark.turn, item_id: bookmark.item, direction: 'asc' }, 'restore', automatic);
    }
    return load({}, 'sync', automatic);
  }

  function reloadWithoutAnchor(query: FocusTranscriptQuery) {
    if (query.turn_id && query.item_id) options.forgetReadingItem?.(options.activeThreadId.value, query.turn_id, query.item_id);
    // An authoritative read removed the anchor. Do not retain reverted rows.
    turns.value = [];
    cache.clear(); publishWindow(); protectedRow = null; following = true;
    return load();
  }

  function scheduleHead() {
    if (awaitingProjection || historical.value || disposed || options.isDisposed() || automaticAttempts >= 3) return;
    pendingHead = true;
    if (loading.value || refreshTimer !== null) return;
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      pendingHead = false;
      if (historical.value || disposed || options.isDisposed()) return;
      automaticAttempts += 1;
      if (cache.pageCount === 0) void loadReadingWindow(true);
      else void load({}, 'sync', true);
    }, 1000 * 2 ** automaticAttempts);
  }

  function applyDelta(event: FocusProjectionEvent, detail: FocusThreadDeltaDetail) {
    if (event.revision <= eventRevision) return;
    eventRevision = event.revision;
    const covered = (id: string, exists: boolean) => event.revision <= (
      exists ? rowReadRevisions.get(id) ?? -1 : tailReadRevision
    );
    let next = turns.value;
    for (const incoming of detail.item_turns ?? []) {
      const index = next.findIndex((turn) => turn.id === incoming.id);
      if (covered(incoming.id, index >= 0)) continue;
      if (index >= 0) {
        next = [...next];
        const previous = next[index]!;
        // A delayed start skeleton cannot erase text already streamed for the
        // same item. Completed snapshots remain authoritative, including edits.
        const priorStatus = previous.compactTool?.status ?? previous.tools?.[0]?.status;
        if (detail.method === 'item/started' && priorStatus && priorStatus !== 'running'
          && incoming.tools?.[0]?.status === 'running') continue;
        const reply = previous.reply?.state === 'complete' ? previous.reply : incoming.reply ?? previous.reply;
        next[index] = detail.method === 'item/started' && previous.text.length > incoming.text.length
          && previous.text.startsWith(incoming.text) ? { ...previous, reply,
            blocks: previous.blocks?.map(block => block.kind === 'text' ? { ...block, reply } : block),
          } : incoming;
      } else if (!historical.value) {
        // Coalescing may carry the completed item under turn/completed.
        // The row is already complete; no extra body request is necessary.
        next = [...next, incoming];
      } else unseenNewer.value = true;
    }
    const stream = detail.stream_delta;
    if (detail.item_order && !historical.value && event.revision > tailReadRevision) {
      const order = new Set(detail.item_order);
      const byId = new Map(next.map((turn) => [turn.id, turn]));
      next = [...next.filter((turn) => !order.has(turn.id)),
        ...detail.item_order.flatMap((id) => byId.has(id) ? [byId.get(id)!] : [])];
    }
    if (stream) {
      const index = next.findIndex((turn) => turn.rawTurnId === stream.turn_id && turn.itemId === stream.item_id);
      if (covered(next[index]?.id ?? '', index >= 0)) {
        // This exact row was read after the delta was emitted.
      } else if (index >= 0 || !historical.value) {
        const updated = appendTranscriptDelta(next[index], stream);
        if (updated) {
          next = [...next];
          if (index < 0) next.push(updated);
          else next[index] = updated;
        } else scheduleHead();
      } else unseenNewer.value = true;
    }
    if (detail.method === 'turn/completed' && detail.turn_id) {
      next = next.map((turn) => {
        if (turn.rawTurnId !== detail.turn_id || covered(turn.id, true)) return turn;
        const reply = turn.reply?.state === 'generating' ? { ...turn.reply, state: 'unknown' as const } : turn.reply;
        return { ...turn, status: 'completed', ...(reply ? { reply } : {}),
          blocks: turn.blocks?.map(block => block.kind === 'text' && block.reply?.state === 'generating'
            ? { ...block, reply: { ...block.reply, state: 'unknown' as const } } : block),
        };
      });
    }
    if (filling) {
      const previous = new Map(turns.value.map(row => [row.id, row]));
      for (const row of next) if (previous.get(row.id) !== row) rowReadRevisions.set(row.id, event.revision);
    }
    if (cache.update(next, lastDirection, protectedRow)) {
      scheduleHead();
    }
    publishWindow();
    if (showingSaved.value && !following) unseenNewer.value=true;
    const scope=options.api.mobileReadScope, thread=options.snapshot.value?.thread;
    if (cache.atTail && scope && thread) {
      const partial=!!detail.stream_delta;
      const currentRows=partial ? turns.value.filter(row=>row.rawTurnId===detail.stream_delta!.turn_id && row.itemId===detail.stream_delta!.item_id) : turns.value.slice(-80);
      const older=!!cache.older || turns.value.length>80;
      pendingWrite=()=>saveConversationWindow(thread.id,thread.title || thread.name || thread.id,scope,currentRows,true,older,false,partial);
      if (saveTimer === undefined) saveTimer=setTimeout(flushLive,400);
      if (detail.method==='turn/completed' || detail.method==='item/completed') flushLive();
    }
    const completedDetail = (detail.item_turns ?? []).find(turn => turn.id === fullTarget?.id
      && fullTool.value?.status === 'running' && turn.tools?.[0]?.status !== 'running');
    if (completedDetail) void openFull(completedDetail);
  }

  function handleDelta(event: FocusProjectionEvent, detail: FocusThreadDeltaDetail) {
    if (awaitingProjection || !enabled.value || disposed || event.thread_id !== options.activeThreadId.value
      || event.runtime_epoch !== options.snapshot.value?.runtime_epoch) return;
    if (loading.value && !filling) {
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

  async function load(query: FocusTranscriptQuery = {}, mode: 'head' | 'latest' | 'sync' | 'older' | 'newer' | 'target' | 'restore' = 'head',
    automatic = false, intent?: AbortSignal): Promise<boolean> {
    if (awaitingProjection || !enabled.value || disposed || options.isDisposed() || intent?.aborted) return false;
    if (refreshTimer !== null) clearTimeout(refreshTimer);
    refreshTimer = null;
    pendingHead = false;
    if (!automatic) automaticAttempts = 0;
    const keepLiveContext = mode === 'sync' && !needsHead.value && cache.atTail && cache.pageCount > 0;
    if (mode === 'sync') needsHead.value = true;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    const request = ++generation;
    activeMode = mode;
    if (mode !== 'sync' && !query.fill) memberController?.abort();
    filling = !!query.fill;
    latestIntent = intent;
    const startedAt = Date.now();
    const scope = identity();
    const threadId = options.activeThreadId.value;
    // A retained tab must complete its fresh recovery read. Its old window
    // can still be on screen when the host selects it again.
    const confirmedFill = !!query.fill && !!intent && intent === tailContext.value?.signal;
    if (mode === 'sync') retireConfirmedCursor();
    else if (!query.fill) cancelTailContext();
    if (mode === 'latest' && intent) {
      ordinaryTail = true;
      tailReadsLeft = MAX_TAIL_FILL_READS;
    } else if (mode === 'head' && following) ordinaryTail = true;
    const returning = pendingInstanceReturn;
    if (returning?.threadId === threadId && !cache.pageCount) {
      returning.scope = scope;
      returning.recoveryStarted = true;
    }
    const browsingAtStart = historical.value;
    const followingAtStart = following;
    // Superseding a same-document page read must carry its ordered events
    // into the next read, including events for rows retained outside the head.
    if (!loading.value) {
      buffer = [];
      bufferBytes = 0;
      overflowed = false;
    }
    loading.value = true;
    error.value = '';
    const current = () => request === generation && scope === identity() && !disposed && !options.isDisposed();
    const abandonIntent = () => {
      if (!current()) return;
      for (const pending of buffer) applyDelta(pending.event, pending.detail);
      if (overflowed) needsHead.value = true;
      const resync = needsHead.value || pendingHead;
      cancel();
      if (resync) scheduleHead();
    };
    intent?.addEventListener('abort', abandonIntent, { once: true });
    try {
      const result = await readTranscriptTarget(options.api, threadId,
        options.snapshot.value?.runtime_epoch ?? '', query, requestController.signal, current);
      if (!current()) return false;
      if (turns.value.length && (
        (mode === 'sync' && !browsingAtStart && historical.value)
        || (mode === 'head' && followingAtStart && !following)
      )) {
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
      // Recovery retains the old DOM but retires its page cache. A reader can
      // stop following while the tail request is pending; revalidate their
      // current anchor instead of merging into that empty cache and publishing
      // an empty transcript. The anchor read also handles a disjoint live tail.
      const savedAnchor = showingSaved.value && !following ? saved.value!.rows.find(r => r.id===protectedRow) : undefined;
      // A reader may have scrolled the disk page while this network request was outstanding.
      const anchor = mode === 'sync' ? savedAnchor ?? (cache.pageCount===0 ? readingAnchor() : undefined)
        : mode==='restore' && savedAnchor && (savedAnchor.rawTurnId!==query.turn_id || savedAnchor.itemId!==query.item_id) ? savedAnchor : undefined;
      if (anchor?.rawTurnId && anchor.itemId) {
        return await load({ turn_id: anchor.rawTurnId, item_id: anchor.itemId, direction: 'asc' }, 'restore');
      }
      if (query.cursor && (mode === 'older' ? result.older_cursor : result.newer_cursor) === query.cursor) {
        throw new Error('Transcript cursor did not advance.');
      }
      if (mode === 'restore' && !result.turns.some(turn => turn.rawTurnId === query.turn_id && turn.itemId === query.item_id)) {
        return await reloadWithoutAnchor(query);
      }
      if (mode === 'target' && query.item_id && !result.turns.some(turn =>
        turn.rawTurnId === query.turn_id && turn.itemId === query.item_id)) {
        throw new Error('Transcript target was not found.');
      }
      const sourceTail = mode === 'head' || mode === 'latest' || mode === 'sync';
      if (query.fill) {
        const currentRows = new Map(cache.rows.map(row => [row.id, row]));
        result.turns = result.turns.map(row => {
          const current = currentRows.get(row.id);
          return current && ((rowReadRevisions.get(row.id) ?? -1) > result.revision
            || (row.compactTool && current.tools?.[0]?.status === row.compactTool.status)) ? current : row;
        });
      }
      const adjacent = mode === 'older' ? turns.value[0] : mode === 'newer' ? turns.value.at(-1) : undefined;
      const pageRows = adjacent && !result.turns.some(row=>row.id===adjacent.id)
        ? (mode==='older' ? [...result.turns,adjacent] : [adjacent,...result.turns]) : result.turns;
      saveRows(pageRows,sourceTail,!!result.older_cursor || mode==='newer',!sourceTail && (!!result.newer_cursor || mode==='older'));
      if (sourceTail) options.acceptedHead?.(result);
      saved.value=null;
      if (mode === 'older' || mode === 'newer') {
        lastDirection = query.fill ? 'newer' : mode;
        cache.extend(result, query.fill ? 'tail-context' : mode, protectedRow);
      } else if ((mode === 'latest' && !needsHead.value) || (keepLiveContext && following)) {
        lastDirection = 'newer';
        cache.returnToLatest(result);
      } else if (mode === 'sync' && cache.pageCount > 0 && !following && protectedRow && turns.value.length) {
        cache.refreshTail(result, protectedRow);
      } else {
        lastDirection = 'newer';
        cache.replace(result, mode === 'head' || mode === 'latest' || mode === 'sync' || !result.newer_cursor);
        rowReadRevisions.clear();
      }
      for (const row of result.turns) rowReadRevisions.set(row.id, Math.max(rowReadRevisions.get(row.id) ?? -1, result.revision));
      if (cache.atTail && mode !== 'older') tailReadRevision = result.revision;
      focusPerformance.record('transcript', { durationMs: Date.now() - startedAt });
      publishWindow();
      if (cache.atTail && mode !== 'older') unseenNewer.value = false;
      needsHead.value = false;
      for (const pending of buffer) {
        if (pending.event.runtime_epoch === result.runtime_epoch) {
          applyDelta(pending.event, pending.detail);
        }
      }
      if (!needsHead.value && !pendingHead) automaticAttempts = 0;
      const activeReturn = pendingInstanceReturn;
      if (mode === 'sync' && activeReturn?.scope === scope && !needsHead.value && !pendingHead
        && ((returning === activeReturn && activeReturn.recoveryStarted) || activeReturn.wake === 'confirmed')) {
        if (!followingAtStart || !following) cancelTailContext();
        else offerTailContext();
      } else if ((mode === 'sync' || mode === 'head') && !activeReturn && ordinaryTail && following && !needsHead.value && !pendingHead) {
        offerTailContext();
      }
      if (query.fill && cache.older === query.cursor) {
        tailReadsLeft = 0;
        return false;
      }
      return true;
    } catch (failure) {
      if (current()) {
        if (options.reportFatalError?.(failure)) return false;
        if (mode === 'restore' && failure instanceof FocusApiError && failure.code === 'transcript_item_missing') {
          return await reloadWithoutAnchor(query);
        }
        if (query.fill) {
          if (confirmedFill && returning === pendingInstanceReturn && tailReadsLeft && following
            && isStaleWebReadError(failure, 'stale_thread_read')) {
            // Revalidate from the head. Even an overlapping head cannot
            // authorize reuse of the refused cursor from an older source page.
            needsHead.value = true;
            await load({}, 'sync');
            return false;
          }
          tailReadsLeft = 0;
        } else error.value = failure instanceof Error ? failure.message : String(failure);
        for (const pending of buffer) applyDelta(pending.event, pending.detail);
      }
      return false;
    } finally {
      intent?.removeEventListener('abort', abandonIntent);
      if (current()) {
        loading.value = false;
        filling = false;
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

  function extendSaved(direction: 'older'|'newer'): boolean {
    const current = visibleTurns.value;
    const edge = direction==='older' ? current[0] : current.at(-1);
    if (!edge?.rawTurnId || !edge.itemId) return false;
    const page=readSavedWindow(options.activeThreadId.value,options.api.mobileReadScope,{direction,turn:edge.rawTurnId,item:edge.itemId});
    if (!page) return false;
    const ids = new Set(current.map(row=>row.id));
    const extra = savedTurns(page).filter(row=>!ids.has(row.id));
    if (!extra.length) return false;
    const older=direction==='older';
    const joined=older ? [...extra,...current] : [...current,...extra];
    if (older) page.newer=joined.length>108 || (showingSaved.value ? saved.value!.page.newer : hasNewer.value);
    else page.older=joined.length>108 || (showingSaved.value ? saved.value!.page.older : hasOlder.value);
    saved.value={page,rows:older ? joined.slice(0,108) : joined.slice(-108)};
    if (older) { following=false; protectedRow ??= edge.id; }
    return true;
  }
  async function fetchMissing(direction: 'older'|'newer') {
    const edge = direction==='older' ? visibleTurns.value[0] : visibleTurns.value.at(-1);
    if (!enabled.value || !edge?.rawTurnId || !edge.itemId) { error.value='这部分记录需要联网加载'; return false; }
    // Reopen a stable item online to obtain fresh page bounds. Disk never supplies an upstream cursor.
    if (!await load({turn_id:edge.rawTurnId,item_id:edge.itemId,direction:'asc'},'restore')) return false;
    const i=turns.value.findIndex(row=>row.id===edge.id || (row.rawTurnId===edge.rawTurnId && row.itemId===edge.itemId));
    if (direction==='older' ? i>0 : i>=0 && i+1<turns.value.length) return true;
    const cursor=direction==='older' ? edges.value.older : edges.value.newer;
    return !!cursor && load({cursor,direction:direction==='older'?'desc':'asc'},direction);
  }
  function older(intent?: AbortSignal) {
    if (!intent && extendSaved('older')) return Promise.resolve(true);
    if (!intent && showingSaved.value) return fetchMissing('older');
    if (!hasOlder.value || loading.value) return Promise.resolve(false);
    if (intent) {
      if (intent.aborted || intent !== latestIntent || !tailReadsLeft || !cache.older || !cache.atTail || pendingHead
        || cache.pageCount >= TRANSCRIPT_CACHE_PAGES || cache.bytes >= TRANSCRIPT_CACHE_BYTES) return Promise.resolve(false);
      tailReadsLeft--;
      return load({ cursor: edges.value.older!, direction: 'desc', fill: true }, 'older', false, intent);
    }
    if (!edges.value.older && edges.value.needsOlderAnchor) return fetchMissing('older');
    return load({ cursor: edges.value.older!, direction: 'desc' }, 'older');
  }

  function newer() {
    if (extendSaved('newer')) return Promise.resolve(true);
    if (showingSaved.value) return fetchMissing('newer');
    if (!hasNewer.value || loading.value) return Promise.resolve(false);
    const last = turns.value.at(-1);
    const query: FocusTranscriptQuery = edges.value.newer
      ? { cursor: edges.value.newer, direction: 'asc' }
      : { turn_id: last?.rawTurnId, item_id: last?.itemId, direction: 'asc' };
    return load(query, 'newer');
  }

  function finishLatest(intent: AbortSignal) {
    if (!intent.aborted && latestIntent === intent && ordinaryTail && following && !awaitingProjection
      && !loading.value && !needsHead.value && !pendingHead && !error.value) offerTailContext();
  }

  function tailFilled() {
    if (!following || !cache.atTail || (!ordinaryTail && !pendingInstanceReturn)) return;
    tailReadsLeft = MAX_TAIL_FILL_READS;
    if (!awaitingProjection && !loading.value && !needsHead.value && !pendingHead) offerTailContext();
  }

  function updateViewport(anchorId: string | null, isFollowing: boolean) {
    if (isFollowing && !following && cache.atTail && !loading.value) {
      ordinaryTail = true;
      if (!pendingInstanceReturn && activeMode !== 'latest') offerTailContext();
    }
    following = isFollowing;
    protectedRow = isFollowing ? null : anchorId;
  }

  async function locate(turnId: string, itemId?: string, intent?: AbortSignal): Promise<string | null> {
    if (!await load({ turn_id: turnId, direction: 'asc', ...(itemId ? { item_id: itemId } : {}) }, 'target', false, intent)) return null;
    return turns.value.find((turn) => turn.rawTurnId === turnId && (!itemId || turn.itemId === itemId))?.id ?? null;
  }

  async function loadToolMembers(turn: ChatTurn, signal: AbortSignal): Promise<boolean> {
    const compact = turn.compactTool;
    if (!compact || !enabled.value || signal.aborted || awaitingProjection) return false;
    if (!cache.rows.includes(turn)) return false;
    memberController?.abort();
    const request = new AbortController();
    memberController = request;
    const cancelMember = () => request.abort();
    signal.addEventListener('abort', cancelMember, { once: true });
    const scope = identity();
    try {
      const page = await readTranscriptTarget(options.api, options.activeThreadId.value, options.snapshot.value!.runtime_epoch,
        { cursor: compact.cursor, direction: 'desc' }, request.signal, () => scope === identity() && !disposed);
      if (request.signal.aborted || scope !== identity() || awaitingProjection) return false;
      const installed = cache.hydrateTools(compact.cursor, page, protectedRow);
      if (!installed.length) {
        if (cache.rows.some(row => row.compactTool?.cursor === compact.cursor)) {
          prepareReload();
          await resumeAfterReload();
        }
        return false;
      }
      for (const id of installed) rowReadRevisions.set(id, page.revision);
      publishWindow();
      return true;
    } catch (failure) {
      if (!request.signal.aborted && scope === identity()) options.reportFatalError?.(failure);
      return false;
    } finally {
      signal.removeEventListener('abort', cancelMember);
      if (memberController === request) memberController = null;
    }
  }

  async function openFull(turn: ChatTurn) {
    if (!turn.rawTurnId || !turn.itemId) return;
    closeFull();
    const request = detailGeneration;
    const scope = identity();
    const threadId = options.activeThreadId.value;
    fullController = new AbortController();
    fullTarget = turn;
    const tool = turn.tools?.[0];
    fullTool.value = tool ? { name: tool.name, arg: tool.arg, status: tool.status } : null;
    fullLoading.value = true;
    try {
      const result = await readTranscriptTarget(options.api, threadId, options.snapshot.value?.runtime_epoch ?? '', {
        turn_id: turn.rawTurnId, item_id: turn.itemId, full: true,
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

  const stopSaved = watch(options.activeThreadId, restoreSaved, {flush:'post'});
  const stopIdentity = watch(identity, reset, { flush: 'sync' });
  const stopSnapshot = watch([enabled, () => options.snapshot.value?.revision], () => {
    if (awaitingProjection || !enabled.value) return;
    if (historical.value) unseenNewer.value = true;
    else if (loading.value) scheduleHead();
    else void loadInitialWindow();
  }, { immediate: true });
  function dispose() { flushLive(); disposed = true; saved.value=null; reset(); stopIdentity(); stopSnapshot(); stopSaved(); }

  return { enabled, turns, visibleTurns, showingSaved, savedTitle:computed(()=>showingSaved.value ? saved.value!.page.title : ''),
    recheckSaved() {
      if (showingSaved.value && !readSavedWindow(options.activeThreadId.value,options.api.mobileReadScope,{direction:'open'})) saved.value=null;
    },
    clearSaved:()=>{saved.value=null; clearTimeout(saveTimer); saveTimer=undefined; pendingWrite=undefined;}, flushLive, loading, error, historical,
    hasOlder:computed(()=>showingSaved.value ? saved.value!.page.older : hasOlder.value),
    hasNewer:computed(()=>showingSaved.value ? saved.value!.page.newer || unseenNewer.value : hasNewer.value),
    fullText, fullTool, fullLoading, fullError, loadToolMembers, openFull, closeFull,
    refreshFull: () => { if (fullTarget) void openFull(fullTarget); },
    handleDelta, load, retry: () => cache.pageCount === 0 ? loadReadingWindow() : load(),
    older, newer, locate, updateViewport, cancelTarget, prepareReload, resumeAfterReload,
    prepareInitialReturn, expectInstanceReturn, captureForegroundReturn, confirmForegroundWake,
    cancelTailContext, tailContext, tailFilled, finishLatest, reset, dispose };
}
