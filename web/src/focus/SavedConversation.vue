<script setup lang="ts">
import { nextTick, onMounted, ref, shallowRef } from 'vue';
import ChatPane from '../components/chat/ChatPane.vue';
import { captureTranscriptScrollAnchor, restoreTranscriptScrollAnchor } from '../components/chat/transcriptScrollAnchor';
import { savedTurns, type SavedWindow } from './mobileConversation';
import type { ChatTurn } from '../types';

function host(op: string, value: object = {}) { return window.prompt('conversation/1/' + op, JSON.stringify(value)); }
const info = JSON.parse(host('init') || '{}') as {thread: string; name: string};
const thread = ref(info.thread);
const view = ref<HTMLElement | null>(null);
const page = shallowRef<SavedWindow | null>(null);
const turns = shallowRef<ChatTurn[]>([]);
const threads = shallowRef<{thread: string; title: string}[] | null>(null);
const gap = ref('');
const touched=ref(false);
let ready=false;
let bookmarkTimer: ReturnType<typeof setTimeout> | undefined;
function position() {
  const pane = view.value;
  if (!pane || !touched.value || !ready) return;
  const top = pane.getBoundingClientRect().top;
  const nodes = Array.from(pane.querySelectorAll<HTMLElement>('[data-turn-id]'));
  const node = nodes.find(n => n.getBoundingClientRect().bottom > top && !n.hidden);
  const row = turns.value.find(t => t.id === node?.dataset.turnId);
  if (!row || !node) return;
  const tail = !page.value?.newer && pane.scrollHeight - pane.scrollTop - pane.clientHeight < 16;
  host('bookmark', { thread: thread.value, anchor: tail ? {} : {turn: row.rawTurnId, item: row.itemId, offset: node.getBoundingClientRect().top - top} });
}
function scrolled() { clearTimeout(bookmarkTimer); bookmarkTimer = setTimeout(position, 100); }
function place(id?: string, offset = 0, tail = false) {
  const pane = view.value;
  if (!pane) return;
  const row = Array.from(pane.querySelectorAll<HTMLElement>('[data-turn-id]')).find(n => n.dataset.turnId === id);
  if (row) pane.scrollTop += row.getBoundingClientRect().top - pane.getBoundingClientRect().top - offset;
  else if (tail) pane.scrollTop = pane.scrollHeight;
}
async function load(direction: 'open'|'older'|'newer') {
  const first = direction === 'older' ? turns.value[0] : turns.value.at(-1);
  const viewport = view.value;
  const previous = direction !== 'open' && viewport ? captureTranscriptScrollAnchor(viewport) : null;
  const raw = host('read', {thread: thread.value, direction, ...(direction !== 'open' && first ? {turn:first.rawTurnId,item:first.itemId}: {})});
  const next = raw && JSON.parse(raw) as SavedWindow | null;
  if (!next) { gap.value='这部分记录需要联网加载'; return; }
  gap.value='';
  const current = direction === 'open' ? [] : turns.value;
  const ids = new Set(current.map(row => row.id));
  const fresh = savedTurns(next).filter(row => !ids.has(row.id));
  const joined = direction === 'older' ? [...fresh, ...current] : [...current, ...fresh];
  if (direction === 'older') next.newer = joined.length > 108 || !!page.value?.newer;
  if (direction === 'newer') next.older = joined.length > 108 || !!page.value?.older;
  page.value = next;
  turns.value = direction === 'older' ? joined.slice(0, 108) : joined.slice(-108);
  await nextTick();
  if (direction === 'open') {
    const anchor = turns.value.find(t => t.rawTurnId===next.anchor.turn && t.itemId===next.anchor.item);
    const align = () => { if (!touched.value) place(anchor?.id,next.anchor.offset,!anchor); };
    align(); requestAnimationFrame(() => requestAnimationFrame(align));
  } else if (viewport && previous) {
    restoreTranscriptScrollAnchor(viewport, previous, { preserveScrollMotion: false });
  }
  ready=true;
}
function switchThread(id: string) {
  position(); clearTimeout(bookmarkTimer);
  threads.value = null;
  if (id === thread.value || host('select', { thread: id }) !== 'ok') return;
  thread.value=id; touched.value=false; ready=false;
  turns.value=[]; page.value=null; void load('open');
}
function showList() { threads.value=JSON.parse(host('threads') || '[]'); }
onMounted(() => { void load('open'); window.addEventListener('pagehide',position); });
</script>
<template>
  <div class="saved-chat">
    <header><button type="button" @click="host('instances')">切换实例</button>
      <button type="button" class="thread-title" @click="showList">{{ page?.title || info.name }}</button>
      <small role="status">正在连接</small></header>
    <nav v-if="threads"><button v-for="entry in threads" :key="entry.thread" @click="switchThread(entry.thread)">{{ entry.title }}</button>
      <button @click="threads=null">返回对话</button></nav>
    <main v-show="!threads" ref="view" @pointerdown="touched=true" @wheel="touched=true" @scroll.passive="scrolled">
      <ChatPane :turns="turns" :has-more-messages="!!page?.older" :has-newer-messages="!!page?.newer"
        :history-auto-load-armed="touched && !gap" :newer-auto-load-armed="false"
        @load-older-messages="load('older')" @load-newer-messages="load('newer')" />
      <small v-if="gap" role="status">{{ gap }}</small>
    </main>
    <footer><button type="button" @click="host('records')">查看离线副本</button></footer>
  </div>
</template>
<style scoped>
.saved-chat{height:100dvh;display:flex;flex-direction:column;background:var(--color-bg);color:var(--color-text);font-family:system-ui,sans-serif}
header,footer{display:flex;align-items:center;gap:12px;padding:8px 12px;border-bottom:1px solid var(--color-border)}
button{color:inherit;background:none;border:0;padding:6px;font:inherit} .thread-title{flex:1;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600}
main,nav{flex:1;min-height:0;overflow:auto;padding:12px 16px}nav button{display:block;text-align:left;width:100%}
small,footer{color:var(--color-text-secondary);font-size:12px}footer{justify-content:flex-end;border-top:1px solid var(--color-border)}
</style>
