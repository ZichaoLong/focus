<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { ChatTurn } from '../../types';
import { formatMessageTime } from '../../lib/formatMessageTime';
import { copyTextToClipboard } from '../../lib/clipboard';
import { promptTimingKey, type PromptTimingView } from './promptTiming';
const props = defineProps<{ turn: Pick<ChatTurn, 'promptTiming' | 'codexRecordedAtMs' | 'clientUserMessageId'> }>();
const { t } = useI18n();
const reader = inject(promptTimingKey, null);
const id = computed(() => props.turn.promptTiming?.submissionId ?? props.turn.clientUserMessageId?.slice(10) ?? '');
const submitted = computed(() => props.turn.promptTiming?.submittedAtMs ?? reader?.local(id.value)?.submittedAtMs ?? detail.value?.submittedAtMs);
const time = computed(() => submitted.value ?? props.turn.codexRecordedAtMs);
const expanded = ref(false), loading = ref(false), error = ref(false), copied = ref(false);
const detail = ref<PromptTimingView | null>(null);
let generation = 0;
const full = (value: number) => new Date(value).toLocaleString(undefined, { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3 });
async function load() {
  if (!reader || !id.value || !expanded.value) return;
  const current = ++generation;
  loading.value = true; error.value = false; copied.value = false;
  try { const value = await reader.read(id.value, props.turn.codexRecordedAtMs); if (current === generation) detail.value = value; }
  catch { if (current === generation) error.value = true; }
  finally { if (current === generation) loading.value = false; }
}
function toggle() {
  expanded.value = !expanded.value;
  if (expanded.value) void load();
  else { generation += 1; loading.value = false; }
}
watch(id, () => { generation += 1; expanded.value = false; detail.value = null; error.value = false; copied.value = false; });
onUnmounted(() => { generation += 1; });
async function copy() { if (detail.value) copied.value = await copyTextToClipboard(detail.value.diagnostic); }
</script>

<template>
  <template v-if="time !== undefined || id">
    <button type="button" class="prompt-time-label" :aria-expanded="expanded" @click.stop="toggle">
      {{ time !== undefined ? formatMessageTime(new Date(time).toISOString(), t('conversation.yesterday')) : t('focus.timing.details') }}
    </button>
    <div v-if="expanded" class="prompt-time-detail">
      <div v-if="submitted !== undefined">{{ t('focus.timing.submitted') }}: {{ full(submitted) }}</div>
      <div v-if="detail?.receivedAtMs !== undefined">{{ t('focus.timing.serviceReceived') }}: {{ full(detail.receivedAtMs) }}</div>
      <div v-if="turn.codexRecordedAtMs !== undefined">{{ t('focus.timing.codexRecorded') }}: {{ full(turn.codexRecordedAtMs) }}</div>
      <div v-for="(line, index) in detail?.lines ?? []" :key="index"><span>{{ line.label }}: </span>{{ line.value }}</div>
      <div v-if="!id">{{ t('focus.timing.firstOutput') }}: {{ t('focus.timing.output_not_recorded') }}</div>
      <p v-if="loading && !detail" role="status">{{ t('focus.timing.loading') }}</p>
      <p v-if="error" role="status">{{ t(detail ? 'focus.timing.refreshFailed' : 'focus.timing.loadFailed') }}</p>
      <div v-if="reader && id" class="prompt-time-actions">
        <button type="button" :disabled="loading" @click.stop="load">{{ t('focus.timing.refresh') }}</button>
        <button v-if="detail" type="button" @click.stop="copy">{{ t(copied ? 'focus.promptDiagnosticCopied' : 'focus.promptDiagnosticCopy') }}</button>
      </div>
    </div>
  </template>
</template>

<style scoped>
.prompt-time-label { border: 0; background: none; color: var(--muted); padding: 4px 0; cursor: pointer; font: inherit; font-size: var(--text-sm); text-align: left; white-space: nowrap; }
.prompt-time-detail { order: 1; flex-basis: 100%; min-width: 0; max-height: 40vh; overflow-y: auto; color: var(--muted); font-size: var(--text-sm); padding: var(--space-2) 0; overflow-wrap: anywhere; user-select: text; line-height: 1.6; text-align: left; }
.prompt-time-detail p { margin: var(--space-2) 0; }
.prompt-time-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-2); }
.prompt-time-actions button { font: inherit; color: inherit; cursor: pointer; background: var(--hover); border: 0; border-radius: var(--radius-sm); padding: var(--space-2); }
</style>
