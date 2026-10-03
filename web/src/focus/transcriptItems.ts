import type { ChatTurn, TurnBlock } from '../types';
import type { FocusStreamDelta } from './types';
import { appendBoundedToolOutput } from './toolOutputPresentation';

export const TRANSCRIPT_WINDOW_ITEMS = 80;

/** Apply one ordered delta to one bounded item, without scanning a whole turn. */
export function appendTranscriptDelta(previous: ChatTurn | undefined, stream: FocusStreamDelta): ChatTurn | null {
  const reply = stream.kind === 'text' ? { ...previous?.reply,
    state: previous?.reply?.state === 'complete' ? 'complete' as const : 'generating' as const } : previous?.reply;
  if (previous?.contentDeferred) return reply === previous.reply ? previous : { ...previous, reply };
  if (!previous && stream.kind === 'tool_output') return null;
  const turn: ChatTurn = previous ?? {
    id: `${stream.turn_id}:item:${stream.item_id}:0`,
    rawTurnId: stream.turn_id, itemId: stream.item_id,
    role: 'assistant', no: 0, text: '', blocks: [], status: 'inProgress',
    ...(reply ? { reply } : {}),
  };
  const blocks = [...(turn.blocks ?? [])];
  const tools = [...(turn.tools ?? [])];
  if (stream.kind === 'tool_output') {
    const index = tools.findIndex((tool) => tool.id === stream.item_id);
    const tool = tools[index];
    if (!tool || tool.outputDeferred) return turn;
    const output = appendBoundedToolOutput(tool.output ?? [], stream.delta,
      tool.outputOmittedChars ?? 0, tool.outputHeadLineCount ?? 0);
    const updated = { ...tool, output: output.lines,
      ...(output.omittedChars > 0 ? {
        outputTruncated: true, outputOmittedChars: output.omittedChars,
        outputHeadLineCount: output.headLineCount,
      } : {}),
    };
    tools[index] = updated;
    const blockIndex = blocks.findIndex((block) => block.kind === 'tool' && block.tool.id === tool.id);
    if (blockIndex >= 0) blocks[blockIndex] = { kind: 'tool', tool: updated };
  } else {
    const thinking = stream.kind === 'thinking' || stream.kind === 'thinking_separator';
    const kind = thinking ? 'thinking' : 'text';
    const index = blocks.findIndex((block) => block.kind === kind && block.itemId === stream.item_id);
    const old = blocks[index];
    const text = (old?.kind === 'text' ? old.text : old?.kind === 'thinking' ? old.thinking : '')
      + (stream.kind === 'thinking_separator' ? '\n\n' : stream.delta);
    const block: TurnBlock = thinking
      ? { kind: 'thinking', itemId: stream.item_id, thinking: text }
      : { kind: 'text', itemId: stream.item_id, text, reply };
    if (index < 0) blocks.push(block);
    else blocks[index] = block;
  }
  return { ...turn, blocks, tools, status: 'inProgress',
    ...(reply ? { reply } : {}),
    text: blocks.flatMap((block) => block.kind === 'text' ? [block.text] : []).join('\n\n'),
  };
}
