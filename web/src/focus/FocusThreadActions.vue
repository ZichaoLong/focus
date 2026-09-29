<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';
import Dialog from '../components/ui/Dialog.vue';
import Input from '../components/ui/Input.vue';
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
const filename = computed(() => request.value ? normalizeExportFilename(value.value, request.value.format) : '');

function requestExportOptions(options: ExportOptionsRequest): Promise<ExportOptionsChoice | null> {
  value.value = options.suggestedFilename;
  documentTitle.value = options.suggestedDocumentTitle ?? '';
  return new Promise((resolve) => { request.value = { ...options, resolve }; });
}
function settle(choice: ExportOptionsChoice | null): void {
  const pending = request.value;
  request.value = null;
  pending?.resolve(choice);
}
function submit(): void {
  if (filename.value) settle({
    filename: filename.value,
    ...(request.value?.format === 'markdown' ? { documentTitle: documentTitle.value } : {}),
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
    :title="t(request?.format === 'jsonl' ? 'header.exportThreadData' : 'header.exportSession')"
    :description="t('focus.exportFilenameHelp')"
    initial-focus="input"
    @update:open="!$event && settle(null)"
  >
    <form class="export-form" @submit.prevent="submit">
      <label class="export-label">
        <span>{{ t('focus.exportFilename') }}</span>
        <Input v-model="value" autocomplete="off" :spellcheck="false" aria-describedby="export-filename-preview" @focus="selectStem" />
      </label>
      <p id="export-filename-preview" class="export-preview" aria-live="polite">
        {{ filename ? t('focus.exportFilenamePreview', { filename }) : t('focus.exportFilenameRequired') }}
      </p>
      <p class="export-preview">{{ t('focus.exportSaveLocationHelp') }}</p>
      <label v-if="request?.format === 'markdown'" class="export-label">
        <span>{{ t('focus.exportDocumentTitle') }}</span>
        <Input v-model="documentTitle" autocomplete="off" :placeholder="DEFAULT_SUMMARY_TITLE" aria-describedby="export-title-help" />
      </label>
      <p v-if="request?.format === 'markdown'" id="export-title-help" class="export-preview">{{ t('focus.exportDocumentTitleHelp') }}</p>
      <div class="export-actions">
        <Button type="button" variant="secondary" @click="settle(null)">{{ t('focus.cancel') }}</Button>
        <Button type="submit" variant="primary" :disabled="!filename">{{ t('focus.exportDownload') }}</Button>
      </div>
    </form>
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
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
