import { describe, expect, it } from 'vitest';
import type { ChatTurn } from '../src/types';
import { createToolGroupExpansion, projectTranscriptToolGroups, toolGroupMember, type ToolGroup } from '../src/components/toolGroupPresentation';

function tool(id: string, rawTurnId = 'turn'): ChatTurn {
  const value = { id, name: 'Shell', arg: `echo ${id}`, status: 'ok' as const };
  return { id: `${rawTurnId}:item:${id}:0`, rawTurnId, itemId: id, role: 'assistant', no: 0,
    text: '', contentDeferred: true, tools: [value], blocks: [{ kind: 'tool', tool: value }] };
}
function prose(id: string, text: string, kind: 'text' | 'thinking' = 'text'): ChatTurn {
  return { id: `turn:item:${id}:0`, rawTurnId: 'turn', itemId: id, role: 'assistant', no: 0,
    text: kind === 'text' ? text : '', blocks: [kind === 'text' ? { kind, text } : { kind, thinking: text }] };
}
function group(members: string[], collapsedByDefault = true): ToolGroup { return { members, collapsedByDefault }; }

describe('transcript tool group presentation', () => {
  it('annotates independent source rows and seals them only after visible replies', () => {
    const rows = [tool('a'), prose('empty', '', 'thinking'), tool('b')];
    const initial = projectTranscriptToolGroups(rows);
    const value = initial.leaders.get(rows[0]!.id)!;
    expect(value.collapsedByDefault).toBe(false);
    expect(value.sourceIds).toEqual([rows[0]!.id, rows[2]!.id]);
    expect(value.tools).toEqual([rows[0]!.tools![0], rows[2]!.tools![0]]);
    expect(initial.members.get(rows[2]!.id)).toBe(value);
    expect(rows).toHaveLength(3);
    const sealed = projectTranscriptToolGroups([...rows, prose('reply', 'Done'), tool('c')]);
    expect(sealed.leaders.get(rows[0]!.id)?.collapsedByDefault).toBe(true);
    expect(sealed.members.has(tool('c').id)).toBe(false);
  });

  it('keeps lone completed tools foldable and does not group across source-turn boundaries', () => {
    const a = tool('a'); const b = tool('b', 'next');
    const result = projectTranscriptToolGroups([a, b, prose('reply', 'Done')]);
    expect([...result.leaders.keys()]).toEqual([a.id, b.id]);
    expect(result.leaders.get(a.id)?.sourceIds).toEqual([a.id]);
  });

  it('splits at user messages and visible reasoning, including newly filled placeholders', () => {
    const a = tool('a'); const b = tool('b');
    for (const boundary of [prose('reasoning', 'Checking', 'thinking'), { ...prose('user', 'Continue'), role: 'user' as const }]) {
      const result = projectTranscriptToolGroups([a, boundary, b, prose('reply', 'Done')]);
      expect([...result.leaders.values()].map(value => value.sourceIds)).toEqual([[a.id], [b.id]]);
    }
  });
});

describe('bounded tool group expansion choices', () => {
  it('inherits explicit expansion through prepend, leader eviction, and a subsequent split', () => {
    const state = createToolGroupExpansion();
    const bc = group(['b', 'c']);
    expect(state.isOpen(bc)).toBe(false);
    state.toggle(bc);
    const abc = group(['a', 'b', 'c']);
    state.reconcile([abc], new Set(abc.members));
    expect(state.isOpen(abc)).toBe(true);
    const ac = group(['a', 'c']);
    state.reconcile([ac], new Set(ac.members));
    state.reconcile([group(['a']), group(['c'])], new Set(ac.members));
    expect(state.isOpen(group(['a']))).toBe(true);
    expect(state.isOpen(group(['c']))).toBe(true);
    state.reconcile([], new Set());
    expect(state.isOpen(abc)).toBe(false);
  });

  it('uses the latest explicit choice when differently toggled runs join', () => {
    const state = createToolGroupExpansion();
    state.setOpen(group(['a']), true);
    state.setOpen(group(['b']), false);
    const both = group(['a', 'b'], false);
    state.reconcile([both], new Set(both.members));
    expect(state.isOpen(both)).toBe(false);
    state.reconcile([group(['a']), group(['b'])], new Set(both.members));
    expect(state.isOpen(group(['a'], false))).toBe(false);
  });

  it('keeps manual intent when the automatic default changes, without retaining evicted rows', () => {
    const state = createToolGroupExpansion();
    const current = group(['a'], false);
    state.toggle(current);
    expect(state.isOpen(group(['a'], true))).toBe(false);
    state.reconcile([], new Set(['b']));
    expect(state.isOpen(current)).toBe(true);
  });

  it('separates legacy block identity from paginated row identity and ambiguous strings', () => {
    expect(toolGroupMember('a', 'b')).not.toBe(toolGroupMember('a:b'));
    expect(toolGroupMember('a', 'b:c')).not.toBe(toolGroupMember('a:b', 'c'));
  });
});
