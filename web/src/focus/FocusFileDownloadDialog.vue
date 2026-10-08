<script setup lang="ts">
import { onBeforeUnmount } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';
import Dialog from '../components/ui/Dialog.vue';
import Input from '../components/ui/Input.vue';
import { createFileDownload, formatFileSize, type FileDownloadApi } from './fileDownload';

const props = defineProps<{ api: FileDownloadApi }>();
const { t } = useI18n();
const download = createFileDownload(props.api);
onBeforeUnmount(download.close);
defineExpose({ open: download.open });
</script>

<template>
  <Dialog :open="download.opened.value" :title="t('focus.fileDownloadTitle')" @update:open="!$event && download.close()">
    <form class="file-download-form" @submit.prevent="download.save">
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
      </template>
      <p v-if="download.busy.value" role="status">{{ t('focus.fileSaving', { size: formatFileSize(download.received.value) }) }}</p>
      <p v-if="download.errorKey.value" role="alert">{{ t(download.errorKey.value) }}</p>
      <p v-if="download.statusKey.value" role="status">{{ t(download.statusKey.value) }}</p>
      <div class="file-download-actions">
        <Button type="button" variant="secondary" @click="download.close()">{{ t('focus.cancel') }}</Button>
        <Button v-if="download.info.value" type="submit" variant="primary" :disabled="download.busy.value || !download.filename.value">
          {{ t(download.nativePicker.value ? 'focus.fileSaveAs' : 'focus.fileDownloadAction') }}
        </Button>
      </div>
    </form>
  </Dialog>
</template>

<style scoped>
.file-download-form, .file-download-label { display: flex; flex-direction: column; gap: var(--space-2); }
.file-download-form { gap: var(--space-4); }
.file-download-form p { margin: 0; overflow-wrap: anywhere; }
.file-download-path { font-family: var(--font-mono); }
.file-download-help { color: var(--color-text-muted); font-size: var(--text-sm); }
.file-download-actions { display: flex; justify-content: flex-end; gap: var(--space-2); }
</style>
