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
  appearance: none;
  border: 0;
  background: transparent;
  color: var(--color-accent);
  font: inherit;
  padding: 0;
  cursor: pointer;
  white-space: nowrap;
}
.tool-detail-button:hover, .tool-detail-button:focus-visible {
  text-decoration: underline;
  text-underline-offset: 2px;
}
.tool-detail-button:focus-visible { outline: none; }
</style>
