<script setup lang="ts">
import { ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import Dialog from '../components/ui/Dialog.vue';
import Button from '../components/ui/Button.vue';
import { copyTextToClipboard } from '../lib/clipboard';
const props = defineProps<{ text: string | null; loading: boolean; error: string }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const copied = ref(false);
watch(() => props.text, () => { copied.value = false; });
async function copy() { if (props.text !== null) copied.value = await copyTextToClipboard(props.text); }
</script>
<template>
  <Dialog :open="loading || !!error || text !== null" :title="t('conversation.fullContent')" size="xl" height="fixed" @close="emit('close')">
    <p v-if="loading" role="status">{{ t('conversation.loading') }}</p>
    <p v-else-if="error" role="alert">{{ t('conversation.transcriptError') }} {{ error }}</p>
    <textarea v-else class="full-content-text" :value="text ?? ''" readonly :aria-label="t('conversation.fullContent')" />
    <template #foot>
      <Button :disabled="text === null" @click="copy">{{ copied ? t('filePreview.copied') : t('filePreview.copy') }}</Button>
    </template>
  </Dialog>
</template>
<style scoped>
.full-content-text { width: 100%; min-height: 55vh; resize: vertical; white-space: pre-wrap; color: var(--color-text); background: var(--color-surface); border: 1px solid var(--color-line); font: inherit; }
</style>
