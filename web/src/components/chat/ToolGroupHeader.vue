<!-- Extracted from apps/kimi-web/src/components/chat/ToolGroup.vue. -->
<script setup lang="ts">
import { computed, inject, nextTick, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ToolCall } from '../../types';
import Icon from '../ui/Icon.vue';
import StatusDot from '../ui/StatusDot.vue';

const props = defineProps<{ tools: readonly ToolCall[]; open: boolean }>();
const emit = defineEmits<{ toggle: [] }>();
const { t } = useI18n();
const status = computed(() => props.tools.some(tool => tool.status === 'running') ? 'running'
  : props.tools.some(tool => tool.status === 'error') ? 'error' : 'done');
const pinScroll = inject<(el: HTMLElement, ms?: number) => void>('pinScroll', () => {});
const element = ref<HTMLElement | null>(null);
function toggle(): void {
  emit('toggle');
  const header = element.value;
  if (header) void nextTick(() => pinScroll(header));
}
</script>

<template>
  <button ref="element" class="tool-group-head" type="button" :aria-expanded="open" @click="toggle">
    <StatusDot :status="status" />
    <Icon class="tg-ic" name="list" size="sm" />
    <span class="tg-title">{{ t('tools.group.title', tools.length) }}</span>
    <span class="tg-meta">· {{ t(`tools.group.${status}`) }}</span>
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
.tg-title { font-weight: var(--weight-medium); color: var(--color-text); }
.tg-meta { color: var(--color-text-faint); }
.tg-car {
  margin-left: auto;
  color: var(--color-text-faint);
  flex: none;
  transition: transform var(--duration-base) var(--ease-out);
}
.tool-group-head[aria-expanded="true"] .tg-car { transform: rotate(90deg); }
</style>
