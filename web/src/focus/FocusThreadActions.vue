<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';
import Dialog from '../components/ui/Dialog.vue';
import Input from '../components/ui/Input.vue';
import Select from '../components/ui/Select.vue';
import ExportTurnPicker from './ExportTurnPicker.vue';
import { createExportTurnSelection, MAX_SELECTED_EXPORT_TURNS } from './exportTurnSelection';
import type { FocusSummaryExportSelection } from './types';
import { normalizeExportFilename } from './exportFilename';
import { DEFAULT_SUMMARY_TITLE } from './summaryDocumentTitle';
import { createFocusThreadActions, type ExportOptionsChoice, type ExportOptionsRequest, type FocusThreadActionsOptions } from './focusThreadActions';
import type { useFocusWebClient } from './useFocusWebClient';

const props = defineProps<{
  client: ReturnType<typeof useFocusWebClient>;
  confirm: (options: Parameters<FocusThreadActionsOptions['confirm']>[0]) => Promise<boolean>;
  notify: (message: string) => void;
}>();
const { t } = useI18n();
const request = shallowRef<(ExportOptionsRequest & { resolve: (value: ExportOptionsChoice | null) => void }) | null>(null);
const value = ref('');
const documentTitle = ref('');
const scope = ref<FocusSummaryExportSelection['scope']>('all');
const selection = reactive(createExportTurnSelection({
  listExportTurns: (...args) => props.client.listExportTurns(...args),
  previewExportTurn: (...args) => props.client.previewExportTurn(...args),
}));
const filename = computed(() => request.value ? normalizeExportFilename(value.value, request.value.format) : '');
const canSubmit = computed(() => Boolean(filename.value) && (request.value?.format === 'jsonl'
  || scope.value !== 'selected' || (selection.selected.length > 0 && !selection.loading && !selection.unavailableSelectedCount)));
watch(() => [request.value?.threadId, scope.value], () => {
  if (request.value && scope.value === 'selected') selection.open(request.value.threadId);
});

function changeScope(value: string): void {
  if (value === 'all' || value === 'last_turn' || value === 'selected') scope.value = value;
}
function changeContent(value: string): void {
  if (value === 'qa' || value === 'final_answers' || value === 'prompts') selection.setContent(value);
}

function requestExportOptions(options: ExportOptionsRequest): Promise<ExportOptionsChoice | null> {
  scope.value = 'all';
  selection.reset();
  selection.setContent('qa');
  value.value = options.suggestedFilename;
  documentTitle.value = options.suggestedDocumentTitle ?? '';
  return new Promise((resolve) => { request.value = { ...options, resolve }; });
}
function settle(choice: ExportOptionsChoice | null): void {
  const pending = request.value;
  request.value = null;
  selection.reset();
  pending?.resolve(choice);
}
function submit(): void {
  if (!canSubmit.value || (request.value?.onConfirm && !request.value.onConfirm())) return;
  settle({
    filename: filename.value,
    ...(request.value?.format !== 'jsonl' ? {
      documentTitle: documentTitle.value,
      selection: { scope: scope.value, turn_ids: scope.value === 'selected' ? [...selection.selected] : [], content: selection.content },
    } : {}),
  });
}
function selectStem(event: FocusEvent): void {
  const input = event.target as HTMLInputElement;
  const extensionStart = input.value.lastIndexOf('.');
  input.setSelectionRange(0, extensionStart < 0 ? input.value.length : extensionStart);
}
function getThreadTitle(threadId: string): string {
  const active = props.client.activeThread.value;
  if (active?.id === threadId) return active.title;
  return props.client.sessions.value.find((session) => session.id === threadId)?.title
    ?? props.client.searchSessions.value.find((session) => session.id === threadId)?.title ?? '';
}

const actions = createFocusThreadActions({
  client: props.client, confirm: props.confirm, notify: props.notify,
  translate: (key) => t(key), getThreadTitle, requestExportOptions,
});
onBeforeUnmount(() => settle(null));
defineExpose(actions);
</script>

<template>
  <Dialog
    :open="request !== null"
    :title="t(request?.format === 'jsonl' ? 'header.exportThreadData' : request?.format === 'print' ? 'focus.printSummary' : 'header.exportSession')"
    :description="t(request?.format === 'jsonl' ? 'focus.exportFilenameHelp' : 'focus.exportScopeHelp')"
    size="lg"
    :initial-focus="request?.format === 'jsonl' ? 'input' : 'select'"
    @update:open="!$event && settle(null)"
  >
    <form id="focus-export-options" class="export-form" @submit.prevent="submit">
      <label v-if="request?.format !== 'jsonl'" class="export-label">
        <span>{{ t('focus.exportScope') }}</span>
        <Select :model-value="scope" @update:model-value="changeScope">
          <option value="all">{{ t('focus.exportAll') }}</option>
          <option value="last_turn">{{ t('focus.exportLastTurn') }}</option>
          <option value="selected">{{ t('focus.exportSelected') }}</option>
        </Select>
      </label>
      <label v-if="request?.format !== 'jsonl'" class="export-label">
        <span>{{ t('focus.exportContent') }}</span>
        <Select :model-value="selection.content" @update:model-value="changeContent">
          <option value="qa">{{ t('focus.exportContentQa') }}</option>
          <option value="final_answers">{{ t('focus.exportContentAnswers') }}</option>
          <option value="prompts">{{ t('focus.exportContentPrompts') }}</option>
        </Select>
      </label>
      <p v-if="request?.format !== 'jsonl'" class="export-preview">
        {{ t(selection.content === 'prompts' ? 'focus.exportPromptsHelp' : 'focus.exportAnswersHelp') }}
      </p>
      <p v-if="request?.format !== 'jsonl' && scope === 'last_turn'" class="export-preview">{{ t(selection.content === 'prompts' ? 'focus.exportLastPromptsHelp' : 'focus.exportLastTurnHelp') }}</p>
      <ExportTurnPicker v-if="request?.format !== 'jsonl' && scope === 'selected'" :selection="selection" />
      <label v-if="request?.format !== 'print'" class="export-label">
        <span>{{ t('focus.exportFilename') }}</span>
        <Input v-model="value" autocomplete="off" :spellcheck="false" aria-describedby="export-filename-preview" @focus="selectStem" />
      </label>
      <p v-if="request?.format !== 'print'" id="export-filename-preview" class="export-preview" aria-live="polite">
        {{ filename ? t('focus.exportFilenamePreview', { filename }) : t('focus.exportFilenameRequired') }}
      </p>
      <p v-if="request?.format !== 'print'" class="export-preview">{{ t('focus.exportSaveLocationHelp') }}</p>
      <label v-if="request?.format !== 'jsonl'" class="export-label">
        <span>{{ t('focus.exportDocumentTitle') }}</span>
        <Input v-model="documentTitle" autocomplete="off" :placeholder="DEFAULT_SUMMARY_TITLE" aria-describedby="export-title-help" />
      </label>
      <p v-if="request?.format !== 'jsonl'" id="export-title-help" class="export-preview">{{ t('focus.exportDocumentTitleHelp') }}</p>
    </form>
    <template #foot>
      <div class="export-actions">
        <span v-if="request?.format !== 'jsonl' && scope === 'selected'" class="export-selected-count" role="status">
          {{ t('focus.exportSelectedCount', { count: selection.selected.length, max: MAX_SELECTED_EXPORT_TURNS }) }}
        </span>
        <Button type="button" variant="secondary" @click="settle(null)">{{ t('focus.cancel') }}</Button>
        <Button type="submit" form="focus-export-options" variant="primary" :disabled="!canSubmit">{{ t(request?.format === 'print' ? 'focus.exportOpenPrint' : 'focus.exportDownload') }}</Button>
      </div>
    </template>
  </Dialog>
</template>

<style scoped>
.export-form, .export-label {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.export-form { gap: var(--space-4); }
.export-label { font-size: var(--text-sm); }
.export-preview {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
}
.export-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--space-2);
}
.export-selected-count { margin-right: auto; color: var(--color-text-muted); font-size: var(--text-sm); }
</style>
