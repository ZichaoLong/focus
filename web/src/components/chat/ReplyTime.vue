<script setup lang="ts">
import { computed, ref, useId } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ReplyMetadata } from '../../types';
import { formatMessageTime } from '../../lib/formatMessageTime';
import { formatDuration } from '../chatTurnRendering';

const props = defineProps<{ reply: ReplyMetadata }>();
const { t } = useI18n();
const expanded = ref(false);
const detailsId = useId();
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
  <template v-if="time !== undefined">
    <button type="button" class="reply-time" :aria-expanded="expanded" :aria-controls="expanded ? detailsId : undefined" @click.stop="expanded = !expanded">
      <span>{{ formatMessageTime(new Date(time).toISOString(), t('conversation.yesterday')) }}</span>
      <span v-if="reply.state === 'generating' && reply.completedAtMs === undefined">{{ t('conversation.replyGenerating') }}</span>
    </button>
    <div v-if="expanded" :id="detailsId" class="reply-time-details">
      <span v-if="reply.startedAtMs !== undefined">{{ t('conversation.replyStarted') }} {{ full(reply.startedAtMs) }}</span>
      <span v-if="reply.completedAtMs !== undefined">{{ t('conversation.replyCompleted') }} {{ full(reply.completedAtMs) }}</span>
      <span v-if="duration !== null">{{ t('conversation.replyDuration') }} {{ duration }}</span>
    </div>
  </template>
</template>
<style scoped>
.reply-time {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 22px;
  padding: 2px 0;
  box-sizing: border-box;
  white-space: nowrap;
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
.reply-time-details {
  order: 1;
  flex-basis: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: var(--muted);
  font-size: var(--text-sm);
  overflow-wrap: anywhere;
  opacity: 0.7;
}
@media (hover: none) {
  .reply-time {
    min-height: 32px;
    padding: 6px 0;
    margin-block: -4px;
  }
}
</style>
