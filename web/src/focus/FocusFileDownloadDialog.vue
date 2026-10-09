<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';
import Dialog from '../components/ui/Dialog.vue';
import Input from '../components/ui/Input.vue';
import { useNarrowViewport } from '../composables/useNarrowViewport';
import type { FilePreviewRequest } from '../types';
import { createFileDownload, formatFileSize, type FileDownloadApi } from './fileDownload';
import { createFilePreview, filePreviewKind, filePreviewLimit } from './filePreview';
import FocusFilePreview from './FocusFilePreview.vue';

const props = defineProps<{ api: FileDownloadApi }>();
const { t } = useI18n();
const download = createFileDownload(props.api);
const preview = createFilePreview(props.api);
const narrow = useNarrowViewport();
const targetLine = ref<number | undefined>();
const previewKind = computed(() => filePreviewKind(download.info.value?.name ?? ''));
const previewLimit = computed(() => filePreviewLimit(previewKind.value ?? 'text'));
const notice = ref('');
let noticeTimer: ReturnType<typeof setTimeout> | undefined;

watch(download.statusKey, key => {
  if (!key) return;
  clearTimeout(noticeTimer);
  notice.value = key;
  noticeTimer = setTimeout(() => { notice.value = ''; }, 4500);
});
watch(download.opened, async isOpen => {
  if (!preview.opened.value) return;
  await nextTick();
  document.querySelector<HTMLElement>(isOpen ? '.file-download-form input, .file-download-actions button' : '.file-preview-toolbar button')?.focus({ preventScroll: true });
});

function open(path: string, cwd: string, line?: number): Promise<void> {
  preview.close();
  targetLine.value = line;
  notice.value = '';
  return download.open(path, cwd);
}

function openLinkedFile(target: FilePreviewRequest): void {
  const path = preview.file.value?.path ?? '';
  const separator = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
  void open(target.path, path.slice(0, separator + 1), target.line);
}

function showPreview(): void {
  if (!download.info.value) return;
  void preview.open(download.info.value, targetLine.value);
  download.close();
  void nextTick(() => document.querySelector<HTMLElement>('.file-preview-toolbar button')?.focus({ preventScroll: true }));
}

function showDownload(): void {
  if (preview.file.value) void download.open(preview.file.value.path, '');
}

function close(): void {
  if (download.opened.value) download.close();
  else preview.close();
}

onBeforeUnmount(() => { clearTimeout(noticeTimer); download.close(); preview.close(); });
defineExpose({ open });
</script>

<template>
  <Dialog :open="download.opened.value || preview.opened.value" :title="t(download.opened.value ? 'focus.fileDownloadTitle' : 'focus.filePreviewTitle')"
    :size="download.opened.value ? 'md' : narrow ? 'full' : 'xl'" :height="download.opened.value || narrow ? 'auto' : 'fixed'"
    :padded="download.opened.value" @update:open="!$event && close()">
    <form v-if="download.opened.value" class="file-download-form" @submit.prevent="download.save">
      <p class="file-download-path">{{ download.path.value }}</p>
      <p v-if="download.loading.value" role="status">{{ t('focus.fileInfoLoading') }}</p>
      <template v-if="download.info.value">
        <p>{{ t('focus.fileSize', { size: formatFileSize(download.info.value.size) }) }}</p>
        <label class="file-download-label">
          <span>{{ t('focus.exportFilename') }}</span>
          <Input v-model="download.name.value" :disabled="download.busy.value" autocomplete="off" :spellcheck="false" />
        </label>
        <p class="file-download-help">{{ download.filename.value ? t('focus.exportFilenamePreview', { filename: download.filename.value }) : t('focus.exportFilenameRequired') }}</p>
        <p class="file-download-help">{{ t(download.nativePicker.value ? 'focus.fileSavePickerHelp' : 'focus.fileBrowserDownloadHelp') }}</p>
        <p v-if="!previewKind" class="file-download-help">{{ t('focus.filePreviewUnsupported') }}</p>
        <p v-else-if="download.info.value.size > previewLimit" class="file-download-help">{{ t('focus.filePreviewTooLarge', { limit: formatFileSize(previewLimit) }) }}</p>
      </template>
      <p v-if="download.busy.value" role="status">{{ t('focus.fileSaving', { size: formatFileSize(download.received.value) }) }}</p>
      <p v-if="download.errorKey.value" role="alert">{{ t(download.errorKey.value) }}</p>
      <div class="file-download-actions">
        <Button type="button" variant="secondary" @click="download.close()">{{ t('focus.cancel') }}</Button>
        <Button v-if="download.info.value && !preview.opened.value" type="button" variant="secondary" :disabled="download.busy.value || !previewKind || download.info.value.size > previewLimit" @click="showPreview">{{ t('focus.filePreviewAction') }}</Button>
        <Button v-if="download.info.value" type="submit" variant="primary" :disabled="download.busy.value || !download.filename.value">
          {{ t(download.nativePicker.value ? 'focus.fileSaveAs' : 'focus.fileDownloadAction') }}
        </Button>
      </div>
    </form>
    <FocusFilePreview v-if="preview.opened.value" v-show="!download.opened.value" :preview="preview" @download="showDownload" @open-file="openLinkedFile" />
  </Dialog>
  <Teleport to="body"><div v-if="notice" class="file-download-notice" role="status">{{ t(notice) }}</div></Teleport>
</template>

<style scoped>
.file-download-form, .file-download-label { display: flex; flex-direction: column; gap: var(--space-2); }
.file-download-form { gap: var(--space-4); }
.file-download-form p { margin: 0; overflow-wrap: anywhere; }
.file-download-path { font-family: var(--font-mono); }
.file-download-help { color: var(--color-text-muted); font-size: var(--text-sm); }
.file-download-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); }
.file-download-notice { position: fixed; bottom: var(--space-5); left: 50%; transform: translateX(-50%); z-index: var(--z-toast);
  max-width: calc(100% - var(--space-6)); box-sizing: border-box; padding: var(--space-3) var(--space-4); border: 1px solid var(--color-line);
  border-radius: var(--radius-md); background: var(--color-surface-raised); color: var(--color-text); box-shadow: var(--shadow-xl); pointer-events: none; }
</style>
