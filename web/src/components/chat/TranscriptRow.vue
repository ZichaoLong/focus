<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, provide, ref, watch } from 'vue';
import type { ChatTurn } from '../../types';
import { isEmptyAssistantTurn } from '../toolGroupPresentation';
import { markdownChunkHeightsKey } from '../../composables/markdownChunkHeights';
import { isTranscriptRowPinned } from './transcriptScrollAnchor';

const props = withDefaults(defineProps<{ turn: ChatTurn; folded?: boolean }>(), { folded: false });
provide(markdownChunkHeightsKey, new Map());
const element = ref<HTMLElement | null>(null);
const visible = ref(typeof IntersectionObserver === 'undefined');
const height = ref<number | null>(null);
const empty = computed(() => isEmptyAssistantTurn(props.turn));
const hidden = computed(() => props.folded || empty.value);
// Cleared content has no reusable height; folding real content keeps its measurement.
watch(empty, value => { if (value) height.value = null; });
const estimate = computed(() => Math.min(1200, Math.max(64,
  Math.ceil((props.turn.text.length + (props.turn.thinking?.length ?? 0)) / 45) * 22)));
let intersection: IntersectionObserver | null = null;
let resize: ResizeObserver | null = null;

onMounted(() => {
  const el = element.value;
  if (!el || !props.turn.itemId || typeof IntersectionObserver === 'undefined') return;
  intersection = new IntersectionObserver((entries) => {
    const entry = entries[0];
    if (!entry) return;
    if (entry.isIntersecting) visible.value = true;
    else if (!isTranscriptRowPinned(el)) {
      const measured = el.getBoundingClientRect().height;
      if (!hidden.value && visible.value && measured > 0) height.value = measured;
      visible.value = false;
    }
  }, { root: el.closest('.chat-scroll, .panes'), rootMargin: '900px 0px' });
  intersection.observe(el);
  if (typeof ResizeObserver !== 'undefined') {
    resize = new ResizeObserver(() => {
      if (!hidden.value && visible.value && el.getBoundingClientRect().height > 0) height.value = el.getBoundingClientRect().height;
    });
    resize.observe(el);
  }
});
onBeforeUnmount(() => { intersection?.disconnect(); resize?.disconnect(); });
</script>
<template>
  <div v-if="turn.itemId" ref="element" class="transcript-row turn-anchor"
    :hidden="hidden"
    :class="{ 'transcript-assistant': turn.role === 'assistant' }"
    :data-turn-id="turn.id"
    :data-raw-turn-id="turn.rawTurnId"
    :data-prompt-id="turn.role === 'user' ? turn.id : undefined"
    :style="visible || hidden ? undefined : { height: `${height ?? estimate}px` }">
    <slot v-if="visible && !hidden" />
  </div>
  <slot v-else />
</template>
<style scoped>
.transcript-row { display: flow-root; width: 100%; margin-top: var(--chat-turn-gap); }
.transcript-row[hidden] { display: none; }
.transcript-assistant { margin-top: 10px; }
.transcript-row:first-child { margin-top: 0; }
/* This row already owns offscreen mounting and measured placeholders.
   markstream's content-visibility:auto otherwise replaces even a short reply
   with a 600px intrinsic estimate after remount, changing intersection and
   repeatedly triggering unmount/remount plus scroll-anchor corrections. */
.transcript-row :deep(.markdown-renderer) {
  content-visibility: visible;
  contain-intrinsic-size: none;
}
</style>
