<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { PDFDocumentLoadingTask, PDFDocumentProxy, PDFPageProxy, RenderTask, TextLayer } from 'pdfjs-dist';
import Button from '../components/ui/Button.vue';
import IconButton from '../components/ui/IconButton.vue';
import Icon from '../components/ui/Icon.vue';

const props = defineProps<{ bytes: Uint8Array<ArrayBuffer> }>();
const { t } = useI18n();
const viewport = ref<HTMLElement | null>(null);
const sheet = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);
const textContainer = ref<HTMLElement | null>(null);
const pageNumber = ref(1), total = ref(0), scale = ref(1), zoom = ref(1);
const fitting = ref(true), busy = ref(true), ready = ref(false);
const error = ref(''), textUnavailable = ref(false), password = ref(''), passwordReason = ref('');
const percentage = computed(() => Math.round(scale.value / (4 / 3) * 100));
let runtime: typeof import('./filePreviewPdf') | null = null;
let loadingTask: PDFDocumentLoadingTask | null = null;
let document: PDFDocumentProxy | null = null;
let currentPage: PDFPageProxy | null = null;
let renderTask: RenderTask | null = null;
let textLayer: TextLayer | null = null;
let unlock: ((value: string) => void) | null = null;
let disposed = false, generation = 0, resizeFrame = 0;
let observer: ResizeObserver | null = null;

async function renderPage(): Promise<void> {
  const host = viewport.value, target = canvas.value, text = textContainer.value;
  if (!document || !runtime || !host || !target || !text || !host.clientWidth || !host.clientHeight) return;
  const request = ++generation;
  const previous = renderTask;
  previous?.cancel(); textLayer?.cancel(); textLayer = null;
  ready.value = false; busy.value = true; error.value = ''; textUnavailable.value = false;
  try {
    // A cancelled render still owns its canvas until its promise settles.
    await previous?.promise.catch(() => {});
    if (disposed || request !== generation) return;
    currentPage?.cleanup();
    const page = await document.getPage(pageNumber.value);
    if (disposed || request !== generation) return;
    currentPage = page;
    const original = page.getViewport({ scale: 1 });
    const ratio = Math.min(2, window.devicePixelRatio || 1);
    const desired = fitting.value
      ? Math.min(Math.max(1, host.clientWidth - 24) / original.width, Math.max(1, host.clientHeight - 24) / original.height)
      : zoom.value * (4 / 3);
    const actual = Math.min(desired, 8192 / (original.width * ratio), 8192 / (original.height * ratio),
      Math.sqrt(runtime.PDF_CANVAS_PIXELS / (original.width * original.height)) / ratio);
    if (!Number.isFinite(actual) || actual <= 0) throw new Error('Invalid PDF page dimensions');
    const view = page.getViewport({ scale: actual });
    scale.value = actual;
    target.width = Math.max(1, Math.floor(view.width * ratio));
    target.height = Math.max(1, Math.floor(view.height * ratio));
    sheet.value!.style.width = `${view.width}px`;
    sheet.value!.style.height = `${view.height}px`;
    sheet.value!.style.setProperty('--total-scale-factor', String(view.scale * view.userUnit));
    text.replaceChildren();
    const task = page.render({ canvas: target, viewport: view, transform: [ratio, 0, 0, ratio, 0, 0] });
    renderTask = task;
    await task.promise;
    if (disposed || request !== generation) return;
    ready.value = true;
    busy.value = false;
    // Text extraction is optional; a scanned page remains a normal image.
    try {
      const source = await page.getTextContent();
      if (disposed || request !== generation) return;
      if (source.items.length > 10_000) throw new Error('PDF text layer too large');
      const layer = new runtime.TextLayer({ textContentSource: source, container: text, viewport: view });
      textLayer = layer;
      await layer.render();
    } catch {
      if (!disposed && request === generation) { textUnavailable.value = true; text.replaceChildren(); }
    }
  } catch {
    if (!disposed && request === generation) error.value = 'focus.filePreviewPdfFailed';
  } finally {
    if (!disposed && request === generation) { busy.value = false; renderTask = null; }
  }
}

function goToPage(event: Event): void {
  const input = event.target as HTMLInputElement;
  const next = Number(input.value);
  if (Number.isInteger(next) && next >= 1 && next <= total.value) pageNumber.value = next;
  input.value = String(pageNumber.value);
}
function changeZoom(factor: number): void {
  zoom.value = Math.max(0.1, Math.min(5, scale.value / (4 / 3) * factor));
  fitting.value = false;
}
function submitPassword(): void {
  const callback = unlock;
  if (!callback) return;
  unlock = null; passwordReason.value = ''; busy.value = true;
  callback(password.value); password.value = '';
}
watch([pageNumber, zoom, fitting], () => { void renderPage(); });

onMounted(async () => {
  observer = new ResizeObserver(() => {
    if (!fitting.value || resizeFrame || !viewport.value?.clientWidth) return;
    resizeFrame = requestAnimationFrame(() => { resizeFrame = 0; void renderPage(); });
  });
  if (viewport.value) observer.observe(viewport.value);
  try {
    runtime = await import('./filePreviewPdf');
    if (disposed) return;
    loadingTask = runtime.loadPreviewPdf(props.bytes);
    loadingTask.onPassword = (update: (value: string) => void, reason: number) => {
      if (disposed) return;
      unlock = update; busy.value = false;
      passwordReason.value = reason === runtime!.PasswordResponses.INCORRECT_PASSWORD
        ? 'focus.filePreviewPdfPasswordWrong' : 'focus.filePreviewPdfPasswordNeeded';
    };
    document = await loadingTask.promise;
    if (disposed) return;
    total.value = document.numPages;
    await renderPage();
  } catch {
    if (!disposed) { error.value = 'focus.filePreviewPdfFailed'; busy.value = false; }
  }
});
onBeforeUnmount(() => {
  disposed = true; generation++; unlock = null; password.value = '';
  observer?.disconnect(); cancelAnimationFrame(resizeFrame);
  renderTask?.cancel(); textLayer?.cancel();
  // Destroy also rejects a pending password/load and terminates the worker.
  void loadingTask?.destroy().catch(() => {});
  if (canvas.value) canvas.value.width = canvas.value.height = 0;
});
</script>

<template>
  <div class="pdf-preview">
    <div v-if="total" class="pdf-toolbar">
      <IconButton size="lg" :label="t('focus.filePreviewPrevious')" :disabled="pageNumber <= 1" @click="pageNumber--"><Icon name="chevron-right" class="pdf-previous" /></IconButton>
      <input class="pdf-page-number" type="number" min="1" :max="total" :value="pageNumber" :aria-label="t('focus.filePreviewPdfPage')" @change="goToPage" />
      <span>/ {{ total }}</span>
      <IconButton size="lg" :label="t('focus.filePreviewNext')" :disabled="pageNumber >= total" @click="pageNumber++"><Icon name="chevron-right" /></IconButton>
      <Button variant="ghost" @click="fitting = true">{{ t('filePreview.diagramFit') }}</Button>
      <IconButton size="lg" :label="t('filePreview.imageZoomOut')" :disabled="percentage <= 10" @click="changeZoom(1 / 1.25)"><Icon name="minus" /></IconButton>
      <span>{{ percentage }}%</span>
      <IconButton size="lg" :label="t('filePreview.imageZoomIn')" :disabled="percentage >= 500" @click="changeZoom(1.25)"><Icon name="plus" /></IconButton>
    </div>
    <form v-if="passwordReason" class="pdf-password" @submit.prevent="submitPassword">
      <label for="pdf-preview-password">{{ t(passwordReason) }}</label>
      <input id="pdf-preview-password" v-model="password" type="password" autocomplete="off" :aria-label="t('focus.filePreviewPdfPassword')" />
      <Button type="submit" :disabled="!password">{{ t('focus.filePreviewPdfUnlock') }}</Button>
    </form>
    <p v-if="busy" class="pdf-status" role="status">{{ t('focus.filePreviewPdfLoading') }}</p>
    <p v-if="error" class="pdf-status" role="alert">{{ t(error) }}</p>
    <p v-if="textUnavailable" class="pdf-status" role="status">{{ t('focus.filePreviewPdfTextUnavailable') }}</p>
    <div ref="viewport" class="pdf-viewport" tabindex="0" :aria-label="t('focus.filePreviewPdfPage')">
      <div v-show="ready" ref="sheet" class="pdf-sheet">
        <canvas ref="canvas" :aria-label="t('focus.filePreviewPdfPageNumber', { page: pageNumber, total })" />
        <div ref="textContainer" class="pdf-text-layer" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-preview { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; }
.pdf-toolbar { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: var(--space-1); padding: var(--space-1); font-size: var(--text-sm); }
.pdf-page-number { width: 5ch; height: 44px; box-sizing: border-box; border: 1px solid var(--color-line); border-radius: var(--radius-sm); color: var(--color-text); background: var(--color-surface); font: inherit; text-align: center; }
.pdf-previous { transform: rotate(180deg); }
.pdf-viewport { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding: 12px; background: var(--color-surface-raised); }
.pdf-sheet { position: relative; margin: 0 auto; background: white; --scale-round-x: 1px; --scale-round-y: 1px; }
.pdf-sheet canvas { width: 100%; height: 100%; display: block; }
.pdf-status { position: absolute; z-index: 1; bottom: 0; left: 0; right: 0; padding: var(--space-2) var(--space-3); margin: 0; font-size: var(--text-sm); background: var(--color-surface); }
.pdf-password { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: var(--space-2); padding: var(--space-3); }
.pdf-password input { box-sizing: border-box; height: 44px; max-width: 100%; border: 1px solid var(--color-line); border-radius: var(--radius-sm); padding: var(--space-2); color: var(--color-text); background: var(--color-surface); font: inherit; }
/* PDF.js 6.5 TextLayer's CSS variables describe positioned text runs. */
.pdf-text-layer { position: absolute; inset: 0; overflow: hidden; transform-origin: 0 0; line-height: 1; text-align: initial; text-size-adjust: none; forced-color-adjust: none; }
.pdf-text-layer :deep(span), .pdf-text-layer :deep(br) { position: absolute; color: transparent; white-space: pre; cursor: text; user-select: text; transform-origin: 0 0; }
.pdf-text-layer :deep(span) { font-size: calc(var(--total-scale-factor) * var(--min-font-size) * var(--font-height)); transform: rotate(var(--rotate, 0deg)) scaleX(var(--scale-x, 1)) scale(calc(1 / var(--min-font-size))); }
.pdf-text-layer :deep(::selection) { background: rgb(0 100 255 / 25%); }
.pdf-text-layer[data-main-rotation="90"] { transform: rotate(90deg) translateY(-100%); }
.pdf-text-layer[data-main-rotation="180"] { transform: rotate(180deg) translate(-100%, -100%); }
.pdf-text-layer[data-main-rotation="270"] { transform: rotate(270deg) translateX(-100%); }
</style>
