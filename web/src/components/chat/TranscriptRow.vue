<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue';
import type { ChatTurn } from '../../types';

const props = defineProps<{ turn: ChatTurn }>();
const element = ref<HTMLElement | null>(null);
const visible = ref(typeof IntersectionObserver === 'undefined');
const height = ref<number | null>(null);
const estimate = computed(() => Math.min(1200, Math.max(64,
  Math.ceil((props.turn.text.length + (props.turn.thinking?.length ?? 0)) / 45) * 22)));
let intersection: IntersectionObserver | null = null;
let resize: ResizeObserver | null = null;

function pinned(): boolean {
  const el = element.value;
  if (!el) return false;
  const selection = el.ownerDocument.getSelection();
  return el.contains(el.ownerDocument.activeElement)
    || !!(selection && !selection.isCollapsed
      && (el.contains(selection.anchorNode) || el.contains(selection.focusNode)));
}

onMounted(() => {
  const el = element.value;
  if (!el || !props.turn.itemId || typeof IntersectionObserver === 'undefined') return;
  intersection = new IntersectionObserver((entries) => {
    const entry = entries[0];
    if (!entry) return;
    if (entry.isIntersecting) visible.value = true;
    else if (!pinned()) {
      if (visible.value) height.value = el.getBoundingClientRect().height;
      visible.value = false;
    }
  }, { root: el.closest('.chat-scroll, .panes'), rootMargin: '900px 0px' });
  intersection.observe(el);
  if (typeof ResizeObserver !== 'undefined') {
    resize = new ResizeObserver(() => {
      if (visible.value && el.getBoundingClientRect().height > 0) height.value = el.getBoundingClientRect().height;
    });
    resize.observe(el);
  }
});
onBeforeUnmount(() => { intersection?.disconnect(); resize?.disconnect(); });
</script>
<template>
  <div v-if="turn.itemId" ref="element" class="transcript-row turn-anchor"
    :class="{ 'transcript-assistant': turn.role === 'assistant' }"
    :data-turn-id="turn.id"
    :data-raw-turn-id="turn.rawTurnId"
    :data-prompt-id="turn.role === 'user' ? turn.id : undefined"
    :style="visible ? undefined : { height: `${height ?? estimate}px` }">
    <slot v-if="visible" />
  </div>
  <slot v-else />
</template>
<style scoped>
.transcript-row { display: flow-root; width: 100%; margin-top: var(--chat-turn-gap); }
.transcript-assistant { margin-top: 10px; }
.transcript-row:first-child { margin-top: 0; }
</style>
