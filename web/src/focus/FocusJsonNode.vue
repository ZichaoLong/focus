<script setup lang="ts">
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { PreviewJsonNode } from './filePreviewJson';
import Button from '../components/ui/Button.vue';

const props = withDefaults(defineProps<{ node: PreviewJsonNode; depth?: number }>(), { depth: 0 });
const { t } = useI18n();
const expanded = ref(props.depth === 0);
const page = ref(0);
const pageSize = 100;
const pages = computed(() => Math.ceil((props.node.children?.length ?? 0) / pageSize));
const children = computed(() => props.node.children?.slice(page.value * pageSize, (page.value + 1) * pageSize));
</script>

<template>
  <div class="json-node">
    <button v-if="node.children?.length" type="button" class="json-node-toggle" :aria-expanded="expanded" @click="expanded = !expanded">
      <span aria-hidden="true">{{ expanded ? '▾' : '▸' }}</span><span class="json-key">{{ node.label }}</span>
      <span>{{ node.value }} · {{ node.children.length }}</span>
    </button>
    <div v-else class="json-node-value"><span class="json-key">{{ node.label }}:</span> <span>{{ node.value }}</span></div>
    <div v-if="expanded && children?.length" class="json-children">
      <FocusJsonNode v-for="child in children" :key="child.id" :node="child" :depth="depth + 1" />
      <div v-if="pages > 1" class="json-pages">
        <Button variant="ghost" :disabled="page === 0" @click="page--">{{ t('focus.filePreviewPrevious') }}</Button>
        <span>{{ page + 1 }} / {{ pages }}</span>
        <Button variant="ghost" :disabled="page + 1 >= pages" @click="page++">{{ t('focus.filePreviewNext') }}</Button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.json-node { font: 400 14px/22px var(--font-mono); }
.json-node-toggle { display: flex; align-items: center; gap: var(--space-2); min-height: 44px; border: 0; padding: 0 var(--space-1); border-radius: var(--radius-sm); background: transparent; color: var(--color-text); font: inherit; text-align: start; cursor: pointer; }
.json-node-toggle:hover { background: var(--color-surface-raised); }
.json-node-value { padding: var(--space-1); white-space: pre-wrap; overflow-wrap: anywhere; }
.json-key { color: var(--color-text-muted); overflow-wrap: anywhere; }
.json-children { margin-left: var(--space-4); border-left: 1px solid var(--color-line); padding-left: var(--space-2); }
.json-pages { display: flex; align-items: center; gap: var(--space-2); }
</style>
