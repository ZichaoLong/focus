import { computed, ref, watch, type ComputedRef } from 'vue';
import type { ToolCall } from '../../../types';

interface ToolPresentationProps {
  tool: ToolCall;
  toolDiffPanel?: boolean;
  toolDetailAvailable?: boolean;
  toolDetailTarget?: ToolCall | null;
}

/** Shared routing and selection for saved tool detail, including small headers. */
export function useToolDetail(
  props: ToolPresentationProps,
  kind?: 'commandExecution' | 'fileChange',
) {
  const canLoadDetail = computed(() => Boolean(
    props.toolDiffPanel && props.toolDetailAvailable
    && props.tool.status !== 'running' && props.tool.inspectionLocator
    && (!kind || props.tool.inspectionLocator.kind === kind),
  ));
  const detailOpen = computed(() => {
    const target = props.toolDetailTarget;
    const left = props.tool.inspectionLocator;
    const right = target?.inspectionLocator;
    return Boolean(target && left && right
      && left.turn_id === right.turn_id && left.item_id === right.item_id
      && left.kind === right.kind && left.change_index === right.change_index);
  });
  return { canLoadDetail, detailOpen };
}

/** Keep inline folding separate from the exact, externally owned detail target. */
export function useToolPresentation(
  props: ToolPresentationProps,
  kind: 'commandExecution' | 'fileChange',
  inlineAvailable: ComputedRef<boolean>,
) {
  const { canLoadDetail, detailOpen } = useToolDetail(props, kind);
  const canExpand = computed(() => inlineAvailable.value && !canLoadDetail.value && !props.tool.outputDeferred);
  const open = ref(props.tool.defaultExpanded === true && canExpand.value);
  let manuallyToggled = false;
  function toggle(): void {
    if (!canExpand.value) return;
    manuallyToggled = true;
    open.value = !open.value;
  }
  watch(() => props.tool.id, () => {
    manuallyToggled = false;
    open.value = props.tool.defaultExpanded === true && canExpand.value;
  });
  watch([canExpand, () => props.tool.defaultExpanded], () => {
    if (!canExpand.value) open.value = false;
    else if (!manuallyToggled && props.tool.defaultExpanded === true) open.value = true;
  });
  return { canLoadDetail, detailOpen, canExpand, open, toggle };
}
