// apps/kimi-web/src/components/chatTurnRendering.ts
// Pure turn-rendering helpers, independent of Vue and component lifetimes.
import type { ChatTurn, ReplyMetadata, TurnBlock } from '../types';

// Shared 1024-based token formatter (lib/formatTokens); re-exported so the
// existing ChatPane import keeps working.
export { formatTokens } from '../lib/formatTokens';

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = ((ms % 60_000) / 1000).toFixed(1);
  return `${m}m${s}s`;
}

// Ordered render blocks for an assistant turn. The Focus projection supplies
// `blocks` (thinking + text + tool cards in call order); fall back to deriving
// them from aggregate fields for any turn built without blocks (e.g. unit tests).
export function turnBlocks(turn: ChatTurn): TurnBlock[] {
  if (turn.blocks) return turn.blocks;
  const blocks: TurnBlock[] = [];
  if (turn.thinking) blocks.push({ kind: 'thinking', thinking: turn.thinking });
  if (turn.text) blocks.push({ kind: 'text', text: turn.text });
  for (const tool of turn.tools ?? []) blocks.push({ kind: 'tool', tool });
  return blocks;
}

export type ToolStackPosition = 'single' | 'first' | 'middle' | 'last';

export type ToolStackItem = {
  tool: Extract<TurnBlock, { kind: 'tool' }>['tool'];
  sourceIndex: number;
};

export type AssistantRenderBlock =
  | { kind: 'thinking'; thinking: string; sourceIndex: number }
  | { kind: 'text'; text: string; sourceIndex: number; reply?: ReplyMetadata }
  | { kind: 'reply-separator'; sourceIndex: number }
  | { kind: 'tool'; tool: ToolStackItem['tool']; sourceIndex: number }
  | { kind: 'tool-stack'; tools: ToolStackItem[]; collapsedByDefault: boolean };

export function rendersToolCard(block: Extract<TurnBlock, { kind: 'tool' }>): boolean {
  return !(block.tool.status === 'ok' && block.tool.media);
}

export function toolStackPosition(index: number, count: number): ToolStackPosition {
  if (count <= 1) return 'single';
  if (index === 0) return 'first';
  if (index === count - 1) return 'last';
  return 'middle';
}

export function assistantRenderBlocks(turn: ChatTurn): AssistantRenderBlock[] {
  const blocks = turnBlocks(turn);
  const rendered: AssistantRenderBlock[] = [];
  let toolRun: ToolStackItem[] = [];
  let emptyBlocks: AssistantRenderBlock[] = [];
  let hasPendingWorkActivity = false;
  let lastReplyIndex = -1;
  blocks.forEach((block, sourceIndex) => {
    if (block.kind === 'text' && block.text.trim().length > 0) lastReplyIndex = sourceIndex;
  });

  const flushToolRun = () => {
    const [first] = toolRun;
    if (first) {
      const collapsedByDefault = first.sourceIndex < lastReplyIndex;
      if (toolRun.length === 1 && !collapsedByDefault) {
        rendered.push({ kind: 'tool', tool: first.tool, sourceIndex: first.sourceIndex });
      } else {
        rendered.push({ kind: 'tool-stack', tools: toolRun, collapsedByDefault });
      }
    }
    toolRun = [];
    rendered.push(...emptyBlocks);
    emptyBlocks = [];
  };

  blocks.forEach((block, sourceIndex) => {
    if (block.kind === 'tool') {
      // Every admitted tool block has a visible ToolCall presentation. Media
      // tools render outside a grouped card, but still count as work activity.
      hasPendingWorkActivity = true;
      if (rendersToolCard(block)) {
        toolRun.push({ tool: block.tool, sourceIndex });
        return;
      }
      flushToolRun();
      rendered.push({ kind: 'tool', tool: block.tool, sourceIndex });
      return;
    }

    if (block.kind === 'thinking') {
      if (block.thinking.trim().length > 0) {
        flushToolRun();
        hasPendingWorkActivity = true;
        rendered.push({ kind: 'thinking', thinking: block.thinking, sourceIndex });
      } else {
        emptyBlocks.push({ kind: 'thinking', thinking: block.thinking, sourceIndex });
      }
      return;
    }

    const hasReply = block.text.trim().length > 0;
    if (hasReply) {
      flushToolRun();
      if (hasPendingWorkActivity) {
        rendered.push({ kind: 'reply-separator', sourceIndex });
        hasPendingWorkActivity = false;
      }
      rendered.push({ kind: 'text', text: block.text, sourceIndex, ...(block.reply ? { reply: block.reply } : {}) });
    } else {
      emptyBlocks.push({ kind: 'text', text: block.text, sourceIndex, ...(block.reply ? { reply: block.reply } : {}) });
    }
  });

  flushToolRun();
  return rendered;
}

export function turnFinalText(turn: ChatTurn): string {
  return turnBlocks(turn)
    .flatMap((blk) => (blk.kind === 'text' && blk.text ? [blk.text] : []))
    .join('\n\n');
}

export function toolStackKey(item: ToolStackItem): string {
  return item.tool.id || `tool-${item.sourceIndex}`;
}

export function renderBlockKey(block: AssistantRenderBlock, index: number): string {
  if (block.kind === 'tool-stack') {
    return `tool-stack-${block.tools[0]?.sourceIndex ?? index}`;
  }
  if (block.kind === 'tool') return toolStackKey({ tool: block.tool, sourceIndex: block.sourceIndex });
  return `${block.kind}-${block.sourceIndex}`;
}
