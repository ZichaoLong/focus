<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { centerDiagram, constrainDiagram, diagramFitScale, MAX_DIAGRAM_SCALE, moveDiagram,
  type DiagramPoint, type DiagramSize } from '../../lib/diagramViewport';
import Button from './Button.vue';
import IconButton from './IconButton.vue';
import Icon from './Icon.vue';

const props = defineProps<{ source: string; width: number; height: number; alt: string; help: string; failedText: string; naturalSize?: boolean; hideHelp?: boolean }>();
const emit = defineEmits<{ failed: [] }>();
const { t } = useI18n();
const canvas = ref<HTMLElement | null>(null);
const imageSize = ref<DiagramSize>({ width: props.width, height: props.height });
const bounds = ref<DiagramSize>({ width: 1, height: 1 });
const view = ref(centerDiagram(imageSize.value, bounds.value));
const fitting = ref(true);
const dragging = ref(false);
const failed = ref(false);
const pointers = new Map<number, DiagramPoint>();
let resize: ResizeObserver | null = null;
const transform = computed(() => ({ width: `${imageSize.value.width}px`, height: `${imageSize.value.height}px`,
  transform: `translate(${view.value.x}px, ${view.value.y}px) scale(${view.value.scale})` }));
const percentage = computed(() => new Intl.NumberFormat(undefined, { maximumSignificantDigits: 3 }).format(view.value.scale * 100));

function cancelGesture(): void { pointers.clear(); dragging.value = false; }
function fit(): void { cancelGesture(); fitting.value = true; view.value = centerDiagram(imageSize.value, bounds.value); }
function actualSize(): void { cancelGesture(); fitting.value = false; view.value = centerDiagram(imageSize.value, bounds.value, 1); }
function loaded(event: Event): void {
  const image = event.target as HTMLImageElement;
  // Camera JPEGs can have EXIF rotation. Browser-oriented dimensions preserve
  // their aspect ratio; Mermaid keeps its explicit diagram dimensions.
  if (props.naturalSize && image.naturalWidth && image.naturalHeight) {
    imageSize.value = { width: image.naturalWidth, height: image.naturalHeight };
    fit();
  }
}
function point(event: { clientX: number; clientY: number }): DiagramPoint {
  const rect = canvas.value!.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}
function zoom(factor: number, anchor = { x: bounds.value.width / 2, y: bounds.value.height / 2 }): void {
  fitting.value = false;
  view.value = moveDiagram(view.value, imageSize.value, bounds.value, anchor, anchor, factor);
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
  view.value = moveDiagram(view.value, imageSize.value, bounds.value,
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
    if (delta) view.value = constrainDiagram({ ...view.value, x: view.value.x + delta[0]!, y: view.value.y + delta[1]! }, imageSize.value, bounds.value);
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
  view.value = fitting.value ? centerDiagram(imageSize.value, next)
    : constrainDiagram({ ...view.value, x: view.value.x + (next.width - previous.width) / 2,
      y: view.value.y + (next.height - previous.height) / 2 }, imageSize.value, next);
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
});
</script>

<template>
    <div class="image-viewer" @wheel.stop.prevent>
      <div class="image-toolbar">
        <Button variant="ghost" @click="fit">{{ t('filePreview.diagramFit') }}</Button>
        <Button variant="ghost" @click="actualSize">{{ t('filePreview.diagramActualSize') }}</Button>
        <IconButton :label="t('filePreview.imageZoomOut')" :disabled="view.scale <= diagramFitScale(imageSize, bounds) / 2" @click="zoom(1 / 1.2)"><Icon name="minus" /></IconButton>
        <span class="image-scale">{{ percentage }}%</span>
        <IconButton :label="t('filePreview.imageZoomIn')" :disabled="view.scale >= MAX_DIAGRAM_SCALE" @click="zoom(1.2)"><Icon name="plus" /></IconButton>
      </div>
      <div ref="canvas" class="image-canvas" :class="{ dragging }" tabindex="0"
        :aria-label="help" @keydown="keydown"
        @pointerdown.stop.prevent="start" @pointermove.stop.prevent="move"
        @pointerup.stop="end" @pointercancel.stop="end" @lostpointercapture="end"
        @wheel.stop.prevent="wheel" @dragstart.prevent>
        <img v-if="!failed" :src="source" :style="transform" :alt="alt" draggable="false" @load="loaded" @error="failed = true; emit('failed')" />
        <p v-else class="image-failed" role="alert">{{ failedText }}</p>
      </div>
      <div v-if="!hideHelp" class="image-help">{{ help }}</div>
    </div>
</template>

<style scoped>
.image-viewer { height: 100%; display: flex; flex-direction: column; min-height: 0; }
.image-toolbar { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 4px; padding: 4px 8px; }
.image-scale { min-width: 5ch; text-align: center; font-size: var(--text-sm); color: var(--color-text-muted); }
.image-canvas { position: relative; flex: 1; min-height: 0; overflow: hidden; touch-action: none; overscroll-behavior: none; user-select: none; cursor: grab; background: var(--color-surface); }
.image-canvas.dragging { cursor: grabbing; }
.image-canvas:focus-visible { outline: 2px solid var(--color-accent); outline-offset: -2px; }
.image-canvas img { position: absolute; left: 0; top: 0; max-width: none; max-height: none; transform-origin: 0 0; pointer-events: none; }
.image-help { padding: 8px 12px; text-align: center; font-size: var(--text-sm); color: var(--color-text-muted); }
.image-failed { padding: 16px; }
</style>
