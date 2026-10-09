<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { FilePreviewRequest } from '../types';
import LazyMarkdown from '../components/chat/LazyMarkdown.vue';
import Button from '../components/ui/Button.vue';
import ImageViewport from '../components/ui/ImageViewport.vue';
import { copyTextToClipboard } from '../lib/clipboard';
import { canChooseFileDestination } from './browserFileSave';
import { formatFileSize } from './fileDownload';
import { filePreviewKind, filePreviewLimit, type FilePreviewState } from './filePreview';

const props = defineProps<{ preview: FilePreviewState }>();
const emit = defineEmits<{ download: []; openFile: [target: FilePreviewRequest] }>();
const { t } = useI18n();
const content = computed(() => props.preview.content.value);
const sourceMode = ref(false);
const wrapped = ref(false);
const source = ref<HTMLTextAreaElement | null>(null);
const copyState = ref('filePreview.copy');
const locatedLine = ref(0);
const limit = computed(() => filePreviewLimit(filePreviewKind(props.preview.file.value?.name ?? '') ?? 'text'));
const showingSource = computed(() => content.value?.kind !== 'image'
  && (!content.value?.renderMarkdown || sourceMode.value));

async function locateLine(): Promise<void> {
  const requested = props.preview.line.value;
  if (!requested) return;
  sourceMode.value = true;
  wrapped.value = false;
  await nextTick();
  const field = source.value;
  if (!field) return;
  let start = 0;
  let line = 1;
  while (line < requested) {
    const end = field.value.indexOf('\n', start);
    if (end < 0) break;
    start = end + 1;
    line++;
  }
  const end = field.value.indexOf('\n', start);
  field.focus({ preventScroll: true });
  field.setSelectionRange(start, end < 0 ? field.value.length : end);
  field.scrollTop = Math.max(0, (line - 2) * parseFloat(getComputedStyle(field).lineHeight));
  locatedLine.value = line;
}

watch(content, async () => {
  sourceMode.value = !!props.preview.line.value;
  copyState.value = 'filePreview.copy';
  locatedLine.value = 0;
  if (content.value && content.value.kind !== 'image') await locateLine();
}, { immediate: true });

async function copy(): Promise<void> {
  copyState.value = await copyTextToClipboard(content.value?.text ?? '') ? 'filePreview.copied' : 'filePreview.failed';
}
</script>

<template>
  <section class="file-preview">
    <div class="file-preview-toolbar">
      <Button variant="secondary" @click="emit('download')">{{ t(canChooseFileDestination() ? 'focus.fileSaveAs' : 'focus.fileDownloadAction') }}</Button>
      <Button variant="ghost" :disabled="preview.loading.value" @click="preview.refresh()">{{ t('focus.filePreviewRefresh') }}</Button>
      <template v-if="content && content.kind !== 'image'">
        <Button v-if="content.renderMarkdown" variant="ghost" :aria-pressed="sourceMode" @click="sourceMode = !sourceMode">{{ t(sourceMode ? 'focus.filePreviewRendered' : 'focus.filePreviewSource') }}</Button>
        <Button v-if="showingSource" variant="ghost" :aria-pressed="wrapped" @click="wrapped = !wrapped">{{ t('focus.filePreviewWrap') }}</Button>
        <Button variant="ghost" @click="copy">{{ t(copyState) }}</Button>
      </template>
    </div>
    <div class="file-preview-description">
      <p class="file-preview-path">{{ preview.file.value?.path }}</p>
      <p>{{ t('focus.filePreviewCurrent') }}</p>
      <p v-if="locatedLine && showingSource" role="status">{{ t('focus.filePreviewLine', { line: locatedLine }) }}</p>
      <p v-if="content?.kind === 'markdown' && !content.renderMarkdown">{{ t('focus.filePreviewLargeMarkdown') }}</p>
    </div>
    <p v-if="preview.loading.value" class="file-preview-message" role="status">{{ t('focus.filePreviewLoading', { size: formatFileSize(preview.received.value) }) }}</p>
    <p v-else-if="preview.errorKey.value" class="file-preview-message" role="alert">{{ t(preview.errorKey.value, { limit: formatFileSize(limit) }) }}</p>
    <template v-else-if="content">
      <ImageViewport v-if="content.kind === 'image'" :key="content.url" class="file-preview-image"
        :source="content.url" :width="content.width" :height="content.height" :alt="preview.file.value?.name ?? ''" :natural-size="true"
        :help="t('filePreview.imageControls')" :failed-text="t('focus.filePreviewImageInvalid')" />
      <textarea v-else-if="showingSource" ref="source" class="file-preview-source" readonly :spellcheck="false"
        :aria-label="t('focus.filePreviewSource')" :wrap="wrapped ? 'soft' : 'off'" :value="content.text" />
      <div v-else class="file-preview-markdown"><LazyMarkdown :text="content.text" :defer-images="true" :open-file="target => emit('openFile', target)" /></div>
    </template>
  </section>
</template>

<style scoped>
.file-preview { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.file-preview-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); padding: 0 var(--space-3) var(--space-2); }
.file-preview-description { padding: 0 var(--space-4) var(--space-2); color: var(--color-text-muted); font-size: var(--text-sm); }
.file-preview-description p { margin: 0; }
.file-preview-path { overflow-wrap: anywhere; max-height: 4em; overflow: auto; font-family: var(--font-mono); }
.file-preview-message { padding: var(--space-4); }
.file-preview-source { flex: 1; min-height: 0; width: 100%; resize: none; box-sizing: border-box; border: 0; border-top: 1px solid var(--color-line);
  padding: var(--space-4); border-radius: 0; color: var(--color-text); background: var(--color-surface); font: 400 14px/22px var(--font-mono); overscroll-behavior: contain; }
.file-preview-markdown { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding: var(--space-4); }
.file-preview-image { flex: 1; min-height: 0; }
</style>
