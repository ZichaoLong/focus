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

/** Annotate source rows without replacing, reparenting, or copying their content. */
export function projectTranscriptToolGroups(turns: readonly ChatTurn[]): TranscriptToolGroups {
  const leaders = new Map<string, TranscriptToolGroup>();
  const members = new Map<string, TranscriptToolGroup>();
  let lastReply = -1;
  turns.forEach((turn, index) => {
    if (turn.role === 'assistant' && (turn.blocks
      ? turn.blocks.some(block => block.kind === 'text' && block.text.trim())
      : turn.text.trim())) lastReply = index;
  });

  let run: ChatTurn[] = [];
  let runStart = 0;
  const flush = () => {
    const first = run[0];
    if (first && (run.length > 1 || runStart < lastReply)) {
      const group: TranscriptToolGroup = {
        sourceIds: run.map(turn => turn.id),
        members: run.map(turn => toolGroupMember(turn.id)),
        tools: run.flatMap(turn => turn.tools ?? []),
        collapsedByDefault: runStart < lastReply,
      };
      leaders.set(first.id, group);
      for (const turn of run) members.set(turn.id, group);
    }
    run = [];
  };

  turns.forEach((turn, index) => {
    if (run.length && run[0]!.rawTurnId !== turn.rawTurnId) flush();
    if (turn.role === 'assistant' && turn.contentDeferred && turn.tools?.length) {
      if (!run.length) runStart = index;
      run.push(turn);
    } else if (!(turn.role === 'assistant' && (turn.blocks
      ? turn.blocks.every(block => (block.kind === 'text' && !block.text.trim())
        || (block.kind === 'thinking' && !block.thinking.trim()))
      : !turn.text.trim() && !turn.thinking?.trim() && !turn.tools?.length))) {
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

  function setOpen(group: ToolGroup, open: boolean): void {
    const selected = { open, sequence: ++sequence };
    for (const member of group.members) choices.set(member, selected);
  }

  return {
    isOpen,
    setOpen,
    toggle(group: ToolGroup): void { setOpen(group, !isOpen(group)); },
    reconcile(groups: readonly ToolGroup[], retainedMembers: ReadonlySet<string>): void {
      for (const member of choices.keys()) if (!retainedMembers.has(member)) choices.delete(member);
      // Inherit the latest user choice before an older page/leader can be evicted.
      for (const group of groups) {
        const selected = choice(group);
        if (selected) for (const member of group.members) choices.set(member, selected);
      }
    },
  };
}
