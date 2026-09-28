<script setup lang="ts">
import { ref } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';
import { copyTextToClipboard } from '../lib/clipboard';

const props = defineProps<{ diagnostic: string }>();
const { t } = useI18n();
const copyState = ref<'idle' | 'copied' | 'failed'>('idle');

async function copyDiagnostic(): Promise<void> {
  copyState.value = await copyTextToClipboard(props.diagnostic) ? 'copied' : 'failed';
}
</script>

<template>
  <div class="prompt-diagnostic">
    <Button size="sm" variant="secondary" @click="copyDiagnostic">
      {{ t(copyState === 'copied' ? 'focus.promptDiagnosticCopied' : 'focus.promptDiagnosticCopy') }}
    </Button>
    <span v-if="copyState === 'failed'" role="status">{{ t('focus.promptDiagnosticCopyFailed') }}</span>
    <details>
      <summary>{{ t('focus.promptDiagnosticDetails') }}</summary>
      <pre>{{ diagnostic }}</pre>
    </details>
  </div>
</template>

<style scoped>
.prompt-diagnostic {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
  min-width: 0;
  max-width: 100%;
}
.prompt-diagnostic summary {
  cursor: pointer;
}
.prompt-diagnostic pre {
  margin: var(--space-2) 0 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  user-select: text;
}
</style>
