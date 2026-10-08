<script setup lang="ts">
import { inject } from 'vue';
import { MermaidBlockNode, toSafeMermaidSvgMarkup, type MermaidBlockEvent, type MermaidBlockNodeProps } from 'markstream-vue';
import type { MermaidDiagram } from '../../lib/diagramViewport';

defineOptions({ inheritAttrs: false });
withDefaults(defineProps<{
  node: MermaidBlockNodeProps['node'];
  loading?: boolean;
  isDark?: boolean;
}>(), { loading: true });
const showViewer = inject<(diagram: MermaidDiagram) => void>('focusMarkdownMermaidViewer');

function openDiagram(event: MermaidBlockEvent): void {
  if (!showViewer) return;
  const svg = event.svgString && toSafeMermaidSvgMarkup(event.svgString);
  if (!svg) return;
  const element = new DOMParser().parseFromString(svg, 'image/svg+xml').documentElement;
  const box = element.getAttribute('viewBox')?.trim().split(/[\s,]+/).map(Number);
  const width = box?.[2] ?? Number.parseFloat(element.getAttribute('width') ?? '');
  const height = box?.[3] ?? Number.parseFloat(element.getAttribute('height') ?? '');
  if (!(Number.isFinite(width) && width > 0 && Number.isFinite(height) && height > 0)) return;
  // Keep the upstream strict renderer/source fallback, but own the viewing
  // interaction. A snapshot avoids re-rendering Mermaid or changing mid-drag.
  event.preventDefault();
  showViewer({ svg, width, height });
}
</script>

<template>
  <div class="md-mermaid">
    <MermaidBlockNode v-bind="$attrs" :node="node" :loading="loading" :is-dark="isDark"
      :show-zoom-controls="false" :enable-wheel-zoom="false" :is-strict="true"
      :enable-mermaid-interactions="false" @open-modal="openDiagram" />
  </div>
</template>

<style scoped>
.md-mermaid { --ms-size-diagram-min-height: 160px; }
.md-mermaid :deep(.mermaid-block-header) { flex-wrap: wrap; gap: 4px; }
.md-mermaid :deep(.mermaid-block-header > div) { flex-shrink: 0; }
.md-mermaid :deep(.mermaid-block-header button) { white-space: nowrap; }
.md-mermaid :deep(.mermaid-header-actions) { margin-left: auto; }
/* The inline diagram is an overview, not a second pan surface nested in the
   transcript scroller. Keep the library's measured height, bounded on phones. */
.md-mermaid :deep(.mermaid-preview-area) {
  min-height: 0;
  max-height: min(420px, 50dvh);
  pointer-events: none;
}
.md-mermaid :deep([data-mermaid-wrapper]) { transform: none !important; }
.md-mermaid :deep(._mermaid) {
  height: 100% !important;
  min-height: 0;
  content-visibility: visible;
}
.md-mermaid :deep(._mermaid svg) {
  width: 100%;
  height: 100%;
  max-width: 100% !important;
}
</style>
