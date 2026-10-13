import { computed, ref, shallowRef } from 'vue';
import type { FocusExportTurn, FocusExportTurnPage } from './types';
import { summaryDocumentBody } from './summaryDocumentTitle';

export const MAX_SELECTED_EXPORT_TURNS = 100;

/** Dialog-local selection survives page changes, never a thread/dialog change. */
export function createExportTurnSelection(ports: {
  listExportTurns(threadId: string, cursor?: string, signal?: AbortSignal): Promise<FocusExportTurnPage>;
  previewExportTurn(threadId: string, turnId: string, signal?: AbortSignal): Promise<Blob>;
}) {
  const rows = shallowRef<FocusExportTurn[]>([]);
  const selected = ref<string[]>([]);
  const pageIndex = ref(0);
  const loading = ref(false);
  const error = ref('');
  const hasNext = ref(false);
  const previewId = ref('');
  const previewText = ref('');
  const previewLoading = ref(false);
  const previewError = ref('');
  let threadId = '';
  let cursors: Array<string | undefined> = [undefined];
  let generation = 0;
  let retryIndex = 0;
  let controller: AbortController | null = null;
  let previewController: AbortController | null = null;
  const canSelectPage = computed(() => {
    const union = new Set([...selected.value, ...rows.value.filter(row => row.status === 'completed').map(row => row.turn_id)]);
    return !loading.value && union.size > selected.value.length && union.size <= MAX_SELECTED_EXPORT_TURNS;
  });

  function closePreview() {
    previewController?.abort(); previewController = null;
    previewId.value = ''; previewText.value = ''; previewError.value = ''; previewLoading.value = false;
  }
  function reset() {
    generation += 1; controller?.abort(); controller = null; closePreview();
    threadId = ''; rows.value = []; selected.value = []; pageIndex.value = 0;
    cursors = [undefined]; retryIndex = 0; loading.value = false; error.value = ''; hasNext.value = false;
  }
  async function load(index = retryIndex) {
    if (!threadId || index < 0 || index >= cursors.length) return;
    const current = ++generation;
    retryIndex = index;
    controller?.abort(); closePreview();
    const request = new AbortController(); controller = request;
    loading.value = true; error.value = '';
    try {
      const page = await ports.listExportTurns(threadId, cursors[index], request.signal);
      if (current !== generation) return;
      if (page.thread_id !== threadId || (page.next_cursor && cursors.slice(0, index + 1).includes(page.next_cursor))) {
        throw new Error('The export directory did not advance or belongs to another conversation.');
      }
      rows.value = page.turns; pageIndex.value = index; hasNext.value = page.next_cursor !== null;
      cursors = cursors.slice(0, index + 1);
      if (page.next_cursor) cursors.push(page.next_cursor);
    } catch (failure) {
      if (current === generation) error.value = failure instanceof Error ? failure.message : String(failure);
    } finally {
      if (current === generation) { loading.value = false; controller = null; }
    }
  }
  function open(id: string) {
    if (threadId === id) return;
    reset(); threadId = id; void load(0);
  }
  function toggle(row: FocusExportTurn) {
    if (selected.value.includes(row.turn_id)) selected.value = selected.value.filter(id => id !== row.turn_id);
    else if (row.status === 'completed' && selected.value.length < MAX_SELECTED_EXPORT_TURNS) selected.value = [...selected.value, row.turn_id];
  }
  function selectPage() {
    if (canSelectPage.value) selected.value = [...new Set([
      ...selected.value, ...rows.value.filter(row => row.status === 'completed').map(row => row.turn_id),
    ])];
  }
  async function preview(row: FocusExportTurn) {
    if (previewId.value === row.turn_id) { closePreview(); return; }
    closePreview();
    const request = new AbortController(); previewController = request;
    previewId.value = row.turn_id; previewLoading.value = true;
    try {
      const blob = await ports.previewExportTurn(threadId, row.turn_id, request.signal);
      const text = await blob.text();
      if (previewController === request) previewText.value = summaryDocumentBody(text);
    } catch (failure) {
      if (previewController === request) previewError.value = failure instanceof Error ? failure.message : String(failure);
    } finally {
      if (previewController === request) previewLoading.value = false;
    }
  }
  return { rows, selected, pageIndex, loading, error, hasNext, canSelectPage,
    previewId, previewText, previewLoading, previewError, open, reset, load, toggle, selectPage, preview,
    clear: () => { selected.value = []; } };
}
