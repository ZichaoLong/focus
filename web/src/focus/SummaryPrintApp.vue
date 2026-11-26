<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { cancelMobileFile, hasMobileFeature, type MobilePrintSource } from '../lib/mobileHost';
import { chooseFileDestination, saveExportBlob } from './browserFileSave';
import { suggestExportFilename } from './exportFilename';
import { normalizeSummaryTitle, summaryDocumentBody } from './summaryDocumentTitle';
import { receiveSummaryPrint, type PrintPayload } from './summaryPrintWindow';
import { renderSummaryPrintMarkdown } from './summaryPrintMarkdown';
import { prepareSummaryPrint } from './summaryPrintPreparation';
import { createSummaryPrintDiagnostics } from './summaryPrintDiagnostics';
import SummaryPrintDiagnostic from './SummaryPrintDiagnostic.vue';
import 'katex/dist/katex.min.css';
import './summaryPrint.css';

const { t, locale } = useI18n();
const props = defineProps<{ preview?: { content: PrintPayload | null } }>();
defineEmits<{ close: [] }>();
const content = ref<HTMLElement>();
const html = ref('');
const rawSource = ref('');
const documentTitle = ref('');
const printedTitle = computed(() => normalizeSummaryTitle(documentTitle.value));
const status = ref<'loading' | 'ready' | 'error'>('loading');
const fallback = ref(false);
const printFailed = ref(false);
const canSavePdf = !props.preview || hasMobileFeature('save');
const canPrint = !props.preview || hasMobileFeature('print');
const diagnostic = props.preview && canPrint ? createSummaryPrintDiagnostics() : null;
const saving = ref(false);
const pdfMessage = ref('');
let pdfJob: AbortController | undefined;
let jobName = 'Focus';
let dispose = () => {};

async function render(markdown: string, suggestedFilename: string, title: string): Promise<void> {
  jobName = suggestExportFilename(suggestedFilename || 'Focus — Q&A', 'print').slice(0, -4);
  if (!props.preview) document.title = jobName;
  documentTitle.value = normalizeSummaryTitle(title);
  const body = summaryDocumentBody(markdown);
  try {
    const rendered = renderSummaryPrintMarkdown(body);
    html.value = rendered.html;
    fallback.value = rendered.fallback;
  } catch {
    // A malformed export must remain printable in full, even if parsing fails.
    rawSource.value = body;
    fallback.value = true;
  }
  await nextTick();
  try {
    if (content.value) fallback.value = await prepareSummaryPrint(content.value) || fallback.value;
  } catch {
    // Unexpected preparation failure falls back to the complete original text.
    html.value = '';
    rawSource.value = body;
    fallback.value = true;
  }
  status.value = 'ready';
}

async function savePdf(): Promise<void> {
  if (saving.value || status.value !== 'ready' || !content.value) return;
  const job = new AbortController();
  pdfJob = job;
  saving.value = true;
  pdfMessage.value = '';
  const filename = `${jobName}.pdf`;
  const title = printedTitle.value;
  const article = content.value;
  let mobileFileOpen = false;
  function discardFile(): void {
    if (mobileFileOpen) {
      mobileFileOpen = false;
      cancelMobileFile();
    }
  }
  job.signal.addEventListener('abort', discardFile, { once: true });
  try {
    const destination = await chooseFileDestination(filename, [{ description: 'PDF', accept: { 'application/pdf': ['.pdf'] } }]);
    if (!destination) return;
    mobileFileOpen = destination.kind === 'mobile';
    job.signal.throwIfAborted();
    pdfMessage.value = 'focus.pdfPreparing';
    const { createSummaryPdf } = await import('./summaryPdf');
    const result = await createSummaryPdf(article, title, locale.value, job.signal);
    await saveExportBlob(destination, result.blob, filename, job.signal);
    mobileFileOpen = false;
    pdfMessage.value = result.missingGlyphs ? 'focus.pdfFontFallback' : result.fallback ? 'focus.pdfExportFallback'
      : destination.kind === 'download' ? 'focus.pdfDownloadStarted' : 'focus.pdfSaved';
  } catch {
    if (!job.signal.aborted) pdfMessage.value = 'focus.pdfSaveFailed';
  } finally {
    job.signal.removeEventListener('abort', discardFile);
    discardFile();
    pdfJob = undefined;
    saving.value = false;
  }
}

function print(source: MobilePrintSource = 'webview'): void {
  if (status.value !== 'ready') return;
  if (diagnostic) printFailed.value = !diagnostic.print(jobName, source);
  else window.print();
}

onMounted(() => {
  document.documentElement.classList.add('summary-print-page');
  if (props.preview) {
    document.documentElement.classList.add('summary-mobile-print');
    dispose = watch(() => props.preview?.content, payload => {
      if (payload && 'markdown' in payload) void render(payload.markdown, payload.suggestedFilename, payload.documentTitle);
      else if (payload) status.value = 'error';
    }, { immediate: true });
    return;
  }
  document.title = 'Focus — Q&A';
  dispose = receiveSummaryPrint((markdown, filename, title) => { void render(markdown, filename, title); }, () => { status.value = 'error'; });
});
onUnmounted(() => {
  pdfJob?.abort();
  diagnostic?.stop();
  dispose();
  document.documentElement.classList.remove('summary-print-page', 'summary-mobile-print');
});
</script>

<template>
  <main class="summary-print" :data-status="status">
    <header class="summary-print-toolbar">
      <div class="summary-print-actions">
        <h1>{{ t('focus.printSummary') }}</h1>
        <button v-if="canSavePdf" type="button" class="save-pdf" :disabled="status !== 'ready' || saving" @click="savePdf">{{ t('focus.savePdf') }}</button>
        <button v-if="canPrint" type="button" class="system-print" :disabled="status !== 'ready' || saving" @click="print()">{{ t('focus.printButton') }}</button>
        <button v-if="preview" type="button" @click="$emit('close')">{{ t('focus.closePrintPreview') }}</button>
      </div>
      <p v-if="pdfMessage" class="summary-pdf-status" role="status">{{ t(pdfMessage) }}</p>
      <p v-if="printFailed" class="summary-print-error" role="status">{{ t('focus.printSystemUnavailable') }}</p>
      <SummaryPrintDiagnostic v-if="diagnostic" :inert="saving" :diagnostic="diagnostic" :status="status" @test-page="print('native-test')" />
      <div v-if="status === 'ready'" class="summary-title-editor">
        <label for="summary-document-title">{{ t('focus.exportDocumentTitle') }}</label>
        <input id="summary-document-title" v-model="documentTitle" :disabled="saving" type="text" :placeholder="printedTitle" aria-describedby="summary-title-help" />
        <span id="summary-title-help">{{ t('focus.printDocumentTitleHelp') }}</span>
      </div>
      <p>{{ t('focus.printScope') }}</p>
      <p v-if="canPrint">{{ t('focus.printHelp') }}</p>
      <p v-if="!preview">{{ t('focus.printMobileHelp') }}</p>
      <p v-if="fallback" role="status">{{ t('focus.printFallback') }}</p>
    </header>
    <p v-if="status !== 'ready'" class="summary-print-status" role="status">
      {{ t(status === 'error' ? 'focus.printFailed' : 'focus.printPreparing') }}
    </p>
    <article ref="content" class="summary-print-content" :aria-busy="status === 'loading'">
      <h1 v-if="documentTitle || status === 'ready'">{{ printedTitle }}</h1>
      <pre v-if="rawSource" class="summary-source">{{ rawSource }}</pre>
      <div v-else v-html="html" />
    </article>
  </main>
</template>
