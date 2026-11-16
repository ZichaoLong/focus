<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import Button from '../components/ui/Button.vue';

const props = defineProps<{ rows: string[][] }>();
const { t } = useI18n();
const page = ref(0);
const pageSize = 50;
const pages = computed(() => Math.max(1, Math.ceil(props.rows.length / pageSize)));
const columns = computed(() => props.rows.reduce((max, row) => Math.max(max, row.length), 0));
const visibleRows = computed(() => props.rows.slice(page.value * pageSize, (page.value + 1) * pageSize));
</script>

<template>
  <div class="table-preview">
    <div class="table-preview-navigation">
      <span>{{ t('focus.filePreviewTableSize', { rows: rows.length, columns }) }}</span>
      <Button variant="ghost" :disabled="page === 0" @click="page--">{{ t('focus.filePreviewPrevious') }}</Button>
      <span>{{ page + 1 }} / {{ pages }}</span>
      <Button variant="ghost" :disabled="page + 1 >= pages" @click="page++">{{ t('focus.filePreviewNext') }}</Button>
    </div>
    <div class="table-preview-scroll" tabindex="0" :aria-label="t('focus.filePreviewTable')">
      <table>
        <thead><tr><th scope="col">#</th><th v-for="column in columns" :key="column" scope="col">{{ column }}</th></tr></thead>
        <tbody><tr v-for="(row, index) in visibleRows" :key="page * pageSize + index">
          <th scope="row">{{ page * pageSize + index + 1 }}</th>
          <td v-for="column in columns" :key="column">{{ row[column - 1] ?? '' }}</td>
        </tr></tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.table-preview { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.table-preview-navigation { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: var(--space-2); padding: var(--space-2); font-size: var(--text-sm); }
.table-preview-scroll { isolation: isolate; overflow: auto; flex: 1; min-height: 0; overscroll-behavior: contain; }
table { border-collapse: separate; border-spacing: 0; min-width: 100%; font: 400 14px/22px var(--font-mono); }
th, td { padding: var(--space-2) var(--space-3); border-bottom: 1px solid var(--color-line); border-right: 1px solid var(--color-line); text-align: start; vertical-align: top; white-space: pre-wrap; min-width: 6ch; max-width: 60ch; overflow-wrap: anywhere; }
th { background: var(--color-surface-raised); font-weight: 500; }
th:first-child { position: sticky; left: 0; z-index: 1; }
thead { position: sticky; top: 0; z-index: var(--z-sticky); }
</style>
