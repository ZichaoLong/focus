<!-- apps/kimi-web/src/components/chat/ToolGroup.vue -->
<script setup lang="ts">
import { computed } from 'vue';
import ToolCall from './ToolCall.vue';
import ToolGroupHeader from './ToolGroupHeader.vue';
import { toolStackKey, toolStackPosition } from '../chatTurnRendering';
import type { ToolStackItem } from '../chatTurnRendering';
import type { FilePreviewRequest, ToolCall as ToolCallData, ToolMedia } from '../../types';

const props = withDefaults(
  defineProps<{
    tools: ToolStackItem[];
    open: boolean;
    toolDiffPanel?: boolean;
    toolDetailAvailable?: boolean;
    toolDetailTarget?: ToolCallData | null;
  }>(),
  { toolDiffPanel: false },
);

const emit = defineEmits<{
  toggle: [];
  openMedia: [media: ToolMedia];
  openFile: [target: FilePreviewRequest];
  openToolDiff: [tool: ToolCallData];
  openAgent: [toolCallId: string];
}>();

const headerTools = computed(() => props.tools.map(item => item.tool));
</script>

<template>
  <div class="tool-group" :class="{ open }">
    <ToolGroupHeader :tools="headerTools" :open="open" @toggle="emit('toggle')" />
    <div class="tool-group-body" :class="{ open }" :inert="!open">
      <div class="tool-group-body-inner">
        <ToolCall
          v-for="(item, si) in tools"
          :key="toolStackKey(item)"
          :tool="item.tool"
          :stack-position="toolStackPosition(si, tools.length)"
          :tool-diff-panel="toolDiffPanel"
          :tool-detail-available="toolDetailAvailable" :tool-detail-target="toolDetailTarget"
          @open-media="emit('openMedia', $event)"
          @open-file="emit('openFile', $event)"
          @open-tool-diff="emit('openToolDiff', $event)"
          @open-agent="emit('openAgent', $event)"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-group {
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
  border: 1px solid var(--color-line);
  border-radius: var(--radius-md);
  overflow: hidden;
}
.tool-group-body {
  display: grid;
  grid-template-rows: minmax(0, 0fr);
  overflow: hidden;
  transition: grid-template-rows var(--duration-base) var(--ease-out);
}
.tool-group-body.open {
  grid-template-rows: minmax(0, 1fr);
}
.tool-group-body-inner {
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

</style>
