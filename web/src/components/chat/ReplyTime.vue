<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ReplyMetadata } from '../../types';
import { formatMessageTime } from '../../lib/formatMessageTime';
import { formatDuration } from '../chatTurnRendering';

const props = defineProps<{ reply: ReplyMetadata }>();
const { t } = useI18n();
const expanded = ref(false);
const time = computed(() => props.reply.completedAtMs ?? props.reply.startedAtMs);
const duration = computed(() => {
  const { startedAtMs: start, completedAtMs: end } = props.reply;
  return start !== undefined && end !== undefined && end >= start ? formatDuration(end - start) : null;
});
function full(value: number): string {
  const d = new Date(value);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
</script>
<template>
  <button v-if="time !== undefined" type="button" class="reply-time" :aria-expanded="expanded" @click.stop="expanded = !expanded">
    <template v-if="expanded">
      <span v-if="reply.startedAtMs !== undefined">{{ t('conversation.replyStarted') }} {{ full(reply.startedAtMs) }}</span>
      <span v-if="reply.completedAtMs !== undefined">{{ t('conversation.replyCompleted') }} {{ full(reply.completedAtMs) }}</span>
      <span v-if="duration !== null">{{ t('conversation.replyDuration') }} {{ duration }}</span>
    </template>
    <span v-else>{{ formatMessageTime(new Date(time).toISOString(), t('conversation.yesterday')) }}</span>
    <span v-if="reply.state === 'generating' && reply.completedAtMs === undefined">{{ t('conversation.replyGenerating') }}</span>
  </button>
</template>
<style scoped>
.reply-time {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  padding: 2px 0;
  margin-top: 4px;
  border: 0;
  background: none;
  color: var(--muted);
  font: inherit;
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
  opacity: 0.7;
}
.reply-time:hover { opacity: 1; }
</style>
