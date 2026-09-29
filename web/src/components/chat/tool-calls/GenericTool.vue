<!-- apps/kimi-web/src/components/chat/tool-calls/GenericTool.vue -->
<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import type { CommandExecutionAction, FilePreviewRequest, ToolCall, ToolMedia } from '../../../types';
import { normalizeToolName, toolChip, toolGlyph, toolLabel, toolSummary } from '../../../lib/toolMeta';
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

const isRunningBash = computed(
  () => props.tool.status === 'running' && normalizeToolName(props.tool.name) === 'bash',
);
const hasOutput = computed(() => hasPresentedToolOutput(
  props.tool.output,
  props.tool.outputOmittedChars,
));
const commandExecutionLines = computed(() => {
  const facts = props.tool.commandExecution;
  if (!facts) return [];
  const lines: string[] = [];
  if (facts.cwd) lines.push(`cwd: ${facts.cwd}`);
  if (facts.source) lines.push(`source: ${facts.source}`);
  if (facts.processId) lines.push(`process: ${facts.processId}`);
  if (facts.exitCode !== undefined) lines.push(`exit code: ${facts.exitCode ?? 'pending'}`);
  for (const action of facts.commandActions ?? []) lines.push(commandActionLine(action));
  return lines;
});
const { canLoadDetail, detailOpen, canExpand, open, toggle } = useToolPresentation(
  props, 'commandExecution', computed(() => hasOutput.value || isRunningBash.value || commandExecutionLines.value.length > 0),
);

const status = computed<'running' | 'ok' | 'error'>(() => props.tool.status as 'running' | 'ok' | 'error');
const label = computed(() => toolLabel(props.tool.name));
const glyph = computed(() => toolGlyph(props.tool.name));
const summary = computed(() => toolSummary(props.tool.name, props.tool.arg));
const summaryFull = computed(() => toolSummary(props.tool.name, props.tool.arg, true));
const chip = computed(() =>
  toolChip({
    name: props.tool.name,
    arg: props.tool.arg,
    output: props.tool.output,
    timing: props.tool.timing,
    status: props.tool.status,
  }),
);

function commandActionLine(action: CommandExecutionAction): string {
  const kind = action.type?.trim() || 'action';
  const details = [
    action.command ? `$ ${action.command}` : '',
    action.name ? `name: ${action.name}` : '',
    action.path ? `path: ${action.path}` : '',
    action.query ? `query: ${action.query}` : '',
  ].filter(Boolean);
  return details.length > 0 ? `action (${kind}): ${details.join(' · ')}` : `action (${kind})`;
}
</script>

<template>
  <ToolRow
    :status="status"
    :icon="glyph"
    :name="label"
    :arg="!open ? summary : ''"
    :time="tool.name !== 'bash' ? tool.timing : ''"
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
    <div v-if="commandExecutionLines.length > 0" class="execution-facts">
      <div v-for="line in commandExecutionLines" :key="line">{{ line }}</div>
    </div>
    <ToolOutputBlock
      v-if="hasOutput || isRunningBash"
      :lines="tool.output"
      :omitted-chars="tool.outputOmittedChars"
      :head-line-count="tool.outputHeadLineCount"
      empty-text="Waiting for output…"
    />
  </ToolRow>
</template>

<style scoped>
.bb-summary {
  color: var(--color-text);
  border-bottom: 1px dashed var(--color-line);
  padding-bottom: 6px;
  margin-bottom: 6px;
  word-break: break-all;
}
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
.execution-facts {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  line-height: 1.55;
  overflow-wrap: anywhere;
}
</style>
