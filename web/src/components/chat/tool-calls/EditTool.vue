<!-- apps/kimi-web/src/components/chat/tool-calls/EditTool.vue -->
<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { DiffViewLine, FilePreviewRequest, ToolCall, ToolMedia } from '../../../types';
import { diffStats } from '../../../lib/diffLines';
import { buildEditDiffLines } from '../../../lib/toolDiff';
import { toolGlyph, toolLabel, toolSummary } from '../../../lib/toolMeta';
import ToolRow from '../ToolRow.vue';
import ToolDetailButton from './ToolDetailButton.vue';
import { useToolPresentation } from './useToolPresentation';
import ToolOutputBlock, { hasPresentedToolOutput } from './ToolOutputBlock.vue';

const props = withDefaults(
  defineProps<{
    tool: ToolCall;
    stackPosition?: 'single' | 'first' | 'middle' | 'last';
    toolDiffPanel?: boolean;
    toolDetailAvailable?: boolean;
    toolDetailTarget?: ToolCall | null;
  }>(),
  { stackPosition: 'single', toolDiffPanel: false },
);

const emit = defineEmits<{
  openMedia: [media: ToolMedia];
  openFile: [target: FilePreviewRequest];
  openToolDiff: [id: string];
}>();
const { t } = useI18n();

const status = computed<'running' | 'ok' | 'error'>(() => props.tool.status as 'running' | 'ok' | 'error');
const label = computed(() => toolLabel(props.tool.name));
const glyph = computed(() => toolGlyph(props.tool.name));
const summary = computed(() => toolSummary(props.tool.name, props.tool.arg));
const summaryFull = computed(() => toolSummary(props.tool.name, props.tool.arg, true));

const editDiff = computed<DiffViewLine[] | null>(() => (
  canLoadDetail.value || props.tool.outputDeferred ? null : props.tool.diff?.lines ?? buildEditDiffLines(props.tool)
));
const chip = computed(() => {
  const diff = editDiff.value;
  if (diff && props.tool.status !== 'error') {
    const { added, removed } = diffStats(diff);
    if (added || removed) return `+${added} −${removed}`;
  }
  return '';
});

const hasOutput = computed(() => hasPresentedToolOutput(
  props.tool.output,
  props.tool.outputOmittedChars,
));
const { canLoadDetail, detailOpen, canExpand, open, toggle } = useToolPresentation(
  props, 'fileChange', computed(() => hasOutput.value),
);

</script>

<template>
  <ToolRow
    :status="status"
    :icon="glyph"
    :name="label"
    :arg="!open ? summary : ''"
    :time="tool.timing"
    :open="open"
    :expandable="canExpand"
    :stacked="stackPosition !== 'single'"
    :stack-position="stackPosition"
    @toggle="toggle"
  >
    <template #trailing>
      <span v-if="chip" class="chip">{{ chip }}</span>
      <ToolDetailButton v-if="canLoadDetail || detailOpen" :active="detailOpen" @toggle="emit('openToolDiff', tool.id)" />
      <span v-else-if="tool.outputDeferred" class="detail-unavailable">{{ t('tools.detail.unavailable') }}</span>
    </template>
    <div v-if="summaryFull" class="bb-summary">{{ summaryFull }}</div>
    <ToolOutputBlock
      :lines="tool.output"
      :omitted-chars="tool.outputOmittedChars"
      :head-line-count="tool.outputHeadLineCount"
      empty-text="Waiting for output…"
    />
  </ToolRow>
</template>

<style scoped>
.chip {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  flex: none;
}
.detail-unavailable {
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  flex: none;
}
.bb-summary {
  color: var(--color-text);
  border-bottom: 1px dashed var(--color-line);
  padding-bottom: 6px;
  margin-bottom: 6px;
  word-break: break-all;
}
</style>
