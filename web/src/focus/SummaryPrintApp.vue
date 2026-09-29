<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { normalizeSummaryTitle, summaryDocumentBody } from './summaryDocumentTitle';
import { receiveSummaryPrint } from './summaryPrintWindow';
import { renderSummaryPrintMarkdown } from './summaryPrintMarkdown';
import { prepareSummaryPrint } from './summaryPrintPreparation';
import 'katex/dist/katex.min.css';
import './summaryPrint.css';

const { t } = useI18n();
const content = ref<HTMLElement>();
const html = ref('');
const rawSource = ref('');
const documentTitle = ref('');
const printedTitle = computed(() => normalizeSummaryTitle(documentTitle.value));
const status = ref<'loading' | 'ready' | 'error'>('loading');
const fallback = ref(false);
let dispose = () => {};

async function render(markdown: string, suggestedFilename: string, title: string): Promise<void> {
  document.title = suggestedFilename.replace(/\.pdf$/i, '') || 'Focus — Q&A';
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

function print(): void {
  if (status.value === 'ready') window.print();
}

onMounted(() => {
  document.title = 'Focus — Q&A';
  document.documentElement.classList.add('summary-print-page');
  dispose = receiveSummaryPrint((markdown, filename, title) => { void render(markdown, filename, title); }, () => { status.value = 'error'; });
});
onUnmounted(() => { dispose(); document.documentElement.classList.remove('summary-print-page'); });
</script>

<template>
  <main class="summary-print" :data-status="status">
    <header class="summary-print-toolbar">
      <div class="summary-print-actions">
        <h1>{{ t('focus.printSummary') }}</h1>
        <button type="button" :disabled="status !== 'ready'" @click="print">{{ t('focus.printButton') }}</button>
      </div>
      <div v-if="status === 'ready'" class="summary-title-editor">
        <label for="summary-document-title">{{ t('focus.exportDocumentTitle') }}</label>
        <input id="summary-document-title" v-model="documentTitle" type="text" :placeholder="printedTitle" aria-describedby="summary-title-help" />
        <span id="summary-title-help">{{ t('focus.printDocumentTitleHelp') }}</span>
      </div>
      <p>{{ t('focus.printScope') }}</p>
      <p>{{ t('focus.printHelp') }}</p>
      <p>{{ t('focus.printMobileHelp') }}</p>
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
