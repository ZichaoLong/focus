<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import PromptTime from '../components/chat/PromptTime.vue';
import type { PromptTimingStore } from './promptTimingStore';
import type { PromptTimingRecord } from './promptTimingTypes';
const props = defineProps<{ store: PromptTimingStore; threadId: string }>();
const { t } = useI18n();
const expanded = ref(false), loading = ref(false), failed = ref(false);
const server = ref<PromptTimingRecord[]>([]);
let generation = 0, timer: ReturnType<typeof setTimeout> | undefined;
const local = computed(() => props.store.records.value.filter(row => row.thread_id === props.threadId));
const rows = computed(() => {
  const map = new Map(server.value.map(row => [row.submission_id, { id: row.submission_id, time: row.submitted_at_ms, result: row.result }]));
  for (const row of local.value) if (!map.has(row.submission_id)) map.set(row.submission_id,
    { id: row.submission_id, time: row.submitted_at_ms, result: 'unconfirmed' });
  return [...map.values()].sort((a, b) => b.time - a.time).slice(0, 32);
});
const unresolved = computed(() => local.value.filter(row => !['succeeded', 'known_no_effect'].includes(
  server.value.find(value => value.submission_id === row.submission_id)?.result ?? row.browser.result ?? '')).length);
async function load() {
  if (!expanded.value || !props.threadId) return;
  const current = ++generation;
  loading.value = true; failed.value = false;
  try { await props.store.sync(); const result = await props.store.list(props.threadId); if (current === generation) server.value = result.records; }
  catch { if (current === generation) failed.value = true; }
  finally { if (current === generation) loading.value = false; }
}
function toggle(event: Event) {
  expanded.value = (event.target as HTMLDetailsElement).open;
  if (expanded.value) void load();
  else { generation += 1; loading.value = false; clearTimeout(timer); }
}
watch(() => props.threadId, () => { generation += 1; server.value = []; loading.value = false; clearTimeout(timer); if (expanded.value) void load(); });
watch(props.store.revision, () => {
  if (!expanded.value) return;
  clearTimeout(timer); timer = setTimeout(() => void load(), 250);
});
onUnmounted(() => { generation += 1; clearTimeout(timer); });
</script>

<template>
  <details class="timing-history" @toggle="toggle">
    <summary>{{ t('focus.timing.history') }}<span v-if="unresolved"> · {{ t('focus.timing.unresolved', { count: unresolved }) }}</span></summary>
    <p>{{ t('focus.timing.historyHelp') }}</p>
    <p v-if="!store.durable.value" role="status">{{ t('focus.timing.memoryOnly') }}</p>
    <p v-if="failed" role="status">{{ t('focus.timing.loadFailed') }}</p>
    <p v-if="loading" role="status">{{ t('focus.timing.loading') }}</p>
    <div v-for="row in rows" :key="row.id" class="timing-history-row">
      <span>{{ t(`focus.timing.result_${row.result}`) }}</span>
      <PromptTime :turn="{ promptTiming: { submissionId: row.id, submittedAtMs: row.time } }" />
    </div>
    <p v-if="!loading && !rows.length">{{ t('focus.timing.empty') }}</p>
    <button type="button" :disabled="loading" @click="load">{{ t('focus.timing.refresh') }}</button>
  </details>
</template>

<style scoped>
.timing-history { padding: var(--space-2) var(--space-4); color: var(--muted); font-size: var(--text-sm); max-height: 40vh; overflow-y: auto; flex-shrink: 0; }
.timing-history summary { cursor: pointer; }
.timing-history p { margin: var(--space-2) 0; }
.timing-history-row { padding: var(--space-2) 0; border-bottom: 1px solid var(--border); overflow-wrap: anywhere; }
.timing-history button { color: inherit; font: inherit; padding: var(--space-2); background: var(--hover); border: 0; border-radius: var(--radius-sm); cursor: pointer; }
</style>
