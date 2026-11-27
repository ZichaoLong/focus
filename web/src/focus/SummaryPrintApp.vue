<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { cancelMobileFile, hasMobileFeature, printMobileSummary, saveMobileFile } from '../lib/mobileHost';
import { chooseFileDestination, saveFileResponse, saveExportBlob } from './browserFileSave';
import { suggestExportFilename } from './exportFilename';
import { normalizeSummaryTitle, summaryDocumentBody } from './summaryDocumentTitle';
import { receiveSummaryPrint, type PrintPayload } from './summaryPrintWindow';
import { renderSummaryPrintMarkdown } from './summaryPrintMarkdown';
import { prepareSummaryPrint } from './summaryPrintPreparation';
import { fetchSummaryPdf, pdfJobId, PdfRequestError, type PdfPreview, type PdfStatus } from './summaryServerPdf';
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
const offer = ref('');
const ticket = ref<PdfPreview>();
const canDownloadPdf = computed(() => Boolean(ticket.value) && (!props.preview || hasMobileFeature('save')));
const saving = ref(false);
const pdfMessage = ref('');
const progress = ref<PdfStatus>();
const bytes = ref(0);
const elapsed = ref(0);
let pdfJob: AbortController | undefined;
let lastRequest: { title: string; lang: string; id: string } | undefined;
let panelTimer: ReturnType<typeof setTimeout> | undefined;
let observedPanel = false;
let waitingForPanel = false;
let jobName = 'Focus';
let dispose = () => {};

async function render(markdown: string, suggestedFilename: string, title: string, preview?: PdfPreview): Promise<void> {
  ticket.value = preview;
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
  if (saving.value || !ticket.value || status.value !== 'ready') return;
  const job = new AbortController();
  pdfJob = job;
  saving.value = true;
  pdfMessage.value = '';
  bytes.value = elapsed.value = 0;
  progress.value = undefined;
  const filename = jobName + '.pdf';
  const title = printedTitle.value, lang = locale.value;
  let mobileFileOpen = false;
  let timer: ReturnType<typeof setInterval> | undefined;
  function discardFile(): void {
    if (mobileFileOpen) { mobileFileOpen = false; cancelMobileFile(); }
  }
  job.signal.addEventListener('abort', discardFile, { once: true });
  try {
    const destination = await chooseFileDestination(filename, [{ description: 'PDF', accept: { 'application/pdf': ['.pdf'] } }]);
    if (!destination) return;
    mobileFileOpen = destination.kind === 'mobile';
    job.signal.throwIfAborted();
    const started = Date.now();
    timer = setInterval(() => { elapsed.value = Math.floor((Date.now() - started) * 0.001); }, 1000);
    if (!lastRequest || lastRequest.title !== title || lastRequest.lang !== lang) lastRequest = { title, lang, id: pdfJobId() };
    pdfMessage.value = 'pdfQueued';
    const report = (state: PdfStatus) => {
      progress.value = state;
      pdfMessage.value = ({ queued: 'pdfQueued', preparing: 'pdfPreparing', formulas: 'pdfFormulas', browser: 'pdfBrowserLayout',
        layout: 'pdfBasicLayout', ready: 'pdfDownloading', reconnecting: 'pdfReconnecting' } as Record<string, string>)[state.phase] || 'pdfPreparing';
    };
    const { response, status: result } = await fetchSummaryPdf(ticket.value, lastRequest.id, title, lang, job.signal, report);
    progress.value = result;
    pdfMessage.value = 'pdfDownloading';
    const received = (n: number) => { bytes.value = n; };
    if (destination.kind === 'mobile') await saveMobileFile(response, job.signal, received);
    else if (destination.kind === 'file') await saveFileResponse(destination.handle, response, job.signal, received);
    else await saveExportBlob(destination, await response.blob(), filename, job.signal);
    mobileFileOpen = false;
    pdfMessage.value = destination.kind === 'download' ? 'pdfDownloadStarted' : 'pdfSaved';
  } catch (error) {
    if (job.signal.aborted) return;
    if (error instanceof PdfRequestError) {
      pdfMessage.value = 'pdfError_' + error.reason;
      if (['render', 'expired', 'timeout'].includes(error.reason)) lastRequest = undefined;
    } else pdfMessage.value = 'pdfSaveFailed';
  } finally {
    clearInterval(timer);
    job.signal.removeEventListener('abort', discardFile);
    discardFile();
    pdfJob = undefined;
    saving.value = false;
  }
}

function panelObserved(): void { observedPanel = true; showDownloadOption(); }
function showDownloadOption(): void {
  if (waitingForPanel && !document.hidden) offer.value = observedPanel ? 'printAlternative' : 'printNoPanel';
}
function visibilityChanged(): void { if (document.hidden) panelObserved(); else showDownloadOption(); }
function print(): void {
  if (status.value !== 'ready') return;
  clearTimeout(panelTimer);
  observedPanel = waitingForPanel = false;
  offer.value = '';
  try {
    const reply = props.preview ? printMobileSummary(jobName) : (window.print(), 'ok');
    if (reply !== 'ok') { offer.value = 'printIssue_' + reply; return; }
  } catch { offer.value = 'printIssue_error'; return; }
  panelTimer = setTimeout(() => {
    waitingForPanel = true;
    showDownloadOption();
  }, 3000);
}

onMounted(() => {
  window.addEventListener('afterprint', panelObserved);
  window.addEventListener('blur', panelObserved);
  window.addEventListener('focus-host-pause', panelObserved);
  window.addEventListener('focus', showDownloadOption);
  window.addEventListener('focus-host-resume', showDownloadOption);
  document.addEventListener('visibilitychange', visibilityChanged);
  document.documentElement.classList.add('summary-print-page');
  if (props.preview) {
    document.documentElement.classList.add('summary-mobile-print');
    dispose = watch(() => props.preview?.content, payload => {
      if (payload && 'markdown' in payload) void render(payload.markdown, payload.suggestedFilename, payload.documentTitle, payload.pdfPreview);
      else if (payload) status.value = 'error';
    }, { immediate: true });
    return;
  }
  document.title = 'Focus — Q&A';
  dispose = receiveSummaryPrint((markdown, filename, title, preview) => { void render(markdown, filename, title, preview); }, () => { status.value = 'error'; });
});
onUnmounted(() => {
  pdfJob?.abort();
  clearTimeout(panelTimer);
  window.removeEventListener('afterprint', panelObserved);
  window.removeEventListener('blur', panelObserved);
  window.removeEventListener('focus-host-pause', panelObserved);
  window.removeEventListener('focus', showDownloadOption);
  window.removeEventListener('focus-host-resume', showDownloadOption);
  document.removeEventListener('visibilitychange', visibilityChanged);
  dispose();
  document.documentElement.classList.remove('summary-print-page', 'summary-mobile-print');
});
</script>

<template>
  <main class="summary-print" :data-status="status">
    <header class="summary-print-toolbar">
      <div class="summary-print-actions">
        <h1>{{ t('focus.printPreviewTitle') }}</h1>
        <button type="button" class="system-print" :disabled="status !== 'ready' || saving" @click="print">{{ t('focus.printButton') }}</button>
        <button v-if="preview" type="button" @click="$emit('close')">{{ t('focus.closePrintPreview') }}</button>
      </div>
      <div v-if="offer && (offer !== 'printAlternative' || canDownloadPdf)" class="summary-print-offer" role="status">
        {{ t('focus.' + offer) }}
        <button v-if="canDownloadPdf" class="save-pdf" :disabled="saving" @click="savePdf">
          {{ t(offer === 'printNoPanel' ? 'focus.tryDownloadPdf' : 'focus.savePdf') }}
        </button>
      </div>
      <p v-if="pdfMessage" class="summary-pdf-status" role="status">
        {{ t('focus.' + pdfMessage, { done: progress?.done ?? 0, total: progress?.total ?? 0, kb: Math.round(bytes / 1024) }) }}
        <span v-if="saving">{{ t('focus.pdfElapsed', { seconds: elapsed }) }}</span>
        <span v-if="progress?.engine">{{ t('focus.pdfEngine_' + progress.engine) }}</span>
      </p>
      <ul v-if="progress?.warnings?.length" class="summary-pdf-warnings">
        <li v-for="(w, i) in progress.warnings" :key="i">
          <span v-if="w.round">{{ t('focus.pdfRound', { round: w.round }) }} </span>
          {{ t('focus.pdfWarning_' + w.kind, { code: w.code ?? '', count: w.count ?? 1 }) }}
        </li>
      </ul>
      <div v-if="status === 'ready'" class="summary-title-editor">
        <label for="summary-document-title">{{ t('focus.exportDocumentTitle') }}</label>
        <input id="summary-document-title" v-model="documentTitle" :disabled="saving" type="text" :placeholder="printedTitle" aria-describedby="summary-title-help" />
        <span id="summary-title-help">{{ t('focus.printDocumentTitleHelp') }}</span>
      </div>
      <p>{{ t('focus.printScope') }}</p>
      <p>{{ t('focus.printHelp') }}</p>
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
