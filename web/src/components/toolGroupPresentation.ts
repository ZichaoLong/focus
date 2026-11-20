import type { ChatTurn, ToolCall } from '../types';

/** Browser-local presentation only; see the Focus Web transcript-window contract. */
export interface ToolGroup {
  readonly members: readonly string[];
  readonly collapsedByDefault: boolean;
}

export interface TranscriptToolGroup extends ToolGroup {
  readonly sourceIds: readonly string[];
  readonly tools: readonly ToolCall[];
}

export function toolGroupMember(turnId: string, toolId?: string): string {
  return JSON.stringify([turnId, toolId ?? null]);
}

export interface TranscriptToolGroups {
  readonly leaders: ReadonlyMap<string, TranscriptToolGroup>;
  readonly members: ReadonlyMap<string, TranscriptToolGroup>;
}

/** Empty stream targets keep their identity without taking up transcript space. */
export function isEmptyAssistantTurn(turn: ChatTurn): boolean {
  return turn.role === 'assistant' && !turn.tools?.length && (turn.blocks
    ? turn.blocks.every(block => (block.kind === 'text' && !block.text.trim())
      || (block.kind === 'thinking' && !block.thinking.trim()))
    : !turn.text.trim() && !turn.thinking?.trim());
}

/** Annotate source rows without replacing, reparenting, or copying their content. */
export function projectTranscriptToolGroups(turns: readonly ChatTurn[]): TranscriptToolGroups {
  const leaders = new Map<string, TranscriptToolGroup>();
  const members = new Map<string, TranscriptToolGroup>();
  let run: ChatTurn[] = [];
  const flush = () => {
    const first = run[0];
    if (first) {
      const group: TranscriptToolGroup = {
        sourceIds: run.map(turn => turn.id),
        members: run.map(turn => toolGroupMember(turn.id)),
        tools: run.flatMap(turn => turn.tools ?? []),
        collapsedByDefault: true,
      };
      leaders.set(first.id, group);
      for (const turn of run) members.set(turn.id, group);
    }
    run = [];
  };

  turns.forEach(turn => {
    if (run.length && run[0]!.rawTurnId !== turn.rawTurnId) flush();
    if (turn.role === 'assistant' && turn.contentDeferred && turn.tools?.length) {
      run.push(turn);
    } else if (!isEmptyAssistantTurn(turn)) {
      flush();
    }
  });
  flush();
  return { leaders, members };
}

interface ExpansionChoice { readonly open: boolean; readonly sequence: number }

/** One bounded owner for explicit choices, including groups split or joined by paging. */
export function createToolGroupExpansion() {
  const choices = new Map<string, ExpansionChoice>();
  let sequence = 0;

  function choice(group: ToolGroup): ExpansionChoice | undefined {
    let latest: ExpansionChoice | undefined;
    for (const member of group.members) {
      const candidate = choices.get(member);
      if (candidate && (!latest || candidate.sequence > latest.sequence)) latest = candidate;
    }
    return latest;
  }

  function isOpen(group: ToolGroup): boolean {
    return choice(group)?.open ?? !group.collapsedByDefault;
  }

  function retain(member: string, selected: ExpansionChoice): void {
    if (choices.get(member) === selected) return;
    choices.delete(member);
    choices.set(member, selected);
    if (choices.size > 2048) choices.delete(choices.keys().next().value!);
  }

  function setOpen(group: ToolGroup, open: boolean): void {
    const selected = { open, sequence: ++sequence };
    for (const member of group.members) retain(member, selected);
  }

  return {
    isOpen,
    hasChoice(group: ToolGroup): boolean { return choice(group) !== undefined; },
    setOpen,
    toggle(group: ToolGroup): void { setOpen(group, !isOpen(group)); },
    reconcile(groups: readonly ToolGroup[]): void {
      // Inherit the latest user choice before an older page/leader can be evicted.
      for (const group of groups) {
        const selected = choice(group);
        if (selected) for (const member of group.members) retain(member, selected);
      }
    },
  };
}

// Web documents are isolated per instance/tab. Retain just explicit choices when
// Vue replaces the thread component. Reload starts with an empty map.
const byThread = new Map<string, ReturnType<typeof createToolGroupExpansion>>();
export function trimThreadToolExpansion(limit: number): void {
  while (byThread.size > limit) byThread.delete(byThread.keys().next().value!);
}
export function threadToolExpansion(thread: string, limit: number) {
  const expansion = byThread.get(thread) ?? createToolGroupExpansion();
  byThread.delete(thread);
  byThread.set(thread, expansion);
  trimThreadToolExpansion(limit);
  return expansion;
}
