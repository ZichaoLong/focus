<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref } from 'vue';
import { markdownChunkHeightsKey } from '../../composables/markdownChunkHeights';

const props = defineProps<{ index: number; characters: number; lines: number }>();
const heights = inject(markdownChunkHeightsKey, new Map<number, number>());
const element = ref<HTMLElement | null>(null);
const visible = ref(typeof IntersectionObserver === 'undefined');
const height = ref(heights.get(props.index) ?? null);
const estimate = computed(() => Math.max(48, Math.max(props.lines, Math.ceil(props.characters / 50)) * 24));
let intersection: IntersectionObserver | null = null;
let resize: ResizeObserver | null = null;
function measure() {
  const el = element.value;
  if (!el || !visible.value) return;
  const box = el.getBoundingClientRect();
  if (box.height > 0) {
    height.value = box.height;
    heights.set(props.index, box.height);
  }
}
function pinned() {
  const el = element.value;
  const selection = el?.ownerDocument.getSelection();
  return !!el && (el.contains(el.ownerDocument.activeElement) || !!(selection && !selection.isCollapsed
    && (el.contains(selection.anchorNode) || el.contains(selection.focusNode))));
}
onMounted(() => {
  const el = element.value;
  if (!el || typeof IntersectionObserver === 'undefined') return;
  // Reflow visible chunks after a width change; already measured placeholders
  // keep their old height until they enter the viewport and can be measured.
  intersection = new IntersectionObserver(entries => {
    const entry = entries[0];
    if (!entry) return;
    if (entry.isIntersecting) visible.value = true;
    else if (!pinned()) { measure(); visible.value = false; }
  }, { root: el.closest('.chat-scroll, .panes'), rootMargin: '900px 0px' });
  intersection.observe(el);
  if (typeof ResizeObserver !== 'undefined') {
    resize = new ResizeObserver(measure); resize.observe(el);
  }
});
onBeforeUnmount(() => { measure(); intersection?.disconnect(); resize?.disconnect(); });
</script>
<template>
  <div ref="element" class="markdown-chunk" :data-transcript-chunk="index"
    :style="visible ? undefined : { height: `${height ?? estimate}px` }">
    <slot v-if="visible" />
  </div>
</template>
<style scoped>
.markdown-chunk { display: flow-root; }
</style>
