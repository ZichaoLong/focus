<script setup lang="ts">
import { computed, inject, onBeforeUnmount, shallowRef, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ChatTurn, FilePreviewRequest } from '../../types';
import { replyContentReaderKey, type ReplyContentLease } from '../../composables/replyContent';
import Markdown from './LazyMarkdown.vue';
import MarkdownCopyButton from './MarkdownCopyButton.vue';
import ReplyTime from './ReplyTime.vue';

const props = defineProps<{ turn: ChatTurn; openFile?: (target: FilePreviewRequest) => void }>();
const { t } = useI18n();
const reader = inject(replyContentReaderKey, null);
const lease = shallowRef<ReplyContentLease | null>(null);
const generating = computed(() => props.turn.reply?.state === 'generating' && props.turn.status !== 'completed');
const state = computed(() => lease.value?.state.value);
// This component mounts only near the reading viewport, inside TranscriptRow.
watch([() => props.turn.id, () => props.turn.reply?.state, () => props.turn.reply?.completedAtMs, () => props.turn.status], () => {
  lease.value?.release();
  lease.value = !generating.value && reader ? reader.acquire(props.turn) : null;
}, { immediate: true });
onBeforeUnmount(() => lease.value?.release());
</script>
<template>
  <div class="inline-reply">
    <Markdown v-if="state?.text !== null && state?.text !== undefined" :text="state.text" :open-file="openFile" progressive />
    <template v-else>
      <pre class="reply-preview">{{ turn.text }}</pre>
      <div class="reply-notice" role="status">
        <template v-if="state?.error">
          <span>{{ t('conversation.replyLoadError') }} {{ state.error }}</span>
          <button type="button" @click="lease?.retry()">{{ t('conversation.replyRetry') }}</button>
        </template>
        <span v-else>{{ t(generating ? 'conversation.replyAwaitingCompletion' : 'conversation.replyLoading') }}</span>
      </div>
    </template>
    <div class="reply-footer">
      <ReplyTime v-if="turn.reply" :reply="turn.reply" />
      <MarkdownCopyButton v-if="state?.text !== null && state?.text !== undefined" :source="state.text" :label="t('filePreview.copy')" />
    </div>
  </div>
</template>
<style scoped>
.reply-preview { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
.reply-notice { display: flex; gap: 8px; margin-top: 8px; color: var(--muted); font-size: var(--text-sm); }
.reply-notice button { padding: 0; border: 0; background: none; color: var(--color-accent); font: inherit; cursor: pointer; }
.reply-footer { display: flex; align-items: center; gap: 8px; margin-top: 4px; }
</style>
