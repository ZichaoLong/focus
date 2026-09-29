<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';

defineProps<{ readingMode?: boolean }>();

const message = ref('');
let timer: ReturnType<typeof setTimeout> | null = null;

function show(value: string): void {
  message.value = value;
  if (timer !== null) clearTimeout(timer);
  timer = setTimeout(() => {
    message.value = '';
    timer = null;
  }, 4000);
}

onBeforeUnmount(() => { if (timer !== null) clearTimeout(timer); });
defineExpose({ show });
</script>

<template>
  <div v-if="message" class="transient-notice" :class="{ reading: readingMode }" role="status">
    {{ message }}
  </div>
</template>

<style scoped>
.transient-notice {
  position: absolute;
  z-index: var(--z-sticky);
  top: var(--space-3);
  left: 50%;
  width: max-content;
  max-width: min(520px, calc(100% - var(--space-6)));
  transform: translateX(-50%);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-warning-bd);
  border-radius: var(--radius-md);
  background: var(--color-warning-soft);
  color: var(--color-text);
  box-shadow: var(--shadow-md);
  overflow-wrap: anywhere;
  pointer-events: none;
}
.transient-notice.reading { top: calc(48px + var(--space-2)); }
@media (max-width: 640px) {
  .transient-notice { top: var(--space-2); }
  .transient-notice.reading { top: calc(50px + var(--safe-top) + var(--space-2)); }
}
</style>
