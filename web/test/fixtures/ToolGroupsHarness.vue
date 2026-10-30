<script setup lang="ts">
import { nextTick, provide, shallowRef } from 'vue';
import ConversationPane from '../../src/components/chat/ConversationPane.vue';
import { TranscriptPageWindow } from '../../src/focus/transcriptPageWindow';
import { appendTranscriptDelta } from '../../src/focus/transcriptItems';
import type { ChatTurn, ConversationStatus } from '../../src/types';
import type { FocusTranscriptPage } from '../../src/focus/types';

provide('resolveImage', async () => null);
const rows = shallowRef<ChatTurn[]>([]);
const cache = new TranscriptPageWindow();
const details: string[] = [];
let protectedRow: string | null = null;
const status: ConversationStatus = { model: '', modelId: '', ctxUsed: 0, ctxMax: 0,
  ctxRemainingPct: null, permission: 'manual', branch: '', cwd: '', isGitRepo: false };
function tool(id: string): ChatTurn {
  const value = { id, name: 'Shell', arg: `echo ${id}`, status: 'ok' as const, output: [],
    outputDeferred: true, inspectionLocator: { turn_id: 'turn', item_id: id, kind: 'commandExecution' as const, change_index: null } };
  return { id: `turn:item:${id}:0`, rawTurnId: 'turn', itemId: id, role: 'assistant', no: 0,
    text: '', contentDeferred: true, tools: [value], blocks: [{ kind: 'tool', tool: value }] };
}
function reply(id = 'reply', paragraphs = 18): ChatTurn {
  const text = Array.from({ length: paragraphs }, (_, index) => `${id} paragraph ${index}.`).join('\n\n');
  return { id: `turn:item:${id}:0`, rawTurnId: 'turn', itemId: id, role: 'assistant', no: 0,
    text, blocks: [{ kind: 'text', text }], reply: { state: 'complete' } };
}
function reasoning(text: string): ChatTurn {
  return { id: 'turn:item:reasoning:0', rawTurnId: 'turn', itemId: 'reasoning', role: 'assistant', no: 0,
    text: '', blocks: [{ kind: 'thinking', thinking: text }] };
}
function user(id: string, paragraphs = 18): ChatTurn { return { ...reply(id, paragraphs), role: 'user' }; }
function page(turns: ChatTurn[]): FocusTranscriptPage {
  return { runtime_epoch: 'epoch', revision: 1, thread_id: 'thread', turn_id: null,
    view: 'transcript', target_pending: false, full_text: null,
    older_cursor: 'older', newer_cursor: 'newer', turns };
}
function publish() { rows.value = cache.rows; }
async function reset(kind: 'working' | 'replied' | 'large' | 'split' | 'paged') {
  details.length = 0;
  protectedRow = null;
  if (kind === 'large') {
    cache.replace(page(Array.from({ length: 40 }, (_, index) => tool(`cmd-${index}`))), false);
    for (let start = 40; start < 200; start += 40) {
      cache.extend(page(Array.from({ length: 40 }, (_, index) => tool(`cmd-${start + index}`))), 'newer');
    }
    cache.extend(page([reply()]), 'newer');
  } else if (kind === 'split') {
    cache.replace(page([reply('older'), tool('b'), reasoning(''), tool('c'), user('tail')]), false);
  } else if (kind === 'paged') {
    cache.replace(page([reply('older'), tool('b')]), false);
    cache.extend(page([tool('c'), user('tail')]), 'newer');
    for (let index = 0; index < 8; index++) cache.extend(page([user(`later-${index}`, 1)]), 'newer');
  } else cache.replace(page([tool('b'), tool('c'), ...(kind === 'replied' ? [reply()] : [])]), false);
  publish();
  await nextTick();
}
Object.assign(window, { toolGroupFixture: {
  reset,
  async placeholders(kind: 'text' | 'thinking', text: string) {
    const next = cache.rows.filter(row => !row.itemId?.startsWith('empty-'));
    const placeholders: ChatTurn[] = Array.from({ length: 4 }, (_, index) => {
      const itemId = `empty-${index}`;
      return { id: `turn:item:${itemId}:0`, rawTurnId: 'turn', itemId, role: 'assistant', no: 0,
        text: kind === 'text' ? text : '',
        blocks: [kind === 'text' ? { kind, text, itemId } : { kind, thinking: text, itemId }],
        ...(kind === 'text' ? { reply: { state: 'generating' as const, startedAtMs: 1 } } : {}),
      };
    });
    next.splice(next.findIndex(row => row.itemId === 'c'), 0, ...placeholders);
    cache.update(next, 'newer', protectedRow); publish(); await nextTick();
  },
  async streamPlaceholder(kind: 'text' | 'thinking', delta: string) {
    const next = cache.rows.map(row => row.itemId === 'empty-0'
      ? appendTranscriptDelta(row, { kind, turn_id: 'turn', item_id: 'empty-0', delta })! : row);
    cache.update(next, 'newer', protectedRow); publish(); await nextTick();
  },
  async reasoning(text: string) {
    const next = cache.rows.filter(row => row.itemId !== 'reasoning');
    next.splice(next.findIndex(row => row.itemId === 'c'), 0, reasoning(text));
    cache.update(next, 'newer', protectedRow); publish(); await nextTick();
  },
  async evictFirstPage() {
    cache.extend(page([user('newest', 1)]), 'newer', protectedRow); publish(); await nextTick();
  },
  async navigateAway() { cache.replace(page([user('away')]), false); publish(); await nextTick(); },
  async revisitTool() { cache.replace(page([tool('c'), user('tail')]), false); publish(); await nextTick(); },
  async reply(paragraphs = 18) { cache.update([...cache.rows, reply('reply', paragraphs)], 'newer', protectedRow); publish(); await nextTick(); },
  async prepend() { cache.extend(page([reply('older'), tool('a'), tool('b')]), 'older', protectedRow); publish(); await nextTick(); },
  async evictOlder() {
    for (let index = 0; index < 7; index++) cache.extend(page([reply(`newer-${index}`, 1)]), 'newer', protectedRow);
    publish(); await nextTick();
  },
  get details() { return [...details]; },
  get protectedRow() { return protectedRow; },
} });
void reset('working');
</script>

<template>
  <ConversationPane :turns="rows" :tasks="[]" :status="status" session-id="fixture"
    :composer-ready="false" reading-mode reading-mode-enabled continuous-transcript
    :has-newer-messages="true"
    :update-transcript-viewport="(id, following) => { protectedRow = following ? null : id; }"
    @open-full-content="turn => details.push(turn.itemId!)" />
</template>
