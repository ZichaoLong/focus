<!-- apps/kimi-web/src/components/chat/ToolCall.vue -->
<script setup lang="ts">
import { computed } from 'vue';
import type { FilePreviewRequest, ToolCall, ToolMedia } from '../../types';
import { toolGlyph, toolLabel, toolSummary } from '../../lib/toolMeta';
import ToolRow from './ToolRow.vue';
import ToolDetailButton from './tool-calls/ToolDetailButton.vue';
import { resolveToolRenderer } from './tool-calls/toolRegistry';
import { useToolDetail } from './tool-calls/useToolPresentation';

const props = withDefaults(
  defineProps<{
    tool: ToolCall;
    previewOnly?: boolean;
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
  openToolDiff: [tool: ToolCall];
  openFullContent: [];
  openAgent: [toolCallId: string];
}>();

const { canLoadDetail, detailOpen } = useToolDetail(props);
const Renderer = computed(() => resolveToolRenderer(props.tool));
const rendererToolDetailAvailable = computed(() => (
  props.tool.inspectionLocator?.kind === 'commandExecution'
  || props.tool.inspectionLocator?.kind === 'fileChange'
    ? props.toolDetailAvailable
    : undefined
));
</script>

<template>
  <ToolRow
    v-if="previewOnly"
    :status="tool.status"
    :icon="toolGlyph(tool.name)"
    :name="toolLabel(tool.name)"
    :arg="toolSummary(tool.name, tool.arg)"
    :data-scroll-anchor-id="tool.id"
  >
    <template #trailing>
      <ToolDetailButton :active="detailOpen" @toggle="canLoadDetail || detailOpen ? emit('openToolDiff', tool) : emit('openFullContent')" />
    </template>
  </ToolRow>
  <component
    v-else
    :is="Renderer"
    :tool="tool"
    :stack-position="stackPosition"
    :tool-diff-panel="toolDiffPanel"
    :tool-detail-available="rendererToolDetailAvailable"
    :tool-detail-target="toolDetailTarget"
    :data-scroll-anchor-id="tool.id"
    @open-media="emit('openMedia', $event)"
    @open-file="emit('openFile', $event)"
    @open-tool-diff="emit('openToolDiff', tool)"
    @open-agent="emit('openAgent', $event)"
  />
</template>
