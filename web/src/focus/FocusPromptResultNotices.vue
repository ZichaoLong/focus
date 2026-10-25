<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import Banner from '../components/ui/Banner.vue';
import Button from '../components/ui/Button.vue';
import FocusPromptDiagnostic from './FocusPromptDiagnostic.vue';
import type { PromptResultNotice } from './mutations/prompt-results';

const props = defineProps<{ notices: readonly PromptResultNotice[] }>();
const emit = defineEmits<{ dismiss: [mutationId: string] }>();
const { t } = useI18n();

function dismiss(): void {
  for (const notice of props.notices) emit('dismiss', notice.mutationId);
}
</script>

<template>
  <Banner v-if="notices.length" variant="warning">
    <div class="prompt-result-notices">
      <details>
        <summary>{{ t('focus.promptResultNoticeSummary', { count: notices.length }) }}</summary>
        <p>{{ t('focus.promptResultNoticeHelp') }}</p>
        <div v-for="notice in notices" :key="notice.mutationId" class="prompt-result-notice">
          <p>{{ notice.message }}</p>
          <FocusPromptDiagnostic :key="notice.diagnostic" :diagnostic="notice.diagnostic" />
        </div>
      </details>
      <Button size="sm" variant="ghost" @click="dismiss">
        {{ t('focus.promptResultNoticeDismiss') }}
      </Button>
    </div>
  </Banner>
</template>

<style scoped>
.prompt-result-notices {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  width: 100%;
  min-width: 0;
}
.prompt-result-notices details {
  flex: 1;
  min-width: 0;
  overflow-wrap: anywhere;
}
.prompt-result-notices summary {
  cursor: pointer;
  padding-block: var(--space-1);
}
.prompt-result-notices p {
  margin: var(--space-2) 0;
}
.prompt-result-notice + .prompt-result-notice {
  margin-top: var(--space-3);
}
</style>
