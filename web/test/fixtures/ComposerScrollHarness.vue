<script setup lang="ts">
import { provide } from 'vue';
import ConversationPane from '../../src/components/chat/ConversationPane.vue';
import type { ChatTurn, ConversationStatus } from '../../src/types';

provide('resolveImage', async () => null);
const query = new URLSearchParams(window.location.search);
const status: ConversationStatus = { model: '', modelId: '', ctxUsed: 0, ctxMax: 0,
  ctxRemainingPct: null, permission: 'manual', branch: '', cwd: '', isGitRepo: false };
const turns: ChatTurn[] = [
  { id: 'prompt', rawTurnId: 'turn', itemId: 'prompt', role: 'user', no: 1, text: 'A saved prompt.' },
  { id: 'reply', rawTurnId: 'turn', itemId: 'reply', role: 'assistant', no: 1,
    // Enough scroll range without entering markstream's separate node window.
    text: Array.from({ length: 48 }, (_, index) => `History paragraph ${index + 1}.`).join('\n\n'),
    reply: { state: 'complete' } },
];
</script>

<template>
  <ConversationPane :turns="turns" :tasks="[]" :status="status" session-id="composer-scroll"
    composer-ready continuous-transcript :narrow-viewport="query.has('narrow')"
    :has-newer-messages="query.has('history')" />
</template>
