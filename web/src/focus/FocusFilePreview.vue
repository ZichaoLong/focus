<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { FilePreviewRequest } from '../types';
import LazyMarkdown from '../components/chat/LazyMarkdown.vue';
import Icon from '../components/ui/Icon.vue';
import IconButton from '../components/ui/IconButton.vue';
import ImageViewport from '../components/ui/ImageViewport.vue';
import FocusHtmlPreview from './FocusHtmlPreview.vue';
import FocusTablePreview from './FocusTablePreview.vue';
import FocusJsonNode from './FocusJsonNode.vue';
import FocusPdfPreview from './FocusPdfPreview.vue';
import FocusCodePreview from './FocusCodePreview.vue';
import { copyTextToClipboard } from '../lib/clipboard';
import { canChooseFileDestination } from './browserFileSave';
import { formatFileSize } from './fileDownload';
import { filePreviewKind, filePreviewLimit, type FilePreviewState } from './filePreview';
import { findPreviewHeading } from './filePreviewAnchor';
import { restoreFilePreviewScroll, type FilePreviewViewState } from './filePreviewViewState';

const props = defineProps<{ preview: FilePreviewState; canGoBack?: boolean; restoreView?: FilePreviewViewState | null; canMaximize?: boolean; maximized?: boolean }>();
const emit = defineEmits<{ close: []; back: []; download: []; restored: []; toggleMaximized: []; openFile: [target: FilePreviewRequest, view: FilePreviewViewState] }>();
const { t } = useI18n();
const content = computed(() => props.preview.content.value);
const panel = ref<HTMLElement | null>(null);
const fullscreen = ref(false);
const sourceMode = ref(false);
const wrapped = ref(false);
const source = ref<HTMLTextAreaElement | null>(null);
const markdown = ref<HTMLElement | null>(null);
const infoOpen = ref(false);
const info = ref<HTMLElement | null>(null);
const infoButton = ref<HTMLButtonElement | null>(null);
const infoId = useId();
const notice = ref('');
type CopyTarget = 'content' | 'name' | 'path';
const copied = ref<CopyTarget | null>(null);
let noticeTimer: ReturnType<typeof setTimeout> | undefined;
const filename = computed(() => props.preview.file.value?.name ?? '');
const filenameParts = computed(() => {
  const characters = Array.from(filename.value);
  const split = characters.length - Math.min(8, Math.ceil(characters.length / 2));
  return [characters.slice(0, split).join(''), characters.slice(split).join('')];
});
const saveLabel = computed(() => t(canChooseFileDestination() ? 'focus.fileSaveAs' : 'focus.fileDownloadAction'));
const limit = computed(() => filePreviewLimit(filePreviewKind(props.preview.file.value?.name ?? '') ?? 'text'));
const hasSource = computed(() => content.value && !['image', 'pdf'].includes(content.value.kind));
const canRender = computed(() => content.value && (content.value.renderMarkdown || content.value.kind === 'html'
  || (content.value.kind === 'svg' && content.value.url) || content.value.renderedText !== undefined
  || content.value.table || content.value.json || content.value.language));
const showingSource = computed(() => hasSource.value && (!canRender.value || sourceMode.value));

function showNotice(message: string): void {
  clearTimeout(noticeTimer);
  notice.value = message;
  noticeTimer = setTimeout(() => { notice.value = ''; copied.value = null; }, 3500);
}

function openLinkedFile(target: FilePreviewRequest): void {
  const scroller = showingSource.value ? source.value : markdown.value;
  emit('openFile', target, { sourceMode: sourceMode.value, wrapped: wrapped.value,
    scrollTop: scroller?.scrollTop ?? 0, scrollLeft: scroller?.scrollLeft ?? 0 });
}

function updateFullscreen(): void { fullscreen.value = document.fullscreenElement === panel.value; }
async function toggleFullscreen(): Promise<void> {
  try {
    if (fullscreen.value) await document.exitFullscreen();
    else await panel.value?.requestFullscreen();
  } catch { showNotice(t('focus.filePreviewFullscreenFailed')); }
}
async function downloadFile(): Promise<void> {
  // The download form is outside the fullscreen panel. Leave fullscreen before
  // hiding the panel, keeping the report mounted while its form is open.
  if (document.fullscreenElement && panel.value?.contains(document.fullscreenElement)) {
    try { await document.exitFullscreen(); }
    catch { showNotice(t('focus.filePreviewFullscreenFailed')); return; }
  }
  emit('download');
}
onMounted(() => document.addEventListener('fullscreenchange', updateFullscreen));

function closeInfo(): boolean {
  if (!infoOpen.value) return false;
  infoOpen.value = false;
  infoButton.value?.focus({ preventScroll: true });
  return true;
}
defineExpose({ closeInfo });

async function toggleInfo(): Promise<void> {
  if (infoOpen.value) { closeInfo(); return; }
  infoOpen.value = true;
  await nextTick();
  info.value?.focus({ preventScroll: true });
}

function onEscape(event: KeyboardEvent): void {
  if (!infoOpen.value) return;
  event.preventDefault();
  event.stopPropagation();
  closeInfo();
}

watch(infoOpen, (open, _, onCleanup) => {
  if (!open) return;
  const outside = (event: PointerEvent) => {
    if (event.target instanceof Node && !info.value?.contains(event.target) && !infoButton.value?.contains(event.target)) closeInfo();
  };
  document.addEventListener('pointerdown', outside, true);
  onCleanup(() => document.removeEventListener('pointerdown', outside, true));
});

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
  showNotice(t('focus.filePreviewLine', { line }));
}

watch(content, async (value, _, onCleanup) => {
  const saved = props.restoreView;
  sourceMode.value = saved?.sourceMode ?? !!props.preview.line.value;
  if (saved) wrapped.value = saved.wrapped;
  copied.value = null;
  notice.value = '';
  clearTimeout(noticeTimer);
  if (!value) return;
  if (!saved) { if (hasSource.value) await locateLine(); return; }
  let current = true;
  let stop = () => {};
  onCleanup(() => { current = false; stop(); });
  await nextTick();
  if (!current) return;
  const scroller = showingSource.value ? source.value : markdown.value;
  const restored = () => { if (current) emit('restored'); };
  if (scroller) stop = restoreFilePreviewScroll(scroller, saved, restored);
  else restored();
}, { immediate: true });

watch([markdown, () => props.preview.anchor.value, content], ([root, anchor], _, onCleanup) => {
  if (!root || !anchor || props.restoreView) return;
  let observer: MutationObserver | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const locate = () => {
    const heading = findPreviewHeading(root, anchor);
    if (!heading) return false;
    heading.scrollIntoView({ block: 'start' });
    observer?.disconnect();
    clearTimeout(timer);
    return true;
  };
  if (locate()) return;
  observer = new MutationObserver(locate);
  observer.observe(root, { subtree: true, childList: true, characterData: true });
  timer = setTimeout(() => {
    observer?.disconnect();
    if (!locate()) showNotice(t('focus.filePreviewAnchorMissing', { anchor }));
  }, 5000);
  onCleanup(() => { observer?.disconnect(); clearTimeout(timer); });
});

async function copy(target: CopyTarget): Promise<void> {
  const text = target === 'content' ? content.value?.text : props.preview.file.value?.[target];
  const success = await copyTextToClipboard(text ?? '');
  copied.value = success ? target : null;
  showNotice(t(success ? 'filePreview.copied' : 'filePreview.failed'));
}

onBeforeUnmount(() => {
  clearTimeout(noticeTimer);
  document.removeEventListener('fullscreenchange', updateFullscreen);
});
</script>

<template>
  <section ref="panel" class="file-preview" @keydown.esc="onEscape">
    <div class="file-preview-toolbar">
      <IconButton v-if="canGoBack" size="lg" :label="t('focus.filePreviewBack')" :title="t('focus.filePreviewBack')" @click="emit('back')"><Icon name="arrow-right" class="file-preview-back" /></IconButton>
      <IconButton size="lg" :label="t('focus.filePreviewClose')" :title="t('focus.filePreviewClose')" @click="emit('close')"><Icon name="close" /></IconButton>
      <button ref="infoButton" type="button" class="file-preview-filename" :title="filename"
        :aria-label="t('focus.filePreviewInfoLabel', { name: filename })" :aria-expanded="infoOpen" :aria-controls="infoId" @click="toggleInfo">
        <span class="file-preview-name" aria-hidden="true"><span class="file-preview-name-start">{{ filenameParts[0] }}</span><span class="file-preview-name-end"><bdi>{{ filenameParts[1] }}</bdi></span></span>
        <Icon :name="infoOpen ? 'chevron-up' : 'chevron-down'" size="sm" />
      </button>
      <IconButton size="lg" :label="saveLabel" :title="saveLabel" @click="downloadFile"><Icon name="download" /></IconButton>
      <IconButton v-if="canMaximize && !fullscreen" size="lg" :label="t(maximized ? 'focus.filePreviewRestore' : 'focus.filePreviewMaximize')"
        :title="t(maximized ? 'focus.filePreviewRestore' : 'focus.filePreviewMaximize')" :aria-pressed="!!maximized" @click="emit('toggleMaximized')"><Icon :name="maximized ? 'window-restore' : 'window-maximize'" /></IconButton>
      <IconButton v-if="content?.kind === 'html'" size="lg" :label="t(fullscreen ? 'focus.filePreviewExitFullscreen' : 'focus.filePreviewFullscreen')"
        :title="t(fullscreen ? 'focus.filePreviewExitFullscreen' : 'focus.filePreviewFullscreen')" @click="toggleFullscreen"><Icon :name="fullscreen ? 'collapse' : 'expand'" /></IconButton>
      <IconButton v-if="canRender" size="lg" :label="t(sourceMode ? 'focus.filePreviewRendered' : 'focus.filePreviewSource')"
        :title="t(sourceMode ? 'focus.filePreviewRendered' : 'focus.filePreviewSource')" :aria-pressed="sourceMode" @click="sourceMode = !sourceMode">
        <Icon :name="sourceMode ? 'file-text' : 'code'" />
      </IconButton>
      <span v-else-if="content?.kind === 'markdown'" class="file-preview-source-badge" :title="t('focus.filePreviewLargeMarkdown')" :aria-label="t('focus.filePreviewLargeMarkdown')" role="img"><Icon name="code" /></span>
      <IconButton v-if="hasSource" size="lg" :label="t('filePreview.copy')" :title="t('filePreview.copy')" @click="copy('content')"><Icon :name="copied === 'content' ? 'check' : 'copy'" /></IconButton>
      <IconButton size="lg" :label="t('focus.filePreviewRefresh')" :title="t('focus.filePreviewRefresh')" :disabled="preview.loading.value" @click="preview.refresh()"><Icon name="refresh" /></IconButton>
    </div>
    <section v-if="infoOpen" :id="infoId" ref="info" class="file-preview-info" role="region" :aria-label="t('focus.filePreviewInfo')" tabindex="-1">
      <dl>
        <div>
          <dt>{{ t('focus.exportFilename') }}<IconButton size="lg" :label="t('focus.filePreviewCopyName')" :title="t('focus.filePreviewCopyName')" @click="copy('name')"><Icon :name="copied === 'name' ? 'check' : 'copy'" /></IconButton></dt>
          <dd>{{ filename }}</dd>
        </div>
        <div>
          <dt>{{ t('focus.filePreviewPath') }}<IconButton size="lg" :label="t('focus.filePreviewCopyPath')" :title="t('focus.filePreviewCopyPath')" @click="copy('path')"><Icon :name="copied === 'path' ? 'check' : 'copy'" /></IconButton></dt>
          <dd>{{ preview.file.value?.path }}</dd>
        </div>
      </dl>
      <label v-if="content && showingSource" class="file-preview-wrap"><input v-model="wrapped" type="checkbox" />{{ t('focus.filePreviewWrap') }}</label>
      <p v-if="content?.kind === 'markdown' && !content.renderMarkdown">{{ t('focus.filePreviewLargeMarkdown') }}</p>
      <p>{{ t('focus.filePreviewCurrent') }}</p>
      <p v-if="preview.anchor.value">{{ t('focus.filePreviewAnchor', { anchor: preview.anchor.value }) }}</p>
      <p v-if="content?.kind === 'html'">{{ t('focus.filePreviewHtmlHelp') }}</p>
      <p v-if="content?.kind === 'image' || content?.kind === 'svg'">{{ t('filePreview.imageControls') }}</p>
      <p v-if="content?.kind === 'svg'">{{ t('focus.filePreviewSvgHelp') }}</p>
      <p v-if="content?.kind === 'pdf'">{{ t('focus.filePreviewPdfHelp') }}</p>
    </section>
    <p v-if="preview.loading.value" class="file-preview-message" role="status">{{ t('focus.filePreviewLoading', { size: formatFileSize(preview.received.value) }) }}</p>
    <p v-else-if="preview.errorKey.value" class="file-preview-message" role="alert">{{ t(preview.errorKey.value, { limit: formatFileSize(limit) }) }}</p>
    <template v-else-if="content">
      <p v-if="content.renderError" class="file-preview-fallback" role="status">{{ t(content.renderError) }} {{ t('focus.filePreviewSourceFallback') }}</p>
      <ImageViewport v-if="content.kind === 'image' || (content.kind === 'svg' && !showingSource)" :key="content.url" class="file-preview-image"
        :source="content.url" :width="content.width" :height="content.height" :alt="preview.file.value?.name ?? ''" :natural-size="content.kind === 'image'"
        :help="t('filePreview.imageControls')" :hide-help="true" :failed-text="t('focus.filePreviewImageInvalid')" />
      <textarea v-else-if="showingSource" ref="source" class="file-preview-source" readonly :spellcheck="false"
        :aria-label="t('focus.filePreviewSource')" :wrap="wrapped ? 'soft' : 'off'" :value="content.text" />
      <FocusHtmlPreview v-else-if="content.kind === 'html'" :text="content.text" :anchor="preview.anchor.value" @open-file="openLinkedFile" />
      <FocusPdfPreview v-else-if="content.kind === 'pdf' && content.bytes" :bytes="content.bytes" />
      <FocusCodePreview v-else-if="content.language" :text="content.text" :language="content.language" />
      <FocusTablePreview v-else-if="content.table" :rows="content.table" />
      <div v-else-if="content.json" class="file-preview-json"><FocusJsonNode :node="content.json" /></div>
      <div v-else ref="markdown" class="file-preview-markdown">
        <div :class="{ 'file-preview-prose': content.kind === 'markdown' }"><LazyMarkdown :text="content.renderedText ?? content.text" :defer-images="true" :open-file="openLinkedFile" /></div>
      </div>
    </template>
    <div v-if="notice" class="file-preview-notice" role="status">{{ notice }}</div>
  </section>
</template>

<style scoped>
.file-preview { position: relative; display: flex; flex-direction: column; height: 100%; min-height: 0; }
.file-preview:fullscreen { background: var(--color-surface); }
.file-preview-toolbar { display: flex; flex: none; align-items: center; padding: 0 var(--space-1); border-bottom: 1px solid var(--color-line); }
.file-preview-back { transform: rotate(180deg); }
.file-preview-filename { display: flex; align-items: center; gap: var(--space-1); flex: 1; min-width: 0; height: 44px; padding: 0 var(--space-1);
  border: 0; border-radius: var(--radius-md); background: transparent; color: var(--color-text); font: inherit; cursor: pointer; }
.file-preview-filename:hover, .file-preview-filename[aria-expanded="true"] { background: color-mix(in srgb, var(--color-text) 8%, transparent); }
.file-preview-filename:focus-visible { outline: none; box-shadow: var(--p-focus-ring); }
.file-preview-filename > .kw-icon { flex: none; }
.file-preview-name { display: flex; min-width: 0; white-space: nowrap; text-align: start; }
.file-preview-name-start { overflow: hidden; text-overflow: ellipsis; }
.file-preview-name-end { flex: none; max-width: 50%; overflow: hidden; direction: rtl; text-align: left; }
.file-preview-source-badge { display: flex; align-items: center; justify-content: center; flex: none; width: 44px; color: var(--color-text-muted); }
.file-preview-info { position: absolute; z-index: var(--z-dropdown); top: 52px; left: var(--space-2); width: min(440px, calc(100% - var(--space-4)));
  max-height: calc(100% - 60px); box-sizing: border-box; overflow: auto; overscroll-behavior: contain; padding: var(--space-3);
  border: 1px solid var(--color-line); border-radius: var(--radius-lg); background: var(--color-surface-raised); box-shadow: var(--shadow-xl); font-size: var(--text-sm); }
.file-preview-info dl, .file-preview-info dd { margin: 0; }
.file-preview-info dt { display: flex; align-items: center; justify-content: space-between; font-weight: 500; }
.file-preview-info dd { white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--font-mono); user-select: text; }
.file-preview-info p { margin: var(--space-3) 0 0; color: var(--color-text-muted); }
.file-preview-wrap { display: flex; align-items: center; gap: var(--space-2); min-height: 44px; margin-top: var(--space-2); cursor: pointer; }
.file-preview-notice { position: absolute; z-index: var(--z-toast); bottom: var(--space-3); left: 50%; transform: translateX(-50%); max-width: calc(100% - var(--space-4));
  width: max-content; padding: var(--space-2) var(--space-3); border: 1px solid var(--color-line); border-radius: var(--radius-md);
  background: var(--color-surface-raised); box-shadow: var(--shadow-sm); font-size: var(--text-sm); pointer-events: none; }
.file-preview-message { padding: var(--space-4); }
.file-preview-fallback { margin: 0; padding: var(--space-2) var(--space-4); font-size: var(--text-sm); color: var(--color-text-muted); }
.file-preview-json { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding: var(--space-3); }
.file-preview-source { flex: 1; min-height: 0; width: 100%; resize: none; box-sizing: border-box; border: 0;
  padding: var(--space-4); border-radius: 0; color: var(--color-text); background: var(--color-surface); font: 400 14px/22px var(--font-mono); overscroll-behavior: contain; }
.file-preview-markdown { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding: var(--space-4); }
.file-preview-prose { max-width: var(--p-content-max); margin-inline: auto; }
.file-preview-image { flex: 1; min-height: 0; }
</style>
