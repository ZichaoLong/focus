import { describe, expect, it } from 'vitest';
import type { ToolCall } from '../src/types';
import { isFocusWireToolCall } from '../src/focus/projectionEventDecoder';
import { toolOutputWindowFitsAggregate } from '../src/focus/toolOutputPresentation';

describe('deferred tool output admission', () => {
  const tool: ToolCall = { id: 'cmd', name: 'Shell', arg: 'echo', status: 'ok', output: [], outputDeferred: true,
    inspectionLocator: { turn_id: 't', item_id: 'cmd', kind: 'commandExecution', change_index: null } };
  it('requires an exact terminal empty marker without truncation or diff content', () => {
    expect(isFocusWireToolCall(tool)).toBe(true);
    for (const change of [{ output: ['leaked'] }, { status: 'running' }, { inspectionLocator: undefined },
      { outputDeferred: false }, { diff: { lines: [] } }, { outputTruncated: false }, { outputOmittedChars: 1 }]) {
      expect(isFocusWireToolCall({ ...tool, ...change })).toBe(false);
    }
  });
  it('requires the same deferral fact in tools and block mirrors', () => {
    const turn = { id: 't:assistant', role: 'assistant' as const, no: 1, text: '', tools: [tool],
      blocks: [{ kind: 'tool' as const, tool }] };
    expect(toolOutputWindowFitsAggregate([turn])).toBe(true);
    const { outputDeferred: _deferred, ...nonDeferred } = tool;
    expect(toolOutputWindowFitsAggregate([{ ...turn, tools: [nonDeferred] }])).toBe(false);
  });
});
