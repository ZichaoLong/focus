<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue';
import { useI18n } from 'vue-i18n';
import ConversationPane from '../components/chat/ConversationPane.vue';
import ReadingModeControls from '../components/chat/ReadingModeControls.vue';
import BottomSheet from '../components/dialogs/BottomSheet.vue';
import NarrowTopBar from '../components/narrow/NarrowTopBar.vue';
import Icon from '../components/ui/Icon.vue';
import IconButton from '../components/ui/IconButton.vue';
import { captureTranscriptScrollAnchor } from '../components/chat/transcriptScrollAnchor';
import { useAppearance } from '../composables/client/useAppearance';
import { useNarrowViewport } from '../composables/useNarrowViewport';
import { useViewportWidth } from '../composables/useViewportWidth';
import { savedTurns, type ConversationLayout, type SavedWindow, type WindowRequest } from './mobileConversation';
import { useMobileConnectionLabel } from './mobileConnectionLabel';
import FocusPromptTimingHistory from './FocusPromptTimingHistory.vue';
import type { ConversationStatus } from '../types';

function host(op: string, value: object = {}) {
  return window.prompt('conversation/1/' + op, JSON.stringify(value));
}
const info = JSON.parse(host('init') || '{}') as {thread: string; name: string; unavailable: boolean;
  appearance?: Pick<ConversationLayout,'colorScheme' | 'accent' | 'fontSize' | 'locale'>};
const thread = ref(info.thread);
function read(request: WindowRequest): SavedWindow | null {
  return JSON.parse(host('read', {thread: thread.value, ...request}) || 'null');
}
const { t, locale } = useI18n();
const appearance = useAppearance();
const narrow = useNarrowViewport();
const { viewportWidth } = useViewportWidth();
const conversation = ref<InstanceType<typeof ConversationPane> | null>(null);
const page = shallowRef(read({direction: 'open'}));
const turns = shallowRef(page.value ? savedTurns(page.value) : []);
const layout = computed(() => page.value?.layout);
const title = computed(() => page.value?.title || info.name);
const workspace = computed(() => layout.value?.workspace ? {name: layout.value.workspace, root: ''} : null);
const reading = ref(false);
const unavailable = ref(info.unavailable);
const connectionLabel = useMobileConnectionLabel(() => unavailable.value ? 'disconnected' : 'connecting');
const threads = shallowRef<{thread: string; title: string}[] | null>(null);
const gap = ref(!page.value);
const status = computed<ConversationStatus>(() => ({
  model: layout.value?.model || 'Codex', modelId: '', ctxUsed: 0, ctxMax: 0,
  ctxRemainingPct: null, permission: 'manual', branch: '', cwd: '', isGitRepo: false,
}));
const capabilities = {commands: false, permissions: false, modes: false, compact: false,
  model: true, effort: false, interrupt: false, submit: false, submitWhileRunning: false};
const dockStyle = computed(() => layout.value?.width === viewportWidth.value && layout.value.dock > 0
  ? {'--saved-dock-height': layout.value.dock + 'px'} : {});
let touched = false;
let pointerDown = false;
let holding = false;
let settleTimer: ReturnType<typeof setTimeout>;

function applyPresentation() {
  const style = info.appearance?.colorScheme ? info.appearance : layout.value;
  if (style) {
    appearance.setColorScheme(style.colorScheme);
    appearance.setAccent(style.accent);
    appearance.setUiFontSize(style.fontSize);
    if (style.locale === 'zh' || style.locale === 'en') locale.value = style.locale;
  }
  reading.value = page.value?.anchor.reading ?? layout.value?.reading ?? false;
}
applyPresentation();

function bookmark() {
  const pane = conversation.value?.transcriptElement;
  if (!pane || !touched) return;
  const tail = !page.value?.newer && pane.scrollHeight - pane.scrollTop - pane.clientHeight < 16;
  const anchor: SavedWindow['anchor'] = {reading: reading.value};
  if (!tail) {
    const location = captureTranscriptScrollAnchor(pane);
    const row = location && turns.value.find(turn => turn.id === location.id);
    if (!row || !location) return;
    Object.assign(anchor, {turn: row.rawTurnId, item: row.itemId, offset: location.offset, chunk: location.chunk});
  }
  host('bookmark', {thread: thread.value, anchor});
}
function hold(active: boolean) {
  if (active === holding) return;
  holding = active;
  host('interacting', {active});
}
function settle() {
  clearTimeout(settleTimer);
  settleTimer = setTimeout(() => {
    if (pointerDown || threads.value) return;
    bookmark();
    hold(false);
  }, 140);
}
function touch(event: Event) {
  if (!conversation.value?.transcriptElement?.contains(event.target as Node)) return;
  touched = true;
  if (event.type === 'pointerdown') pointerDown = true;
  hold(true);
  settle();
}
function release() {
  if (!pointerDown) return;
  pointerDown = false;
  settle();
}
function scroll(event: Event) {
  if (touched && event.target === conversation.value?.transcriptElement) {
    hold(true);
    settle();
  }
}
function place() {
  const pane = conversation.value?.transcriptElement;
  if (!pane || touched || !page.value) return;
  const anchor = page.value.anchor;
  const row = turns.value.find(turn => turn.rawTurnId === anchor.turn && turn.itemId === anchor.item);
  if (row) conversation.value?.restoreSavedPosition(row.id, anchor.offset || 0, anchor.chunk);
  else pane.scrollTop = pane.scrollHeight;
}
async function load(direction: 'older' | 'newer') {
  const edge = direction === 'older' ? turns.value[0] : turns.value.at(-1);
  if (!edge) return false;
  const next = read({direction, turn:edge.rawTurnId, item:edge.itemId});
  if (!next) { gap.value = true; return false; }
  gap.value = false;
  const ids = new Set(turns.value.map(row => row.id));
  const fresh = savedTurns(next).filter(row => !ids.has(row.id));
  const joined = direction === 'older' ? [...fresh, ...turns.value] : [...turns.value, ...fresh];
  if (direction === 'older') next.newer = joined.length > 108 || !!page.value?.newer;
  else next.older = joined.length > 108 || !!page.value?.older;
  page.value = next;
  turns.value = direction === 'older' ? joined.slice(0, 108) : joined.slice(-108);
  return fresh.length > 0;
}
function showList() {
  threads.value = JSON.parse(host('threads') || '[]');
  hold(true);
}
function closeList() {
  threads.value = null;
  settle();
}
function back(event: Event) {
  if (!threads.value) return;
  event.preventDefault();
  closeList();
}
async function select(id: string) {
  bookmark();
  closeList();
  if (id === thread.value || host('select', {thread: id}) !== 'ok') return;
  thread.value = id;
  touched = false;
  page.value = read({direction: 'open'});
  turns.value = page.value ? savedTurns(page.value) : [];
  gap.value = !page.value;
  applyPresentation();
  await nextTick();
  place();
}
async function changeMode(value: boolean) {
  reading.value = value;
  touched = true;
  hold(true);
  await nextTick();
  bookmark();
  settle();
}
function failed() { unavailable.value = true; }
function reconnecting() { unavailable.value = false; }
window.addEventListener('focus-instance-unavailable', failed);
window.addEventListener('focus-instance-reachable', reconnecting);
window.addEventListener('focus-saved-back', back);
window.addEventListener('online', reconnecting);
onMounted(() => {
  place();
  void document.fonts.ready.then(() => requestAnimationFrame(place));
  window.addEventListener('pointerup', release);
  window.addEventListener('pointercancel', release);
  window.addEventListener('pagehide', bookmark);
});
onUnmounted(() => {
  clearTimeout(settleTimer);
  window.removeEventListener('pointerup', release);
  window.removeEventListener('pointercancel', release);
  window.removeEventListener('focus-instance-unavailable', failed);
  window.removeEventListener('focus-instance-reachable', reconnecting);
  window.removeEventListener('focus-saved-back', back);
  window.removeEventListener('online', reconnecting);
  window.removeEventListener('pagehide', bookmark);
});
</script>
<template>
  <div class="saved-chat focus-shell" :style="dockStyle">
    <div class="focus-app" :class="{'narrow-viewport': narrow, 'reading-mode': reading}">
      <NarrowTopBar v-if="narrow && !reading" saved :workspace="workspace" :session-title="title"
        :session-id="thread" :connection-label="connectionLabel" reading-mode-enabled
        :summary-export-available="layout?.exports" @enter-reading-mode="changeMode(true)" @open-switcher="showList">
        <template #instances>
          <IconButton :label="t('focus.switchInstance')" @click="host('instances')"><Icon name="panel-expand" size="lg" /></IconButton>
        </template>
        <template #utility-actions>
          <IconButton size="lg" :label="t('focus.runtimeDetailsOpen')" disabled><Icon name="info" size="lg" /></IconButton>
        </template>
      </NarrowTopBar>
      <aside v-if="!narrow && !reading && layout?.sidebar !== 0" class="saved-side" :style="{width: (layout?.sidebar ?? 270) + 'px'}">
        <button @click="host('instances')">{{ t('focus.switchInstance') }}</button>
        <button @click="showList">{{ title }}</button>
        <small role="status">{{ connectionLabel }}</small>
      </aside>
      <IconButton v-if="!narrow && !reading && layout?.sidebar === 0" class="sidebar-toggle-btn"
        size="sm" :label="t('narrow.openSwitcher')" @click="showList"><Icon name="panel-expand" /></IconButton>
      <main class="focus-main" @pointerdown.capture="touch" @wheel.capture.passive="touch" @scroll.capture.passive="scroll">
        <FocusPromptTimingHistory v-if="!reading && (layout?.timing ?? true)" :thread-id="thread" />
        <ReadingModeControls v-if="reading" saved :narrow-viewport="narrow" :session-title="title" :session-id="thread"
          :summary-export-available="layout?.exports" export-disabled prompt-history-disabled
          :connection-label="connectionLabel" :switcher-open="!!threads" @exit="changeMode(false)" @switch-session="showList">
          <template #instances><IconButton :label="t('focus.switchInstance')" @click="host('instances')"><Icon name="panel-expand" size="lg" /></IconButton></template>
        </ReadingModeControls>
        <ConversationPane ref="conversation" :turns="turns" :session-id="thread" :file-reload-key="thread"
          :tasks="[]" :status="status" :workspace-name="layout?.workspace" :session-title="title"
          :composer-capabilities="capabilities" :composer-ready="false" :interaction-enabled="false"
          :session-actions="false" :narrow-viewport="narrow" :reading-mode="reading" reading-mode-enabled
          saved-transcript continuous-transcript local-read-only
          :has-more-messages="page?.older" :has-newer-messages="page?.newer"
          :load-older-messages="() => load('older')" :load-newer-messages="() => load('newer')"
          @enter-reading-mode="changeMode(true)" />
        <small v-if="gap" class="saved-gap" role="status">{{ t('focus.savedPageGap') }}</small>
      </main>
    </div>
    <BottomSheet :model-value="!!threads" :title="t('narrow.openSwitcher')" @close="closeList">
      <nav class="saved-menu">
        <button v-if="!narrow" @click="closeList(); host('instances')">{{ t('focus.switchInstance') }}</button>
        <button v-for="entry in threads" :key="entry.thread" @click="select(entry.thread)">{{ entry.title }}</button>
        <button class="saved-copy-action" @click="closeList(); host('records')">{{ t('focus.openSavedCopy') }}</button>
        <button v-if="unavailable" @click="closeList(); host('retry')">{{ t('focus.retry') }}</button>
      </nav>
    </BottomSheet>
  </div>
</template>
<style src="./conversationLayout.css"></style>
<style scoped>
.saved-chat :deep(.chat-dock) { min-height: var(--saved-dock-height, 0px); }
.saved-side, .saved-menu { display: flex; flex-direction: column; }
.saved-side { grid-column: 1; overflow: hidden; max-width: calc(100vw - 320px); background: var(--color-surface); }
.saved-menu { padding: var(--space-3); }
.saved-menu button, .saved-side button { text-align: start; padding: var(--space-3); color: var(--color-text); }
.saved-gap { position: absolute; bottom: 25%; align-self: center; padding: var(--space-2); background: var(--color-surface); }
</style>
