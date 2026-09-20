<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import Banner from '../components/ui/Banner.vue';
import Spinner from '../components/ui/Spinner.vue';
import type { FocusUpdateStatus } from './types';

const props = defineProps<{
  status: FocusUpdateStatus | null;
  active: boolean;
  busy: boolean;
  stale: boolean;
  notice: string;
  observedAt: number;
  visible: boolean;
}>();

const { t, locale } = useI18n();
const now = ref(Date.now());
let clock: ReturnType<typeof setInterval> | null = null;
function stopClock(): void {
  if (clock !== null) clearInterval(clock);
  clock = null;
}
watch(() => props.visible && props.active, (running) => {
  stopClock();
  now.value = Date.now();
  if (running) clock = setInterval(() => { now.value = Date.now(); }, 1000);
}, { immediate: true });
onUnmounted(stopClock);

const elapsed = computed(() => {
  const seconds = Math.max(0, Math.floor((now.value - props.observedAt) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
});
const heading = computed(() => {
  if (props.status?.state === 'checking') {
    return t('focus.updateChecking', { target: props.status.target });
  }
  if (props.status?.state === 'applying') {
    return t(props.status.installation_started ? 'focus.updateInstalling' : 'focus.updateRechecking');
  }
  if (props.status?.state === 'succeeded' && props.active) return t('focus.updateReloading');
  return t('focus.updateSubmitting');
});
</script>

<template>
  <div class="update-progress">
    <div v-if="active || busy" class="update-progress-heading" role="status" aria-live="polite">
      <Spinner size="sm" aria-hidden="true" />
      <span>{{ heading }}</span>
    </div>
    <p v-if="active">{{ t('focus.updateBackground') }}</p>
    <p v-if="active && observedAt">{{ t('focus.updateElapsed', { elapsed }) }}</p>
    <p v-if="status?.updated_at">
      {{ t('focus.updateLastRecorded', { time: new Date(status.updated_at * 1000).toLocaleString(locale) }) }}
    </p>
    <Banner v-if="notice" variant="info">{{ notice }}</Banner>
    <Banner v-if="stale" variant="warning">{{ t('focus.updateStatusStale') }}</Banner>
    <Banner v-if="status?.state === 'unknown'" variant="warning">{{ t('focus.updateOutcomeUnknown') }}</Banner>
  </div>
</template>

<style scoped>
.update-progress { display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }
.update-progress-heading { display: flex; align-items: center; gap: var(--space-2); }
.update-progress p { margin: 0; color: var(--color-text-muted); font-size: var(--text-sm); }
</style>
