<script setup lang="ts">
import { computed, inject, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';
import { copyTextToClipboard } from '../lib/clipboard';
import { downloadBlob } from '../lib/download';
import { focusViewportDiagnosticKey } from './focusViewport';

const source = inject(focusViewportDiagnosticKey, null);
const diagnostics = computed(() => source?.value ?? null);
const recording = computed(() => diagnostics.value?.enabled.value ?? false);
const report = computed(() => diagnostics.value?.report.value ?? '');
const expanded = ref(false);
const copyState = ref<'idle' | 'copied' | 'failed'>('idle');
const downloadFailed = ref(false);
const { t } = useI18n();

function toggleRecording(): void {
  copyState.value = 'idle';
  downloadFailed.value = false;
  if (recording.value) diagnostics.value?.stop();
  else diagnostics.value?.start();
}

async function copyDiagnostic(): Promise<void> {
  if (!report.value) return;
  copyState.value = await copyTextToClipboard(report.value) ? 'copied' : 'failed';
}

function downloadDiagnostic(): void {
  const snapshot = report.value;
  if (!snapshot) return;
  downloadFailed.value = false;
  try {
    const timestamp = new Date().toISOString().replace(/[:.]/gu, '-');
    downloadBlob(
      new Blob([snapshot], { type: 'application/json;charset=utf-8' }),
      `focus-layout-diagnostic-${timestamp}.json`,
    );
  } catch {
    downloadFailed.value = true;
  }
}
</script>

<template>
  <details
    v-if="diagnostics !== null"
    class="viewport-diagnostic"
    @toggle="expanded = ($event.target as HTMLDetailsElement).open"
  >
    <summary>{{ t('focus.viewportDiagnosticTitle') }}</summary>
    <div v-if="expanded" class="viewport-diagnostic-content">
      <p>{{ t('focus.viewportDiagnosticHint') }}</p>
      <p>{{ t('focus.viewportDiagnosticRecordingHint') }}</p>
      <p>{{ t('focus.viewportDiagnosticRetentionHint') }}</p>
      <p role="status">
        {{ t(recording ? 'focus.viewportDiagnosticRecording' : report ? 'focus.viewportDiagnosticStopped' : 'focus.viewportDiagnosticOff') }}
      </p>
      <div class="viewport-diagnostic-actions">
        <Button size="sm" variant="secondary" @click="toggleRecording">
          {{ t(recording ? 'focus.viewportDiagnosticStop' : report ? 'focus.viewportDiagnosticRestart' : 'focus.viewportDiagnosticStart') }}
        </Button>
        <Button size="sm" variant="secondary" :disabled="!report" @click="copyDiagnostic">
          {{ t(copyState === 'copied' ? 'focus.promptDiagnosticCopied' : 'focus.promptDiagnosticCopy') }}
        </Button>
        <Button size="sm" variant="secondary" :disabled="!report" @click="downloadDiagnostic">
          {{ t('focus.viewportDiagnosticDownload') }}
        </Button>
      </div>
      <span v-if="copyState === 'failed'" role="status">{{ t('focus.promptDiagnosticCopyFailed') }}</span>
      <span v-if="downloadFailed" role="status">{{ t('focus.viewportDiagnosticDownloadFailed') }}</span>
      <pre v-if="report">{{ report }}</pre>
    </div>
  </details>
</template>

<style scoped>
.viewport-diagnostic { margin-top: var(--space-4); min-width: 0; }
.viewport-diagnostic summary { cursor: pointer; }
.viewport-diagnostic-content {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.viewport-diagnostic p { color: var(--color-text-muted); }
.viewport-diagnostic-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.viewport-diagnostic pre {
  width: 100%;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  user-select: text;
  font-size: var(--text-xs);
}
</style>
