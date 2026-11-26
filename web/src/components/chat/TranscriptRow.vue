<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue';
import type { ChatTurn } from '../../types';
import { isEmptyAssistantTurn } from '../toolGroupPresentation';
import { markdownChunkHeightsKey } from '../../composables/markdownChunkHeights';
import { isTranscriptRowPinned } from './transcriptScrollAnchor';
import { observeTranscriptVisibility } from './transcriptVisibility';

const props = defineProps<{ turn: ChatTurn }>();
provide(markdownChunkHeightsKey, new Map());
const element = ref<HTMLElement | null>(null);
const visible = ref(typeof IntersectionObserver === 'undefined');
const height = ref<number | null>(null);
const empty = computed(() => isEmptyAssistantTurn(props.turn));
const estimate = computed(() => Math.min(1200, Math.max(64,
  Math.ceil((props.turn.text.length + (props.turn.thinking?.length ?? 0)) / 45) * 22)));

watch([element, empty], ([el, blank], _, onCleanup) => {
  if (blank) {
    height.value = null;
    visible.value = false;
    return;
  }
  if (!el) return;
  const stopVisibility = observeTranscriptVisibility(el, isVisible => {
    if (isVisible) visible.value = true;
    else if (!isTranscriptRowPinned(el)) {
      const measured = el.getBoundingClientRect().height;
      if (!empty.value && visible.value && measured > 0) height.value = measured;
      visible.value = false;
    }
  });
  const resize = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => {
    const measured = el.getBoundingClientRect().height;
    if (!empty.value && visible.value && measured > 0) height.value = measured;
  }) : null;
  resize?.observe(el);
  onCleanup(() => { stopVisibility(); resize?.disconnect(); });
}, { flush: 'post' });
</script>
<template>
  <div v-if="turn.itemId" ref="element" class="transcript-row turn-anchor"
    :hidden="empty"
    :class="{ 'transcript-assistant': turn.role === 'assistant' }"
    :data-turn-id="turn.id"
    :data-raw-turn-id="turn.rawTurnId"
    :data-prompt-id="turn.role === 'user' ? turn.id : undefined"
    :style="visible || empty ? undefined : { height: `${height ?? estimate}px` }">
    <slot v-if="visible && !empty" />
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
