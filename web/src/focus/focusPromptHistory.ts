import { computed, ref, shallowRef, watch, type Ref } from 'vue';
import type { ChatTurn } from '../types';
import type { FocusWebApiPort } from './api';
import type { FocusThreadDeltaDetail, FocusThreadSnapshot } from './types';
import { FOCUS_HISTORY_PROMPT_LIMIT, normalizedPromptTitle, type FocusHistoryPrompt } from './focusHistoryNavigation';
import { readTranscriptTarget } from './transcriptRead';

interface Prompt extends FocusHistoryPrompt { rawTurnId: string; itemId: string }

const PROMPTS_PER_BATCH = 20;
const READS_PER_BATCH = 8;

function prompt(turn: ChatTurn): Prompt | null {
  if (turn.role !== 'user' || !turn.rawTurnId || !turn.itemId) return null;
  const normalized = normalizedPromptTitle(turn.text);
  return { id: turn.id, rawTurnId: turn.rawTurnId, itemId: turn.itemId, role: 'user', no: 0,
    title: normalized.title, titleTruncated: normalized.truncated,
    recent: false, pageCursor: null };
}

/** On-demand user-message directory, independent of the visible body window. */
export function createFocusPromptHistory(options: {
  api: Pick<FocusWebApiPort, 'readTranscriptWindow'>;
  snapshot: Readonly<Ref<FocusThreadSnapshot | null>>;
  enabled: Readonly<Ref<boolean>>;
  isDisposed(): boolean;
  reportError(error: unknown): void;
}) {
  const scanned = shallowRef<Prompt[]>([]);
  const live = shallowRef<Prompt[]>([]);
  const loading = ref(false);
  const error = ref(false);
  const complete = ref(false);
  const scanTruncated = ref(false);
  let cursor: string | undefined;
  let generation = 0;
  let visible = false;
  let disposed = false;
  let controller: AbortController | null = null;
  let scanStarted = false;
  let buffered: Prompt[] = [];
  const seen = new Set<string>();
  const seed = computed(() => (options.snapshot.value?.turns ?? []).flatMap((turn) => {
    const entry = prompt(turn); return entry ? [entry] : [];
  }));
  const collected = computed<Prompt[]>(() => {
    if (!options.enabled.value || options.isDisposed()) return [];
    // Scanned pages arrive newest first. Keep the first prompt at the start of
    // its turn while that turn's additional messages are still being fetched.
    const groups = new Map<string, Map<string, Prompt>>();
    const order = [...new Set([...scanned.value, ...seed.value, ...live.value].map((p) => p.rawTurnId).reverse())].reverse();
    for (const item of [...seed.value, ...scanned.value, ...live.value]) {
      const group = groups.get(item.rawTurnId) ?? new Map<string, Prompt>();
      group.set(item.id, item); groups.set(item.rawTurnId, group);
    }
    return order.flatMap((id) => [...(groups.get(id)?.values() ?? [])]);
  });
  const outline = computed(() => collected.value.slice(-FOCUS_HISTORY_PROMPT_LIMIT)
    .map((entry, index) => ({ ...entry, no: index + 1 })));
  const truncated = computed(() => scanTruncated.value || collected.value.length > FOCUS_HISTORY_PROMPT_LIMIT);
  const hasMore = computed(() => options.enabled.value && !options.isDisposed() && !complete.value && !truncated.value);

  function identity() { return `${options.enabled.value}\n${options.snapshot.value?.thread.id}\n${options.snapshot.value?.runtime_epoch}\n${options.isDisposed()}`; }
  function pause() {
    generation += 1;
    controller?.abort(); controller = null; loading.value = false;
    scanned.value = buffered;
  }
  function reset() {
    pause(); scanned.value = []; live.value = []; seen.clear(); cursor = undefined;
    complete.value = false; scanTruncated.value = false; error.value = false;
    buffered = []; scanStarted = false;
  }
  async function loadMore() {
    if (!hasMore.value || loading.value || disposed || options.isDisposed()) return;
    const scope = identity();
    const request = ++generation;
    const requestController = new AbortController(); controller = requestController;
    const current = () => request === generation && scope === identity() && !disposed && !options.isDisposed();
    const initialCount = buffered.length;
    scanStarted = true;
    loading.value = true; error.value = false;
    try {
      for (let reads = 0; reads < READS_PER_BATCH && current() && hasMore.value
        && buffered.length - initialCount < PROMPTS_PER_BATCH; reads += 1) {
        const snapshot = options.snapshot.value!;
        const page = await readTranscriptTarget(options.api, snapshot.thread.id, snapshot.runtime_epoch,
          { view: 'prompts', ...(cursor ? { cursor } : {}) }, requestController.signal, current);
        if (!current()) return;
        if (page.older_cursor && (seen.has(page.older_cursor) || page.older_cursor === cursor)) {
          throw new Error('Prompt history cursor did not advance.');
        }
        if (page.older_cursor) seen.add(page.older_cursor);
        if (seen.size > 256) seen.delete(seen.values().next().value!);
        const entries = page.turns.flatMap((turn) => { const entry = prompt(turn); return entry ? [entry] : []; });
        const byId = new Map([...entries, ...buffered].map((entry) => [entry.id, entry]));
        const all = [...byId.values()];
        buffered = all.slice(-FOCUS_HISTORY_PROMPT_LIMIT);
        scanTruncated.value = all.length > FOCUS_HISTORY_PROMPT_LIMIT
          || (all.length === FOCUS_HISTORY_PROMPT_LIMIT && !!page.older_cursor);
        complete.value = !page.older_cursor;
        cursor = page.older_cursor ?? undefined;
        // Keep displayed entries still while collecting a bounded batch, even
        // when a large turn needs several empty scans. Continue on demand.
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      }
    } catch (failure) {
      if (current()) { error.value = true; options.reportError(failure); }
    } finally {
      if (current()) { scanned.value = buffered; loading.value = false; controller = null; }
    }
  }
  function setVisible(value: boolean) {
    visible = value;
    if (!value) pause();
    else if (!scanStarted) void loadMore();
  }
  function handleDelta(detail: FocusThreadDeltaDetail) {
    if (!options.enabled.value) return;
    const entries = (detail.item_turns ?? []).flatMap((turn) => { const entry = prompt(turn); return entry ? [entry] : []; });
    if (entries.length) live.value = [...new Map([...live.value, ...entries].map((entry) => [entry.id, entry])).values()]
      .slice(-FOCUS_HISTORY_PROMPT_LIMIT);
  }
  const stop = watch(identity, () => { reset(); if (visible) void loadMore(); }, { flush: 'sync' });
  function dispose() { disposed = true; reset(); stop(); }
  return { outline, loading, error, truncated, hasMore, setVisible, pause, loadMore, handleDelta, dispose };
}
