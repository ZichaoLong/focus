import { computed, ref, shallowRef } from 'vue';
import type { FocusExportTurn, FocusExportTurnPage, FocusSummaryExportSelection } from './types';
import { summaryDocumentBody } from './summaryDocumentTitle';

export const MAX_SELECTED_EXPORT_TURNS = 100;

/** Dialog-local selection survives page changes, never a thread/dialog change. */
export function createExportTurnSelection(ports: {
  listExportTurns(threadId: string, cursor?: string, signal?: AbortSignal): Promise<FocusExportTurnPage>;
  previewExportTurn(threadId: string, turnId: string, content: FocusSummaryExportSelection['content'], signal?: AbortSignal): Promise<Blob>;
}) {
  const rows = shallowRef<FocusExportTurn[]>([]);
  const selected = ref<string[]>([]);
  const content = ref<FocusSummaryExportSelection['content']>('qa');
  const selectedStatuses = ref(new Map<string, FocusExportTurn['status']>());
  const unavailableSelectedCount = computed(() => content.value === 'prompts' ? 0
    : selected.value.filter(id => selectedStatuses.value.get(id) !== 'completed').length);
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
    const union = new Set([...selected.value, ...rows.value.filter(canSelect).map(row => row.turn_id)]);
    return !loading.value && union.size > selected.value.length && union.size <= MAX_SELECTED_EXPORT_TURNS;
  });

  function closePreview() {
    previewController?.abort(); previewController = null;
    previewId.value = ''; previewText.value = ''; previewError.value = ''; previewLoading.value = false;
  }
  function setContent(value: FocusSummaryExportSelection['content']) {
    if (content.value === value) return;
    closePreview(); content.value = value;
  }
  function canSelect(row: FocusExportTurn) {
    return content.value === 'prompts' || row.status === 'completed';
  }
  function clear() {
    selected.value = []; selectedStatuses.value.clear();
  }
  function reset() {
    generation += 1; controller?.abort(); controller = null; closePreview();
    threadId = ''; rows.value = []; clear(); pageIndex.value = 0;
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
      for (const row of page.turns) if (selected.value.includes(row.turn_id)) selectedStatuses.value.set(row.turn_id, row.status);
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
    if (selected.value.includes(row.turn_id)) {
      selected.value = selected.value.filter(id => id !== row.turn_id);
      selectedStatuses.value.delete(row.turn_id);
    } else if (canSelect(row) && selected.value.length < MAX_SELECTED_EXPORT_TURNS) {
      selected.value = [...selected.value, row.turn_id];
      selectedStatuses.value.set(row.turn_id, row.status);
    }
  }
  function selectPage() {
    if (!canSelectPage.value) return;
    for (const row of rows.value.filter(canSelect)) {
      if (!selected.value.includes(row.turn_id)) selected.value = [...selected.value, row.turn_id];
      selectedStatuses.value.set(row.turn_id, row.status);
    }
  }
  async function preview(row: FocusExportTurn) {
    if (!canSelect(row)) return;
    if (previewId.value === row.turn_id) { closePreview(); return; }
    closePreview();
    const request = new AbortController(); previewController = request;
    previewId.value = row.turn_id; previewLoading.value = true;
    try {
      const blob = await ports.previewExportTurn(threadId, row.turn_id, content.value, request.signal);
      const text = await blob.text();
      if (previewController === request) previewText.value = summaryDocumentBody(text);
    } catch (failure) {
      if (previewController === request) previewError.value = failure instanceof Error ? failure.message : String(failure);
    } finally {
      if (previewController === request) previewLoading.value = false;
    }
  }
  return { rows, selected, content, setContent, canSelect, unavailableSelectedCount, pageIndex, loading, error, hasNext, canSelectPage,
    previewId, previewText, previewLoading, previewError, open, reset, load, toggle, selectPage, preview,
    clear };
}
