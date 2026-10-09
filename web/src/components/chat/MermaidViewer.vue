<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { MermaidDiagram } from '../../lib/diagramViewport';
import Dialog from '../ui/Dialog.vue';
import ImageViewport from '../ui/ImageViewport.vue';

const props = defineProps<{ diagram: MermaidDiagram }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const open = ref(true);
// The image keeps sanitized SVG fragment IDs and links outside the document.
const source = URL.createObjectURL(new Blob([props.diagram.svg], { type: 'image/svg+xml' }));
async function close(): Promise<void> {
  open.value = false;
  await nextTick();
  emit('close');
}
onBeforeUnmount(() => URL.revokeObjectURL(source));
</script>

<template>
  <Dialog :open="open" title="Mermaid" size="full" :padded="false" initial-focus=".image-canvas" @close="close">
    <ImageViewport :source="source" :width="diagram.width" :height="diagram.height" alt="Mermaid"
      :help="t('filePreview.diagramControls')" :failed-text="t('filePreview.diagramFailed')" />
  </Dialog>
</template>
