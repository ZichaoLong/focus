import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import type { ChatTurn, ToolCall, TurnBlock } from '../src/types';
import {
  assistantRenderBlocks,
  createToolGroupExpansionState,
  formatDuration,
  formatTokens,
  rendersToolCard,
  renderBlockKey,
  toolStackPosition,
  turnBlocks,
  turnFinalText,
} from '../src/components/chatTurnRendering';

function tool(id: string, over: Partial<ToolCall> = {}): ToolCall {
  return { id, name: 'read', arg: `· ${id}.ts`, status: 'ok', ...over };
}

function toolBlock(id: string, over: Partial<ToolCall> = {}): Extract<TurnBlock, { kind: 'tool' }> {
  return { kind: 'tool', tool: tool(id, over) };
}

function assistantTurn(blocks: TurnBlock[], over: Partial<ChatTurn> = {}): ChatTurn {
  return { id: 't1', role: 'assistant', no: 1, text: '', blocks, ...over };
}

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

describe('formatTokens', () => {
  it('keeps counts under 1024 verbatim and uses 1024-based k / M units', () => {
    expect(formatTokens(0)).toBe('0');
    expect(formatTokens(999)).toBe('999');
    expect(formatTokens(1000)).toBe('1000');
    expect(formatTokens(1500)).toBe('1.5k');
    expect(formatTokens(1_000_000)).toBe('977k');
    expect(formatTokens(2_500_000)).toBe('2.4M');
  });
});

describe('formatDuration', () => {
  it('switches units at the 1s and 1m boundaries', () => {
    expect(formatDuration(999)).toBe('999ms');
    expect(formatDuration(1000)).toBe('1.0s');
    expect(formatDuration(59_999)).toBe('60.0s');
    expect(formatDuration(60_000)).toBe('1m0.0s');
    expect(formatDuration(90_500)).toBe('1m30.5s');
  });
});

describe('turnBlocks', () => {
  it('returns the ordered blocks as-is when present', () => {
    const blocks: TurnBlock[] = [{ kind: 'text', text: 'hi' }];
    expect(turnBlocks(assistantTurn(blocks))).toBe(blocks);
  });

  it('falls back to thinking -> text -> tools order when blocks are absent', () => {
    const turn: ChatTurn = {
      id: 't1',
      role: 'assistant',
      no: 1,
      text: 'answer',
      thinking: 'plan',
      tools: [tool('a')],
    };
    expect(turnBlocks(turn)).toEqual([
      { kind: 'thinking', thinking: 'plan' },
      { kind: 'text', text: 'answer' },
      { kind: 'tool', tool: tool('a') },
    ]);
  });
});

describe('rendersToolCard', () => {
  it('hides the card only for a successful tool that carries inline media', () => {
    expect(rendersToolCard(toolBlock('a'))).toBe(true);
    expect(rendersToolCard(toolBlock('r', { status: 'running' }))).toBe(true);
    expect(
      rendersToolCard(toolBlock('m', { status: 'ok', media: { kind: 'image', url: 'x' } })),
    ).toBe(false);
    // media but errored -> still rendered as a card
    expect(
      rendersToolCard(toolBlock('e', { status: 'error', media: { kind: 'image', url: 'x' } })),
    ).toBe(true);
  });
});

describe('toolStackPosition', () => {
  it('marks a lone tool single and otherwise reports first/middle/last', () => {
    expect(toolStackPosition(0, 1)).toBe('single');
    expect(toolStackPosition(0, 0)).toBe('single');
    expect(toolStackPosition(0, 3)).toBe('first');
    expect(toolStackPosition(1, 3)).toBe('middle');
    expect(toolStackPosition(2, 3)).toBe('last');
  });
});

describe('assistantRenderBlocks', () => {
  it('groups consecutive renderable tools into one open tool-stack', () => {
    const rendered = assistantRenderBlocks(assistantTurn([toolBlock('a'), toolBlock('b')]));
    expect(rendered).toHaveLength(1);
    expect(rendered[0]).toMatchObject({ kind: 'tool-stack', collapsedByDefault: false });
    if (rendered[0]?.kind === 'tool-stack') {
      expect(rendered[0].tools.map((t) => t.tool.id)).toEqual(['a', 'b']);
      expect(rendered[0].tools.map((t) => t.sourceIndex)).toEqual([0, 1]);
    }
  });

  it('renders a lone tool without a later reply as a standalone tool', () => {
    const rendered = assistantRenderBlocks(assistantTurn([toolBlock('a')]));
    expect(rendered).toEqual([{ kind: 'tool', tool: tool('a'), sourceIndex: 0 }]);
  });

  it('collapses the preceding tool and leaves the tool after the latest reply open', () => {
    const rendered = assistantRenderBlocks(
      assistantTurn([toolBlock('a'), { kind: 'text', text: 'x' }, toolBlock('b')]),
    );
    expect(rendered.map((b) => b.kind)).toEqual([
      'tool-stack',
      'reply-separator',
      'text',
      'tool',
    ]);
    expect(rendered[0]).toMatchObject({ collapsedByDefault: true });
    expect(rendered[3]).toEqual({ kind: 'tool', tool: tool('b'), sourceIndex: 2 });
  });

  it('breaks the stack when a media tool (no card) interrupts the run', () => {
    const rendered = assistantRenderBlocks(
      assistantTurn([
        toolBlock('a'),
        toolBlock('b'),
        toolBlock('c', { status: 'ok', media: { kind: 'image', url: 'x' } }),
      ]),
    );
    expect(rendered.map((b) => b.kind)).toEqual(['tool-stack', 'tool']);
    if (rendered[0]?.kind === 'tool-stack') {
      expect(rendered[0].tools.map((t) => t.tool.id)).toEqual(['a', 'b']);
      expect(rendered[0].collapsedByDefault).toBe(false);
    }
  });

  it('separates the next non-empty reply after non-empty thinking', () => {
    const rendered = assistantRenderBlocks(
      assistantTurn([
        { kind: 'thinking', thinking: 'plan' },
        { kind: 'text', text: 'answer' },
      ]),
    );
    expect(rendered).toEqual([
      { kind: 'thinking', thinking: 'plan', sourceIndex: 0 },
      { kind: 'reply-separator', sourceIndex: 1 },
      { kind: 'text', text: 'answer', sourceIndex: 1 },
    ]);
  });

  it('keeps thinking on the work side of a tool-to-reply boundary', () => {
    const rendered = assistantRenderBlocks(
      assistantTurn([
        toolBlock('a'),
        { kind: 'thinking', thinking: 'checking result' },
        { kind: 'text', text: 'answer' },
      ]),
    );

    expect(rendered.map((block) => block.kind)).toEqual([
      'tool-stack',
      'thinking',
      'reply-separator',
      'text',
    ]);
    expect(rendered[0]).toMatchObject({ collapsedByDefault: true });
  });

  it('does not insert a boundary for empty work, pure text, or tool-only turns', () => {
    expect(assistantRenderBlocks(assistantTurn([
      { kind: 'thinking', thinking: '  \n ' },
      { kind: 'text', text: '' },
      { kind: 'text', text: 'answer' },
    ])).map((block) => block.kind)).toEqual(['thinking', 'text', 'text']);

    expect(assistantRenderBlocks(assistantTurn([
      { kind: 'text', text: 'answer' },
    ])).map((block) => block.kind)).toEqual(['text']);

    expect(assistantRenderBlocks(assistantTurn([
      toolBlock('a'),
    ])).map((block) => block.kind)).toEqual(['tool']);
  });

  it('does not let empty text split a pending tool run or consume its reply boundary', () => {
    const rendered = assistantRenderBlocks(assistantTurn([
      toolBlock('a'),
      { kind: 'text', text: ' \n ' },
      { kind: 'text', text: 'answer' },
    ]));

    expect(rendered.map((block) => block.kind)).toEqual([
      'tool-stack',
      'text',
      'reply-separator',
      'text',
    ]);
    expect(rendered[0]).toMatchObject({ collapsedByDefault: true });
  });

  it('resets the boundary at each assistant turn and after each reply transition', () => {
    const first = assistantRenderBlocks(assistantTurn([
      toolBlock('a'),
    ]));
    const nextTurn = assistantRenderBlocks(assistantTurn([
      { kind: 'text', text: 'next turn reply' },
    ], { id: 't2' }));
    const repeated = assistantRenderBlocks(assistantTurn([
      { kind: 'text', text: 'first reply' },
      toolBlock('a'),
      { kind: 'text', text: 'second reply' },
      { kind: 'thinking', thinking: 'more work' },
      { kind: 'text', text: 'third reply' },
    ]));

    expect(first.map((block) => block.kind)).toEqual(['tool']);
    expect(nextTurn.map((block) => block.kind)).toEqual(['text']);
    expect(repeated.map((block) => block.kind)).toEqual([
      'text',
      'tool-stack',
      'reply-separator',
      'text',
      'thinking',
      'reply-separator',
      'text',
    ]);
  });

  it('treats an ungrouped media tool as visible work activity', () => {
    const rendered = assistantRenderBlocks(assistantTurn([
      toolBlock('image', { status: 'ok', media: { kind: 'image', url: '/image' } }),
      { kind: 'text', text: 'image ready' },
    ]));

    expect(rendered.map((block) => block.kind)).toEqual([
      'tool',
      'reply-separator',
      'text',
    ]);
  });

  it('groups across empty placeholders while preserving their source order', () => {
    const rendered = assistantRenderBlocks(assistantTurn([
      toolBlock('a'),
      { kind: 'thinking', itemId: 'reasoning', thinking: '' },
      { kind: 'text', itemId: 'message', text: ' \n ' },
      toolBlock('b'),
    ]));

    expect(rendered.map((block) => block.kind)).toEqual(['tool-stack', 'thinking', 'text']);
    if (rendered[0]?.kind === 'tool-stack') {
      expect(rendered[0].tools.map((item) => item.tool.id)).toEqual(['a', 'b']);
      expect(rendered[0].tools.map((item) => item.sourceIndex)).toEqual([0, 3]);
      expect(rendered[0].collapsedByDefault).toBe(false);
    }
    expect(rendered[1]).toMatchObject({ sourceIndex: 1 });
    expect(rendered[2]).toMatchObject({ sourceIndex: 2 });
  });

  it('splits the same run again when a placeholder gains visible thinking', () => {
    const rendered = assistantRenderBlocks(assistantTurn([
      toolBlock('a'),
      { kind: 'thinking', itemId: 'reasoning', thinking: 'inspect the result' },
      toolBlock('b'),
    ]));

    expect(rendered.map((block) => block.kind)).toEqual(['tool', 'thinking', 'tool']);
  });

  it('collapses every tool run before the latest reply without changing tool data', () => {
    const rendered = assistantRenderBlocks(assistantTurn([
      toolBlock('a'),
      toolBlock('b'),
      { kind: 'text', text: 'first reply' },
      toolBlock('c'),
      { kind: 'thinking', thinking: 'checking' },
      toolBlock('d'),
      { kind: 'text', text: 'second reply' },
      toolBlock('e'),
    ]));

    expect(rendered.map((block) => block.kind)).toEqual([
      'tool-stack',
      'reply-separator',
      'text',
      'tool-stack',
      'thinking',
      'tool-stack',
      'reply-separator',
      'text',
      'tool',
    ]);
    const stacks = rendered.filter((block) => block.kind === 'tool-stack');
    expect(stacks.map((block) => block.collapsedByDefault)).toEqual([true, true, true]);
    expect(stacks.flatMap((block) => block.tools.map((item) => item.tool.id))).toEqual(['a', 'b', 'c', 'd']);
    expect(stacks.flatMap((block) => block.tools.map((item) => item.sourceIndex))).toEqual([0, 1, 3, 5]);
    expect(rendered.at(-1)).toEqual({ kind: 'tool', tool: tool('e'), sourceIndex: 7 });
  });
});

describe('assistant reply separator surface', () => {
  it('renders the derived boundary as one unlabeled separator line', () => {
    const chatPane = source('../src/components/chat/ChatPane.vue');
    const separator = chatPane.match(
      /<div\s+v-else-if="blk\.kind === 'reply-separator'"\s+class="assistant-reply-separator"\s+role="separator"\s*\/>/,
    );

    expect(separator?.[0]).toBeDefined();
    expect(separator?.[0]).not.toContain('{{');
    expect(chatPane).toContain('.assistant-reply-separator {');
    expect(chatPane).toMatch(
      /\.assistant-reply-separator \{[\s\S]*?width:\s*100%;[\s\S]*?height:\s*2px;[\s\S]*?background:\s*var\(--color-line-strong\);[\s\S]*?\}/u,
    );
  });
});

describe('turnFinalText', () => {
  it('joins only the text blocks, dropping thinking and tools', () => {
    const turn = assistantTurn([
      { kind: 'thinking', thinking: 'plan' },
      { kind: 'text', text: 'first' },
      toolBlock('a'),
      { kind: 'text', text: 'second' },
    ]);
    expect(turnFinalText(turn)).toBe('first\n\nsecond');
  });
});

describe('renderBlockKey', () => {
  it('derives stable keys per block kind and across the collapse transition', () => {
    expect(renderBlockKey({ kind: 'text', text: 'x', sourceIndex: 2 }, 0)).toBe('text-2');
    expect(renderBlockKey({ kind: 'reply-separator', sourceIndex: 2 }, 0)).toBe(
      'reply-separator-2',
    );
    expect(renderBlockKey({ kind: 'tool', tool: tool('a'), sourceIndex: 3 }, 0)).toBe('a');
    const tools = [{ tool: tool('a'), sourceIndex: 5 }];
    expect(
      renderBlockKey({ kind: 'tool-stack', tools, collapsedByDefault: false }, 0),
    ).toBe('tool-stack-5');
    expect(
      renderBlockKey({ kind: 'tool-stack', tools, collapsedByDefault: true }, 0),
    ).toBe('tool-stack-5');
  });
});

describe('tool group expansion state', () => {
  it('keeps manual expansion through updates and clears it only after turn eviction', () => {
    const turn = assistantTurn([toolBlock('a'), { kind: 'text', text: 'answer' }]);
    const block = assistantRenderBlocks(turn)[0];
    if (block?.kind !== 'tool-stack') throw new Error('expected a collapsed tool stack');
    const state = createToolGroupExpansionState();

    expect(state.isOpen(turn, block, 0)).toBe(false);
    expect(state.toggle(turn, block, 0)).toBe(true);
    state.prune([turn]);
    expect(state.isOpen(turn, block, 0)).toBe(true);
    state.prune([]);
    expect(state.isOpen(turn, block, 0)).toBe(false);
  });

  it('does not reopen a manually collapsed group when its automatic default changes', () => {
    const activeTurn = assistantTurn([toolBlock('a'), toolBlock('b')]);
    const activeBlock = assistantRenderBlocks(activeTurn)[0];
    if (activeBlock?.kind !== 'tool-stack') throw new Error('expected an open tool stack');
    const state = createToolGroupExpansionState();
    expect(state.toggle(activeTurn, activeBlock, 0)).toBe(false);

    const sealedTurn = assistantTurn([
      toolBlock('a'),
      toolBlock('b'),
      { kind: 'text', text: 'answer' },
    ]);
    const sealedBlock = assistantRenderBlocks(sealedTurn)[0];
    if (sealedBlock?.kind !== 'tool-stack') throw new Error('expected a sealed tool stack');
    expect(sealedBlock.collapsedByDefault).toBe(true);
    expect(state.isOpen(sealedTurn, sealedBlock, 0)).toBe(false);
  });
});
