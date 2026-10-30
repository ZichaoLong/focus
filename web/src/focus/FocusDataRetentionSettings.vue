<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import Select from '../components/ui/Select.vue';
import Button from '../components/ui/Button.vue';
import type { DataRetentionOwner } from './client-state/data-retention';
import type { FocusDataRetentionPolicy } from './types';
const props = defineProps<{ owner: DataRetentionOwner }>();
const { t } = useI18n();
function setPeriod(field: keyof FocusDataRetentionPolicy, value: string): void {
  const days = Number(value);
  if (days === 7 || days === 30 || days === 90) void props.owner.update({ [field]: days });
}
</script>

<template>
  <section class="retention-settings" :aria-label="t('focus.retentionTitle')">
    <div v-for="field in (['records_days', 'attachments_days'] as const)" :key="field" class="retention-row">
      <label :for="`retention-${field}`">{{ t(field === 'records_days' ? 'focus.retentionRecords' : 'focus.retentionAttachments') }}</label>
      <Select
        :id="`retention-${field}`"
        :model-value="String(owner.policy.value?.[field] ?? '')"
        :disabled="owner.busy.value || !owner.policy.value"
        size="sm"
        @update:model-value="setPeriod(field, $event)"
      >
        <option v-if="!owner.policy.value" value="" disabled>—</option>
        <option v-for="days in [7, 30, 90]" :key="days" :value="String(days)">{{ t('focus.retentionDays', { days }) }}</option>
      </Select>
    </div>
    <p class="retention-description">{{ t('focus.retentionDescription') }}</p>
    <p v-if="owner.notice.value" role="status" class="retention-description">{{ owner.notice.value }}</p>
    <Button :disabled="owner.busy.value || !owner.policy.value" variant="secondary" size="sm" @click="owner.prune()">
      {{ t(owner.busy.value ? 'focus.retentionWorking' : 'focus.retentionClean') }}
    </Button>
  </section>
</template>

<style scoped>
.retention-settings { display: grid; gap: var(--space-3); border-top: 1px solid var(--color-line); padding-top: var(--space-4); }
.retention-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.retention-row :deep(select) { width: 120px; flex: none; }
.retention-description { margin: 0; font-size: var(--text-sm); color: var(--color-text-muted); line-height: var(--leading-normal); }
</style>
