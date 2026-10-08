<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { centerDiagram, constrainDiagram, diagramFitScale, MAX_DIAGRAM_SCALE, moveDiagram,
  type DiagramPoint, type DiagramSize, type MermaidDiagram } from '../../lib/diagramViewport';
import Dialog from '../ui/Dialog.vue';
import Button from '../ui/Button.vue';
import IconButton from '../ui/IconButton.vue';
import Icon from '../ui/Icon.vue';

const props = defineProps<{ diagram: MermaidDiagram }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const open = ref(true);
const canvas = ref<HTMLElement | null>(null);
const bounds = ref<DiagramSize>({ width: 1, height: 1 });
const view = ref(centerDiagram(props.diagram, bounds.value));
const fitting = ref(true);
const dragging = ref(false);
const failed = ref(false);
// An image isolates SVG fragment IDs from the inline copy and cannot execute
// diagram links/scripts. The input was sanitized by the rendering boundary.
const source = URL.createObjectURL(new Blob([props.diagram.svg], { type: 'image/svg+xml' }));
const pointers = new Map<number, DiagramPoint>();
let resize: ResizeObserver | null = null;
const transform = computed(() => ({ width: `${props.diagram.width}px`, height: `${props.diagram.height}px`,
  transform: `translate(${view.value.x}px, ${view.value.y}px) scale(${view.value.scale})` }));
const percentage = computed(() => new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3 }).format(view.value.scale * 100));

function cancelGesture(): void { pointers.clear(); dragging.value = false; }
function fit(): void { cancelGesture(); fitting.value = true; view.value = centerDiagram(props.diagram, bounds.value); }
function actualSize(): void { cancelGesture(); fitting.value = false; view.value = centerDiagram(props.diagram, bounds.value, 1); }
function point(event: { clientX: number; clientY: number }): DiagramPoint {
  const rect = canvas.value!.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}
function zoom(factor: number, anchor = { x: bounds.value.width / 2, y: bounds.value.height / 2 }): void {
  fitting.value = false;
  view.value = moveDiagram(view.value, props.diagram, bounds.value, anchor, anchor, factor);
}
function start(event: PointerEvent): void {
  if (event.button !== 0) return;
  canvas.value?.focus({ preventScroll: true });
  canvas.value?.setPointerCapture(event.pointerId);
  pointers.set(event.pointerId, point(event));
  dragging.value = true;
}
function move(event: PointerEvent): void {
  if (!pointers.has(event.pointerId)) return;
  const before = [...pointers.values()];
  pointers.set(event.pointerId, point(event));
  const after = [...pointers.values()];
  const midpoint = (a: DiagramPoint, b = a) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  const distance = (a: DiagramPoint, b: DiagramPoint) => Math.hypot(a.x - b.x, a.y - b.y);
  const oldDistance = before.length > 1 ? distance(before[0]!, before[1]!) : 0;
  const factor = oldDistance > 0 ? distance(after[0]!, after[1]!) / oldDistance : 1;
  fitting.value = false;
  view.value = moveDiagram(view.value, props.diagram, bounds.value,
    midpoint(before[0]!, before[1]), midpoint(after[0]!, after[1]), factor);
}
function end(event: PointerEvent): void {
  pointers.delete(event.pointerId);
  dragging.value = pointers.size > 0;
}
function wheel(event: WheelEvent): void {
  const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? bounds.value.height : 1);
  zoom(Math.exp(-Math.max(-300, Math.min(300, pixels)) * 0.005), point(event));
}
function keydown(event: KeyboardEvent): void {
  let handled = true;
  if (event.key === '+' || event.key === '=') zoom(1.2);
  else if (event.key === '-') zoom(1 / 1.2);
  else if (event.key === '0') fit();
  else if (event.key.startsWith('Arrow')) {
    fitting.value = false;
    const delta = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] }[event.key];
    if (delta) view.value = constrainDiagram({ ...view.value, x: view.value.x + delta[0]!, y: view.value.y + delta[1]! }, props.diagram, bounds.value);
  } else handled = false;
  if (handled) { event.preventDefault(); event.stopPropagation(); }
}
function measure(): void {
  if (!canvas.value) return;
  const next = { width: canvas.value.clientWidth, height: canvas.value.clientHeight };
  if (!next.width || !next.height) return;
  const previous = bounds.value;
  bounds.value = next;
  cancelGesture();
  view.value = fitting.value ? centerDiagram(props.diagram, next)
    : constrainDiagram({ ...view.value, x: view.value.x + (next.width - previous.width) / 2,
      y: view.value.y + (next.height - previous.height) / 2 }, props.diagram, next);
}
async function close(): Promise<void> {
  open.value = false;
  // Let Dialog restore focus and release its stack slot before unmounting it.
  await nextTick();
  emit('close');
}
onMounted(() => {
  measure();
  resize = new ResizeObserver(measure);
  if (canvas.value) resize.observe(canvas.value);
  window.addEventListener('blur', cancelGesture);
});
onBeforeUnmount(() => {
  resize?.disconnect();
  window.removeEventListener('blur', cancelGesture);
  URL.revokeObjectURL(source);
});
</script>

<template>
  <Dialog :open="open" title="Mermaid" size="full" :padded="false" initial-focus=".mermaid-canvas" @close="close">
    <div class="mermaid-viewer" @wheel.stop.prevent>
      <div class="mermaid-toolbar">
        <Button variant="ghost" @click="fit">{{ t('filePreview.diagramFit') }}</Button>
        <Button variant="ghost" @click="actualSize">{{ t('filePreview.diagramActualSize') }}</Button>
        <IconButton :label="t('filePreview.diagramZoomOut')" :disabled="view.scale <= diagramFitScale(diagram, bounds) / 2" @click="zoom(1 / 1.2)"><Icon name="minus" /></IconButton>
        <span class="mermaid-scale">{{ percentage }}%</span>
        <IconButton :label="t('filePreview.diagramZoomIn')" :disabled="view.scale >= MAX_DIAGRAM_SCALE" @click="zoom(1.2)"><Icon name="plus" /></IconButton>
      </div>
      <div ref="canvas" class="mermaid-canvas" :class="{ dragging }" tabindex="0"
        :aria-label="t('filePreview.diagramControls')" @keydown="keydown"
        @pointerdown.stop.prevent="start" @pointermove.stop.prevent="move"
        @pointerup.stop="end" @pointercancel.stop="end" @lostpointercapture="end"
        @wheel.stop.prevent="wheel" @dragstart.prevent>
        <img v-if="!failed" :src="source" :style="transform" alt="Mermaid" draggable="false" @error="failed = true" />
        <p v-else class="mermaid-failed" role="alert">{{ t('filePreview.diagramFailed') }}</p>
      </div>
      <div class="mermaid-help">{{ t('filePreview.diagramControls') }}</div>
    </div>
  </Dialog>
</template>

<style scoped>
.mermaid-viewer { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.mermaid-toolbar { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 4px; padding: 4px 8px; }
.mermaid-scale { min-width: 5ch; text-align: center; font-size: var(--text-sm); color: var(--color-text-muted); }
.mermaid-canvas { position: relative; flex: 1; min-height: 0; overflow: hidden; touch-action: none; overscroll-behavior: none; user-select: none; cursor: grab; background: var(--color-surface); }
.mermaid-canvas.dragging { cursor: grabbing; }
.mermaid-canvas:focus-visible { outline: 2px solid var(--color-accent); outline-offset: -2px; }
.mermaid-canvas img { position: absolute; left: 0; top: 0; max-width: none; max-height: none; transform-origin: 0 0; pointer-events: none; }
.mermaid-help { padding: 8px 12px; text-align: center; font-size: var(--text-sm); color: var(--color-text-muted); }
.mermaid-failed { padding: 16px; }
</style>
