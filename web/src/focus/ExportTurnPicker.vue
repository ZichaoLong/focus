<script setup lang="ts">
import { useI18n } from 'vue-i18n';
import type { UnwrapNestedRefs } from 'vue';
import Button from '../components/ui/Button.vue';
import Markdown from '../components/chat/Markdown.vue';
import { MAX_SELECTED_EXPORT_TURNS, type createExportTurnSelection } from './exportTurnSelection';

defineProps<{ selection: UnwrapNestedRefs<ReturnType<typeof createExportTurnSelection>> }>();
const { t } = useI18n();
</script>

<template>
  <section class="export-picker" :aria-label="t('focus.exportSelected')" :aria-busy="selection.loading">
    <div class="export-picker-toolbar">
      <span role="status">{{ t('focus.exportSelectedCount', { count: selection.selected.length, max: MAX_SELECTED_EXPORT_TURNS }) }}</span>
      <Button type="button" size="sm" variant="ghost" :disabled="!selection.canSelectPage" @click="selection.selectPage()">{{ t('focus.exportSelectPage') }}</Button>
      <Button type="button" size="sm" variant="ghost" :disabled="!selection.selected.length" @click="selection.clear()">{{ t('focus.exportClear') }}</Button>
    </div>
    <p class="export-picker-help">{{ t('focus.exportSelectedHelp') }}</p>
    <p v-if="selection.error" role="alert" class="export-picker-error">
      {{ selection.error }}
      <Button type="button" size="sm" variant="ghost" @click="selection.load()">{{ t('focus.retry') }}</Button>
    </p>
    <p v-if="selection.loading" role="status">{{ t('focus.exportTurnsLoading') }}</p>
    <p v-else-if="!selection.rows.length && !selection.error">{{ t('focus.exportTurnsEmpty') }}</p>
    <div class="export-picker-list">
      <article v-for="row in selection.rows" :key="row.turn_id" class="export-picker-row">
        <label class="export-picker-choice">
          <input
            type="checkbox" :checked="selection.selected.includes(row.turn_id)"
            :disabled="selection.loading || (!selection.selected.includes(row.turn_id) && (row.status !== 'completed' || selection.selected.length >= MAX_SELECTED_EXPORT_TURNS))"
            @change="selection.toggle(row)"
          >
          <span>{{ row.prompt }}</span>
        </label>
        <p v-if="row.answer" class="export-picker-answer">{{ row.answer }}</p>
        <div class="export-picker-toolbar">
          <span v-if="row.status !== 'completed'" class="export-picker-help">{{ t(`focus.exportTurn_${row.status}`) }}</span>
          <Button
            v-else type="button" size="sm" variant="ghost" :disabled="selection.loading"
            :aria-expanded="selection.previewId === row.turn_id"
            :aria-label="t('focus.exportPreviewTurn', { prompt: row.prompt })" @click="selection.preview(row)"
          >{{ t(selection.previewId === row.turn_id ? 'focus.exportHidePreview' : 'focus.exportPreview') }}</Button>
        </div>
        <div v-if="selection.previewId === row.turn_id" class="export-picker-preview">
          <p v-if="selection.previewLoading" role="status">{{ t('focus.exportTurnsLoading') }}</p>
          <p v-else-if="selection.previewError" role="alert" class="export-picker-error">{{ selection.previewError }}</p>
          <Markdown v-else :text="selection.previewText" :progressive="false" :defer-images="true" />
        </div>
      </article>
    </div>
    <div class="export-picker-toolbar export-picker-pages">
      <Button type="button" size="sm" variant="secondary" :disabled="selection.loading || selection.pageIndex === 0" @click="selection.load(selection.pageIndex - 1)">{{ t('focus.exportNewerPage') }}</Button>
      <span>{{ t('focus.exportPage', { page: selection.pageIndex + 1 }) }}</span>
      <Button type="button" size="sm" variant="secondary" :disabled="selection.loading || !selection.hasNext" @click="selection.load(selection.pageIndex + 1)">{{ t('focus.exportOlderPage') }}</Button>
    </div>
  </section>
</template>

<style scoped>
.export-picker { display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; }
.export-picker-toolbar { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; font-size: var(--text-sm); }
.export-picker-help, .export-picker-answer { color: var(--color-text-muted); font-size: var(--text-sm); margin: 0; overflow-wrap: anywhere; }
.export-picker-error { color: var(--color-danger); overflow-wrap: anywhere; }
.export-picker-list { max-height: 42vh; overflow: auto; border: 1px solid var(--color-line); border-radius: var(--radius-md); }
.export-picker-row { padding: var(--space-3); display: flex; flex-direction: column; gap: var(--space-2); }
.export-picker-row + .export-picker-row { border-top: 1px solid var(--color-line); }
.export-picker-choice { display: flex; align-items: flex-start; gap: var(--space-2); cursor: pointer; overflow-wrap: anywhere; }
.export-picker-choice input { flex: none; margin-top: 4px; accent-color: var(--color-accent); }
.export-picker-preview { min-width: 0; overflow-wrap: anywhere; }
.export-picker-pages { justify-content: space-between; }
</style>
