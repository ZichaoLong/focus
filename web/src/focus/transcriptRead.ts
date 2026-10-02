import type { FocusWebApiPort } from './api';
import { isStaleWebReadError, type FocusTranscriptPage, type FocusTranscriptQuery } from './types';

/** Bounded individual reads; old servers may need cancellable string-cursor pages. */
export async function readTranscriptTarget(
  api: Pick<FocusWebApiPort, 'readTranscriptWindow'>,
  threadId: string,
  epoch: string,
  query: FocusTranscriptQuery,
  signal: AbortSignal,
  current: () => boolean,
): Promise<FocusTranscriptPage> {
  let request = query;
  const seen = new Set<string>();
  while (true) {
    if (!current() || signal.aborted) throw new DOMException('Read cancelled.', 'AbortError');
    let result: FocusTranscriptPage;
    try {
      result = await api.readTranscriptWindow(threadId, request, signal);
    } catch (failure) {
      if (!isStaleWebReadError(failure) || !current() || signal.aborted) throw failure;
      result = await api.readTranscriptWindow(threadId, request, signal);
    }
    if (result.thread_id !== threadId || result.runtime_epoch !== epoch
      || result.turn_id !== (query.turn_id ?? null) || result.view !== (query.view ?? 'transcript')) {
      throw new Error('Transcript identity changed.');
    }
    if (!result.target_pending) return result;
    const cursor = result.newer_cursor;
    if (!query.item_id || !cursor || seen.has(cursor)) throw new Error('Transcript cursor did not advance.');
    seen.add(cursor);
    if (seen.size > 256) seen.delete(seen.values().next().value!);
    request = { ...query, cursor, direction: 'asc' };
  }
}
