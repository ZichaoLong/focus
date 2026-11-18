<script setup lang="ts">
import { provide, reactive, ref } from 'vue';
import ConversationPane from '../../src/components/chat/ConversationPane.vue';
import type { ChatTurn, ConversationStatus } from '../../src/types';

provide('resolveImage', async () => null);
const query = new URLSearchParams(window.location.search);
const status: ConversationStatus = { model: '', modelId: '', ctxUsed: 0, ctxMax: 0,
  ctxRemainingPct: null, permission: 'manual', branch: '', cwd: '', isGitRepo: false };
// The long variant also exercises Focus's nested Markdown chunk window.
const replyText = Array.from({ length: query.has('long') ? 200 : 48 }, (_, index) =>
  `History paragraph ${index + 1}.${query.has('long') ? ' A sentence for measuring long replies.'.repeat(4) : ''}`).join('\n\n');
const turns = reactive<ChatTurn[]>([
  { id: 'prompt', rawTurnId: 'turn', itemId: 'prompt', role: 'user', no: 1, text: 'A saved prompt.' },
  { id: 'reply', rawTurnId: 'turn', itemId: 'reply', role: 'assistant', no: 1,
    text: replyText, blocks: [{ kind: 'text', text: replyText, reply: { state: 'complete' } }],
    reply: { state: 'complete' } },
]);
const firstPage = ref(2), lastPage = ref(2);
const shortRow = (index: number): ChatTurn => ({ id: `short-${index}`, rawTurnId: 'short-turn',
  itemId: `short-${index}`, role: 'assistant', no: 1, text: `Short page ${index}` });
const pagingRequests: string[] = [];
if (query.has('paging')) {
  turns.splice(0, turns.length, shortRow(2));
  (window as Window & { pagingRequests: string[] }).pagingRequests = pagingRequests;
}
async function loadOlder() {
  pagingRequests.push('older');
  turns.unshift(shortRow(--firstPage.value));
  return true;
}
async function loadNewer() {
  pagingRequests.push('newer');
  turns.push(shortRow(++lastPage.value));
  return true;
}
function latest() {
  pagingRequests.push('latest');
  firstPage.value = lastPage.value = 4;
  turns.splice(0, turns.length, shortRow(4));
}
</script>

<template>
  <ConversationPane :turns="turns" :tasks="[]" :status="status" session-id="composer-scroll"
    composer-ready continuous-transcript :narrow-viewport="query.has('narrow')"
    :has-newer-messages="query.has('paging') ? lastPage < 4 : query.has('history')"
    :has-more-messages="query.has('paging') && firstPage > 0"
    :load-older-messages="query.has('paging') ? loadOlder : undefined"
    :load-newer-messages="query.has('paging') ? loadNewer : undefined"
    :return-to-live-tail="query.has('paging') ? latest : undefined" />
</template>
