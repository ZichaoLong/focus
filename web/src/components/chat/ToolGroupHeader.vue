<!-- Extracted from apps/kimi-web/src/components/chat/ToolGroup.vue. -->
<script setup lang="ts">
import { computed, inject, nextTick, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ToolGroupSummary } from '../toolGroupPresentation';
import type { ToolCall } from '../../types';
import Icon from '../ui/Icon.vue';
import StatusDot from '../ui/StatusDot.vue';

const props = defineProps<{ tools: readonly ToolCall[]; open: boolean; savedCount?: number; summary?: ToolGroupSummary }>();
const emit = defineEmits<{ toggle: [] }>();
const { t } = useI18n();
const failed = computed(() => props.summary?.failed ?? props.tools.filter(tool => tool.status === 'error').length);
const running = computed(() => props.summary?.running ?? props.tools.filter(tool => tool.status === 'running').length);
const status = computed(() => running.value ? 'running'
  : failed.value ? 'error' : 'done');
const pinScroll = inject<(el: HTMLElement, ms?: number) => void>('pinScroll', () => {});
const element = ref<HTMLElement | null>(null);
function toggle(): void {
  emit('toggle');
  const header = element.value;
  if (header) void nextTick(() => pinScroll(header));
}
</script>

<template>
  <button ref="element" class="tool-group-head" type="button" :disabled="savedCount !== undefined" :aria-expanded="open" @click="toggle">
    <StatusDot v-if="savedCount === undefined" :status="status" />
    <span v-else class="saved-tool-dot" aria-hidden="true" />
    <Icon class="tg-ic" name="list" size="sm" />
    <span class="tg-title">{{ t(summary?.partial ? 'tools.group.loaded' : 'tools.group.title', savedCount ?? summary?.count ?? tools.length) }}</span>
    <span class="tg-meta" v-if="savedCount === undefined && status !== 'error'">· {{ running ? t('tools.group.runningCount', { count: running }) : t(`tools.group.${status}`) }}</span>
    <span class="tg-failed" v-if="failed">· {{ t('tools.group.failedCount', { count: failed }) }}</span>
    <Icon class="tg-car" name="chevron-right" size="sm" />
  </button>
</template>

<style scoped>
.tool-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  height: 32px;
  padding: 0 11px;
  border: none;
  background: transparent;
  color: var(--color-text-muted);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  text-align: left;
  cursor: pointer;
  user-select: none;
}
.tool-group-head:hover { background: var(--color-surface-sunken); color: var(--color-text); }
.tool-group-head:focus-visible { outline: none; box-shadow: inset 0 0 0 2px var(--color-accent-soft); }
.tg-ic { color: var(--color-text-faint); flex: none; }
.saved-tool-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--color-text-faint); }
.tg-title { font-weight: var(--weight-medium); color: var(--color-text); }
.tg-failed { color: var(--color-danger); }
.tg-meta { color: var(--color-text-faint); }
.tg-car {
  margin-left: auto;
  color: var(--color-text-faint);
  flex: none;
  transition: transform var(--duration-base) var(--ease-out);
}
.tool-group-head[aria-expanded="true"] .tg-car { transform: rotate(90deg); }
</style>
