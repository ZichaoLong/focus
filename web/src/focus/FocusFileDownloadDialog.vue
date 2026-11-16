<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';
import Dialog from '../components/ui/Dialog.vue';
import Input from '../components/ui/Input.vue';
import { useNarrowViewport } from '../composables/useNarrowViewport';
import { createFileDownload, formatFileSize, type FileDownloadApi } from './fileDownload';
import { createFilePreview, filePreviewKind, filePreviewLimit } from './filePreview';
import { createFilePreviewNavigation } from './filePreviewNavigation';
import FocusFilePreview from './FocusFilePreview.vue';

const props = defineProps<{ api: FileDownloadApi }>();
const { t } = useI18n();
const download = createFileDownload(props.api);
const preview = createFilePreview(props.api);
const navigation = createFilePreviewNavigation(download, preview);
const narrow = useNarrowViewport();
const maximized = ref(false);
const fillsViewport = computed(() => narrow.value || maximized.value);
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
watch([download.opened, preview.opened], async ([isOpen, previewOpen]) => {
  if (!isOpen && !previewOpen) maximized.value = false;
  if (!previewOpen) return;
  await nextTick();
  document.querySelector<HTMLElement>(isOpen ? '.file-download-form input, .file-download-actions button' : '.file-preview-toolbar button')?.focus({ preventScroll: true });
});

function open(path: string, cwd: string, line?: number, anchor?: string): Promise<void> {
  notice.value = '';
  maximized.value = false;
  return navigation.open(path, cwd, line, anchor);
}

function showPreview(): void {
  void navigation.showPreview();
}

onBeforeUnmount(() => { clearTimeout(noticeTimer); navigation.closeAll(); });
defineExpose({ open });
</script>

<template>
  <Dialog :open="download.opened.value || preview.opened.value" :title="t(download.opened.value ? 'focus.fileDownloadTitle' : 'focus.filePreviewTitle')"
    :size="download.opened.value ? 'md' : fillsViewport ? 'full' : 'wide'" :height="download.opened.value || fillsViewport ? 'auto' : 'viewport'"
    :padded="download.opened.value" :show-header="download.opened.value" @update:open="!$event && navigation.close()">
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
        <Button v-if="navigation.canGoBack.value && !preview.opened.value" type="button" variant="secondary" @click="navigation.back()">{{ t('focus.cancel') }}</Button>
        <Button v-else type="button" variant="secondary" @click="navigation.close()">{{ t('focus.cancel') }}</Button>
        <Button v-if="download.info.value && !preview.opened.value" type="button" variant="secondary" :disabled="download.busy.value || !previewKind || download.info.value.size > previewLimit" @click="showPreview">{{ t('focus.filePreviewAction') }}</Button>
        <Button v-if="download.info.value" type="submit" variant="primary" :disabled="download.busy.value || !download.filename.value">
          {{ t(download.nativePicker.value ? 'focus.fileSaveAs' : 'focus.fileDownloadAction') }}
        </Button>
      </div>
    </form>
    <FocusFilePreview v-if="preview.opened.value" v-show="!download.opened.value" :preview="preview"
      :can-go-back="navigation.canGoBack.value" :restore-view="navigation.restoreView.value"
      :can-maximize="!narrow" :maximized="maximized" @toggle-maximized="maximized = !maximized"
      @close="navigation.close()" @back="navigation.back()" @download="navigation.showDownload()"
      @open-file="navigation.openLinkedFile" @restored="navigation.restored()" />
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
