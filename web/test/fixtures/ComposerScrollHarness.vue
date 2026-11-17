<script setup lang="ts">
import { provide } from 'vue';
import ConversationPane from '../../src/components/chat/ConversationPane.vue';
import type { ChatTurn, ConversationStatus } from '../../src/types';

provide('resolveImage', async () => null);
const query = new URLSearchParams(window.location.search);
const status: ConversationStatus = { model: '', modelId: '', ctxUsed: 0, ctxMax: 0,
  ctxRemainingPct: null, permission: 'manual', branch: '', cwd: '', isGitRepo: false };
// The long variant also exercises Focus's nested Markdown chunk window.
const replyText = Array.from({ length: query.has('long') ? 200 : 48 }, (_, index) =>
  `History paragraph ${index + 1}.${query.has('long') ? ' A sentence for measuring long replies.'.repeat(4) : ''}`).join('\n\n');
const turns: ChatTurn[] = [
  { id: 'prompt', rawTurnId: 'turn', itemId: 'prompt', role: 'user', no: 1, text: 'A saved prompt.' },
  { id: 'reply', rawTurnId: 'turn', itemId: 'reply', role: 'assistant', no: 1,
    text: replyText, blocks: [{ kind: 'text', text: replyText, reply: { state: 'complete' } }],
    reply: { state: 'complete' } },
];
</script>

<template>
  <ConversationPane :turns="turns" :tasks="[]" :status="status" session-id="composer-scroll"
    composer-ready continuous-transcript :narrow-viewport="query.has('narrow')"
    :has-newer-messages="query.has('history')" />
</template>
