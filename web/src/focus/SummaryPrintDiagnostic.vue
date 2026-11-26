<script setup lang="ts">
import { ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { copyTextToClipboard } from '../lib/clipboard';
import { chooseMobileFile, hasMobileFeature, saveMobileFile } from '../lib/mobileHost';
import type { createSummaryPrintDiagnostics } from './summaryPrintDiagnostics';

const props = defineProps<{
  diagnostic: ReturnType<typeof createSummaryPrintDiagnostics>;
  status: 'loading' | 'ready' | 'error';
}>();
const { t } = useI18n();
const { report, recording, start, stop } = props.diagnostic;
const panel = ref<HTMLElement>();
const feedback = ref('');
const exporting = ref(false);
const canSave = hasMobileFeature('save');

function toggle(): void {
  feedback.value = '';
  if (recording.value) stop();
  else start(props.status);
}

async function exportReport(kind: 'copy' | 'save'): Promise<void> {
  if (!report.value || exporting.value) return;
  // Freeze before any clipboard prompt or file picker changes foreground state.
  stop();
  const snapshot = JSON.stringify(report.value, null, 2);
  feedback.value = '';
  exporting.value = true;
  try {
    if (kind === 'copy') {
      feedback.value = await copyTextToClipboard(snapshot, panel.value)
        ? 'focus.promptDiagnosticCopied' : 'focus.promptDiagnosticCopyFailed';
    } else if (chooseMobileFile('focus-print-diagnostic.json')) {
      await saveMobileFile(new Response(snapshot));
      feedback.value = 'focus.printDiagnosticSaved';
    }
  } catch {
    feedback.value = kind === 'copy' ? 'focus.promptDiagnosticCopyFailed' : 'focus.printDiagnosticSaveFailed';
  } finally { exporting.value = false; }
}
</script>

<template>
  <details ref="panel" class="summary-print-diagnostic">
    <summary>{{ t('focus.printDiagnosticTitle') }}</summary>
    <p>{{ t('focus.printDiagnosticHint') }}</p>
    <p v-if="report" role="status">
      {{ t(recording ? 'focus.printDiagnosticRecording' : 'focus.printDiagnosticStopped', { count: report.attempts }) }}
    </p>
    <div class="diagnostic-actions">
      <button type="button" :disabled="exporting" @click="toggle">
        {{ t(recording ? 'focus.viewportDiagnosticStop' : report ? 'focus.viewportDiagnosticRestart' : 'focus.viewportDiagnosticStart') }}
      </button>
      <template v-if="report">
        <button type="button" :disabled="exporting" @click="exportReport('copy')">{{ t('focus.promptDiagnosticCopy') }}</button>
        <button v-if="canSave" type="button" :disabled="exporting" @click="exportReport('save')">{{ t('focus.printDiagnosticSave') }}</button>
      </template>
    </div>
    <p v-if="feedback" role="status">{{ t(feedback) }}</p>
    <details v-if="report">
      <summary>{{ t('focus.promptDiagnosticDetails') }}</summary>
      <pre>{{ JSON.stringify(report, null, 2) }}</pre>
    </details>
  </details>
</template>

<style scoped>
.summary-print-diagnostic { margin: 12px 0; }
summary { cursor: pointer; width: fit-content; }
.diagnostic-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
button { padding: 8px 12px; border: 1px solid currentColor; border-radius: var(--radius-md); background: transparent; color: inherit; cursor: pointer; }
button:disabled { opacity: .5; }
pre { max-height: 16rem; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; user-select: text; }
</style>
