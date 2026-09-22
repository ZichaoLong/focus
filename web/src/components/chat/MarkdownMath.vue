<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { MathBlockNode, MathInlineNode, type MathBlockNodeProps, type MathInlineNodeProps } from 'markstream-vue';
import MarkdownCopyButton from './MarkdownCopyButton.vue';

defineOptions({ inheritAttrs: false });
const props = defineProps<{
  node: MathBlockNodeProps['node'] | MathInlineNodeProps['node'];
  indexKey?: string | number;
  cacheScope?: string | number;
}>();
const { t } = useI18n();
// Focus admits only closed \(…\), \[...\], and $$...$$ nodes. Their raw
// source retains whitespace and escapes that render-time normalization changes.
// Strip only the two-character delimiters; never copy rendered KaTeX DOM text.
const source = computed(() => props.node.raw.slice(2, -2));
</script>

<template>
  <div v-if="node.type === 'math_block'" class="md-math-block">
    <MathBlockNode :node="node" :index-key="indexKey" :cache-scope="cacheScope" />
    <MarkdownCopyButton v-if="!node.loading" :source="source" :label="t('filePreview.copyLatex')" />
  </div>
  <span v-else class="md-math-inline">
    <MathInlineNode :node="node" />
    <MarkdownCopyButton v-if="!node.loading" :source="source" :label="t('filePreview.copyLatex')" />
  </span>
</template>

<style scoped>
.md-math-block {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: 4px;
  margin: 0.6em 0;
}
.md-math-block :deep(.math-block__fallback) {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.md-math-inline > .md-copy-control {
  margin-inline: 2px;
}
.md-math-inline :deep(.ui-icon-button) {
  width: 22px;
  height: 22px;
}
@media (pointer: coarse) {
  .md-math-inline :deep(.ui-icon-button) {
    width: 32px;
    height: 32px;
  }
}
</style>
