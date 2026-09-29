import { computed, effectScope, nextTick, reactive } from 'vue';
import { describe, expect, it } from 'vitest';
import type { ToolCall } from '../src/types';
import { useToolPresentation } from '../src/components/chat/tool-calls/useToolPresentation';

describe('tool inline and saved detail presentation', () => {
  it.each(['commandExecution', 'fileChange'] as const)('closes an expanded %s on completion and keeps detail separate', async (kind) => {
    const scope = effectScope();
    const props = reactive({
      tool: { id: 'tool', name: 'Shell', arg: '', status: 'running', output: ['live'], defaultExpanded: true } as ToolCall,
      toolDiffPanel: true, toolDetailAvailable: true, toolDetailTarget: null as ToolCall | null,
    });
    const state = scope.run(() => useToolPresentation(props, kind, computed(() => true)))!;
    expect(state.open.value).toBe(true);
    state.toggle();
    props.tool.output!.push('more');
    await nextTick();
    expect(state.open.value).toBe(false);
    state.toggle();
    props.tool = { ...props.tool, status: 'ok', output: [], outputDeferred: true,
      inspectionLocator: { turn_id: 'turn', item_id: 'item', kind, change_index: kind === 'fileChange' ? 0 : null } };
    await nextTick();
    expect(state.open.value).toBe(false);
    expect(state.canExpand.value).toBe(false);
    expect(state.canLoadDetail.value).toBe(true);
    state.toggle();
    expect(state.open.value).toBe(false);
    props.toolDetailTarget = { ...props.tool };
    expect(state.detailOpen.value).toBe(true);
    props.toolDetailTarget = { ...props.tool, inspectionLocator: { ...props.tool.inspectionLocator!, turn_id: 'another-turn' } };
    expect(state.detailOpen.value).toBe(false);
    scope.stop();
  });

  it('keeps legacy and unavailable-detail output collapsible without reopening on updates', async () => {
    const scope = effectScope();
    const props = reactive({ tool: { id: 'tool', name: 'Edit', arg: '', status: 'ok', output: ['saved'], defaultExpanded: true } as ToolCall,
      toolDiffPanel: true, toolDetailAvailable: false });
    const state = scope.run(() => useToolPresentation(props, 'fileChange', computed(() => true)))!;
    expect(state.canLoadDetail.value).toBe(false);
    expect(state.open.value).toBe(true);
    state.toggle();
    props.tool = { ...props.tool, output: ['updated'], inspectionLocator: { turn_id: 't', item_id: 'i', kind: 'fileChange', change_index: 0 } };
    await nextTick();
    expect(state.open.value).toBe(false);
    state.toggle();
    expect(state.open.value).toBe(true);
    scope.stop();
  });
});
