import { shallowRef, type ShallowRef } from 'vue';
import type { ChatTurn } from '../types';
import type { ReplyContentReader, ReplyContentState } from '../composables/replyContent';

const CACHE_BYTES = 4 * 1024 * 1024;
const CACHE_ITEMS = 4;

/** Exact reply reads have one flight, scoped leases and a small inactive LRU. */
export function createFocusReplyContent(options: {
  read(turn: ChatTurn, signal: AbortSignal): Promise<string>;
  reportFatalError?(error: unknown): boolean;
}): ReplyContentReader & { reset(): void } {
  type Entry = {
    turn: ChatTurn; users: number; state: ShallowRef<ReplyContentState>;
    controller: AbortController | null;
  };
  const entries = new Map<string, Entry>();
  let running: Entry | null = null;
  let generation = 0;

  function prune() {
    const inactive = [...entries].filter(([, entry]) => !entry.users);
    let bytes = inactive.reduce((sum, [, entry]) => sum + (entry.state.value.text?.length ?? 0) * 2, 0);
    let count = inactive.length;
    for (const [key, entry] of inactive) {
      if (bytes <= CACHE_BYTES && count <= CACHE_ITEMS) break;
      entries.delete(key);
      bytes -= (entry.state.value.text?.length ?? 0) * 2;
      count -= 1;
    }
  }

  function pump() {
    if (running) return;
    const entry = [...entries.values()].find(item => item.users && item.state.value.loading && !item.controller);
    if (!entry) return;
    running = entry;
    const controller = new AbortController();
    entry.controller = controller;
    const scope = generation;
    const current = () => generation === scope && !controller.signal.aborted;
    void options.read(entry.turn, controller.signal).then(text => {
      if (current()) entry.state.value = { text, loading: false, error: '' };
    }, failure => {
      if (current()) {
        options.reportFatalError?.(failure);
        entry.state.value = { text: null, loading: false,
          error: failure instanceof Error ? failure.message : String(failure) };
      }
    }).finally(() => {
      if (running === entry) running = null;
      entry.controller = null;
      prune(); pump();
    });
  }

  return {
    acquire(turn) {
      if (!turn.reply || turn.role !== 'assistant' || !turn.rawTurnId || !turn.itemId || !turn.contentDeferred) {
        throw new Error('Inline reading requires an exact assistant reply.');
      }
      const key = JSON.stringify([turn.rawTurnId, turn.itemId, turn.reply.state, turn.reply.completedAtMs, turn.status]);
      let entry = entries.get(key);
      if (!entry) {
        entry = { turn, users: 0, controller: null,
          state: shallowRef<ReplyContentState>({ text: null, loading: true, error: '' }) };
      }
      entries.delete(key); entries.set(key, entry);
      entry.users += 1;
      pump();
      let released = false;
      return {
        state: entry.state,
        retry() {
          if (released || entry.state.value.loading || !entry.state.value.error) return;
          entry.state.value = { text: null, loading: true, error: '' }; pump();
        },
        release() {
          if (released) return;
          released = true;
          entry.users -= 1;
          if (!entry.users && entry.state.value.loading) {
            entry.controller?.abort();
            if (entries.get(key) === entry) entries.delete(key);
          }
          prune();
        },
      };
    },
    reset() {
      generation += 1;
      for (const entry of entries.values()) {
        entry.controller?.abort();
        entry.state.value = { text: null, loading: false, error: '' };
      }
      entries.clear();
      // The in-flight operation drains before admitting another read.
    },
  };
}
