<script setup lang="ts">
import { inject, type ComputedRef } from 'vue';
import { MarkdownCodeBlockNode, PreCodeNode, type CodeBlockNodeProps } from 'markstream-vue';
import { useI18n } from 'vue-i18n';
import MarkdownCopyButton from './MarkdownCopyButton.vue';

defineOptions({ inheritAttrs: false });
defineProps<{
  node: CodeBlockNodeProps['node'];
  isDark?: boolean;
  darkTheme?: string;
  lightTheme?: string;
  stream?: boolean;
}>();
const renderer = inject<ComputedRef<'pre' | 'shiki'>>('focusMarkdownCodeRenderer');
const { t } = useI18n();
</script>

<template>
  <div class="code-block-container md-code-block">
    <div class="code-block-header md-code-header">
      <span>{{ node.language || 'text' }}</span>
      <MarkdownCopyButton :source="node.code" :label="t('filePreview.copyCode')" />
    </div>
    <PreCodeNode v-if="renderer === 'pre'" class="code-pre-fallback" :node="node" />
    <MarkdownCodeBlockNode
      v-else
      :node="node"
      :is-dark="isDark"
      :dark-theme="darkTheme"
      :light-theme="lightTheme"
      :stream="stream"
      :loading="false"
      :show-header="false"
    />
  </div>
</template>

<style scoped>
.md-code-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
</style>
