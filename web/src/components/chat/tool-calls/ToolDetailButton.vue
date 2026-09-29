<script setup lang="ts">
import { useI18n } from 'vue-i18n';
defineProps<{ active: boolean }>();
const emit = defineEmits<{ toggle: [] }>();
const { t } = useI18n();
</script>

<template>
  <button type="button" class="tool-detail-button" :aria-pressed="active" @click.stop="emit('toggle')">
    {{ t(active ? 'tools.detail.close' : 'tools.detail.load') }}
  </button>
</template>

<style scoped>
.tool-detail-button {
  color: var(--color-accent);
  font: var(--text-xs) var(--font-ui);
  padding: 4px 6px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  white-space: nowrap;
}
.tool-detail-button:hover, .tool-detail-button[aria-pressed='true'] { background: var(--color-surface-sunken); }
.tool-detail-button:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 1px; }
</style>
