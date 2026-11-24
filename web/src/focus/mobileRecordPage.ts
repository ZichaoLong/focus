import type { ChatTurn } from '../types';
import { isEmptyAssistantTurn } from '../components/toolGroupPresentation';

export interface RecordItem {
  turn: string; item: string; kind: 'tool' | 'break' | 'user' | 'assistant'; text?: string; partial?: boolean;
}
export interface RecordPage {
  version: 1; mark: string; oldest: [string,string] | null; thread: string; epoch: string; scope: string; older: string | null; rows: RecordItem[];
}
export interface ToolCount {
  kind: 'tools'; v: 1; turn: string; first: string; last: string; count: number; hash: string;
}

export function decodeRecordPage(value: unknown): RecordPage | null {
  const p = value as RecordPage | null;
  if (p?.version !== 1 || typeof p.thread !== 'string' || typeof p.epoch !== 'string'
    || typeof p.mark !== 'string' || !new RegExp('^[a-f0-9]{64}$').test(p.scope)
    || !(p.oldest === null || Array.isArray(p.oldest) && p.oldest.length === 2 && p.oldest.every(id => typeof id === 'string' && id))
    || !(p.older === null || typeof p.older === 'string') || !Array.isArray(p.rows)) return null;
  const rows: RecordItem[] = [];
  for (const row of p.rows) {
    if (!row || typeof row.turn !== 'string' || !row.turn || typeof row.item !== 'string' || !row.item) return null;
    const {kind,turn,item} = row;
    if (kind === 'tool' || kind === 'break') rows.push({kind,turn,item});
    else if ((kind === 'user' || kind === 'assistant') && typeof row.text === 'string' && typeof row.partial === 'boolean')
      rows.push({kind,turn,item,text:row.text,partial:row.partial});
    else return null;
  }
  return {...p,rows};
}

export async function recordHash(text: string): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2,'0')).join('');
}

/** Digest in reverse chronological order so a run can extend across older pages in O(1) space. */
export async function foldRecordPage(items: readonly RecordItem[], edge: ToolCount | null) {
  const body: (RecordItem | ToolCount)[] = [];
  for (let i = items.length - 1; i >= 0; i--) {
    const row = items[i]!;
    if (edge && (row.kind !== 'tool' || row.turn !== edge.turn)) { body.push(edge); edge = null; }
    if (row.kind === 'tool') {
      const hash = await recordHash(JSON.stringify([1,row.turn,row.item,edge?.hash ?? '']));
      edge = {kind:'tools', v:1, turn:row.turn, first:row.item, last:edge?.last ?? row.item, count:(edge?.count ?? 0)+1, hash};
    } else if (row.kind !== 'break') body.push(row);
  }
  return { body, edge };
}

export function classifyRecordTurn(row: ChatTurn): RecordItem | null {
  if (!row.rawTurnId || !row.itemId) return null;
  const key = { turn:row.rawTurnId, item:row.itemId };
  if (row.compactTool || (row.contentDeferred && row.tools?.length)) return { ...key, kind:'tool' };
  if ((row.role === 'user' || row.role === 'assistant') && row.text.trim()) {
    return { ...key, kind:row.role, text:row.text, partial:row.reply?.state === 'generating' };
  }
  return isEmptyAssistantTurn(row) ? null : { ...key, kind:'break' };
}
