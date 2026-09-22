<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
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

const inline = ref<HTMLElement>();
const copyPopover = ref<HTMLElement>();
const open = ref(false);
const position = ref({ top: '0px', left: '0px' });
let hovering = false;
let tapped = false;
let closeTimer: ReturnType<typeof setTimeout> | undefined;
let touch: { id: number; x: number; y: number; time: number } | undefined;

function keyboardFocused(): boolean {
  const active = document.activeElement;
  return !!active && !!inline.value?.contains(active) && active.matches(':focus-visible');
}

function close(): void {
  clearTimeout(closeTimer);
  open.value = false;
  tapped = false;
  touch = undefined;
  copyPopover.value?.hidePopover?.();
}

function place(): void {
  if (!inline.value || !copyPopover.value) return;
  const rect = inline.value.getBoundingClientRect();
  const { width, height } = copyPopover.value.getBoundingClientRect();
  const margin = 8;
  const top = rect.top >= height + margin ? rect.top - height : rect.bottom;
  position.value = {
    top: `${Math.max(margin, Math.min(top, window.innerHeight - height - margin))}px`,
    left: `${Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin))}px`,
  };
}

function show(): void {
  if (props.node.loading) return;
  clearTimeout(closeTimer);
  open.value = true;
  void nextTick(() => {
    if (!open.value) return;
    // The browser's top layer escapes transformed paragraphs and table clips
    // while keeping the control in the formula's DOM and keyboard order.
    copyPopover.value?.showPopover?.();
    place();
  });
}

function leave(): void {
  clearTimeout(closeTimer);
  // Allow the pointer to cross from the formula to its floating control.
  closeTimer = setTimeout(() => {
    if (!hovering && !tapped && !keyboardFocused()) close();
  }, 180);
}

function pointerEnter(event: PointerEvent): void {
  if (event.pointerType !== 'mouse' || event.buttons !== 0) return;
  hovering = true;
  show();
}

function pointerLeave(event: PointerEvent): void {
  if (event.pointerType !== 'mouse') return;
  hovering = false;
  leave();
}

function pointerDown(event: PointerEvent): void {
  if (copyPopover.value?.contains(event.target as Node)) return;
  if (event.pointerType === 'mouse' || !event.isPrimary) {
    close();
    return;
  }
  touch = { id: event.pointerId, x: event.clientX, y: event.clientY, time: event.timeStamp };
}

function pointerMove(event: PointerEvent): void {
  if (event.pointerType === 'mouse' && event.buttons !== 0
    && !copyPopover.value?.contains(event.target as Node)) close();
  if (touch && Math.hypot(event.clientX - touch.x, event.clientY - touch.y) > 10) touch = undefined;
}

function pointerUp(event: PointerEvent): void {
  const start = touch;
  touch = undefined;
  if (!start || start.id !== event.pointerId || event.timeStamp - start.time > 400) return;
  if (Math.hypot(event.clientX - start.x, event.clientY - start.y) > 10) return;
  if (window.getSelection()?.isCollapsed === false) return;
  tapped = true;
  show();
}

function focusIn(event: FocusEvent): void {
  // Touch focus must not open the action before a tap is distinguished from
  // long-press selection or scrolling.
  if ((event.target as HTMLElement).matches(':focus-visible')) show();
}

function keyDown(event: KeyboardEvent): void {
  if (event.target !== inline.value || (event.key !== 'Enter' && event.key !== ' ')) return;
  event.preventDefault();
  show();
  void nextTick(() => copyPopover.value?.querySelector('button')?.focus());
}

function outsidePointerDown(event: PointerEvent): void {
  if (!inline.value?.contains(event.target as Node)) close();
}

function escape(event: KeyboardEvent): void {
  if (event.key === 'Escape') close();
}

watch(open, (visible, _previous, onCleanup) => {
  if (!visible) return;
  document.addEventListener('pointerdown', outsidePointerDown, true);
  document.addEventListener('keydown', escape);
  window.addEventListener('scroll', close, true);
  window.addEventListener('resize', close);
  onCleanup(() => {
    document.removeEventListener('pointerdown', outsidePointerDown, true);
    document.removeEventListener('keydown', escape);
    window.removeEventListener('scroll', close, true);
    window.removeEventListener('resize', close);
  });
});
watch(source, close);
onBeforeUnmount(close);
</script>

<template>
  <div v-if="node.type === 'math_block'" class="md-math-block">
    <MathBlockNode :node="node" :index-key="indexKey" :cache-scope="cacheScope" />
    <MarkdownCopyButton v-if="!node.loading" :source="source" :label="t('filePreview.copyLatex')" />
  </div>
  <span
    v-else
    ref="inline"
    class="md-math-inline"
    :tabindex="node.loading ? -1 : 0"
    role="group"
    :aria-label="`${t('filePreview.copyLatex')}: ${source}`"
    @pointerenter="pointerEnter"
    @pointerleave="pointerLeave"
    @pointerdown="pointerDown"
    @pointermove="pointerMove"
    @pointerup="pointerUp"
    @pointercancel="touch = undefined"
    @contextmenu="close"
    @focusin="focusIn"
    @focusout="leave"
    @keydown="keyDown"
  >
    <MathInlineNode :node="node" />
    <span
      v-if="!node.loading"
      ref="copyPopover"
      popover="manual"
      class="md-math-copy-popover"
      :class="{ 'is-open': open }"
      :style="position"
    ><MarkdownCopyButton :source="source" :label="t('filePreview.copyLatex')" /></span>
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
.md-math-copy-popover {
  position: fixed;
  z-index: var(--z-tooltip);
  display: inline-flex;
  inset: auto;
  margin: 0;
  padding: 2px;
  border: 1px solid var(--color-line);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  box-shadow: var(--shadow-sm);
  line-height: 1;
  opacity: 0;
  pointer-events: none;
}
.md-math-copy-popover:not(.is-open) {
  display: none;
}
.md-math-inline:focus-visible {
  outline: none;
  border-radius: var(--radius-sm);
  box-shadow: var(--p-focus-ring);
}
.md-math-copy-popover.is-open {
  opacity: 1;
  pointer-events: auto;
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
