<!-- apps/kimi-web/src/components/narrow/NarrowTopBar.vue -->
<!-- Narrow-layout title bar (50px): a 28px dark workspace square, a tappable middle -->
<!-- zone showing the mono `workspace / session ⌄` path with a status sub-line -->
<!-- (● running · branch · N sessions), and trailing utility actions. Tapping -->
<!-- the middle opens the switcher sheet; the sliders open the settings sheet. -->
<!-- Terminal Pro styling, no emoji. -->
<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { WorkspaceView } from '../../types';
import IconButton from '../ui/IconButton.vue';
import Icon from '../ui/Icon.vue';
import Menu from '../ui/Menu.vue';
import MenuItem from '../ui/MenuItem.vue';

const { t } = useI18n();

const props = withDefaults(
  defineProps<{
    /** Active workspace (for the chip glyph + name). */
    workspace: WorkspaceView | null;
    /** Active session title (the right, bold side of the mono path). */
    sessionTitle?: string;
    /** True when the active session is doing work (drives the status dot/text). */
    running?: boolean;
    /** Current git branch (sub-line). */
    branch?: string;
    /** Number of sessions in the active workspace (sub-line). */
    sessionCount?: number;
    /** Existing loaded conversation may enter the page-level reading mode. */
    readingModeEnabled?: boolean;
    /** Active thread id used by the narrow-only export action menu. */
    sessionId?: string;
    /** The active thread may be exported as Q&A Markdown. */
    summaryExportAvailable?: boolean;
    /** The active paginated thread may be exported as complete JSONL data. */
    threadDataExportAvailable?: boolean;
  }>(),
  {
    workspace: null,
    sessionTitle: '',
    running: false,
    branch: '',
    sessionCount: 0,
    readingModeEnabled: false,
    sessionId: '',
    summaryExportAvailable: false,
    threadDataExportAvailable: false,
  },
);

const emit = defineEmits<{
  openSwitcher: [];
  openSettings: [];
  enterReadingMode: [];
  exportSession: [id: string];
  exportThreadData: [id: string];
}>();

/** First letter of the workspace name for the square glyph. */
const chip = computed<string>(() => {
  const w = props.workspace;
  const src = (w?.name || w?.root || '').trim();
  const ch = src.charAt(0);
  return ch ? ch.toUpperCase() : 'F';
});

const wsName = computed<string>(() => props.workspace?.name ?? t('workspace.noWorkspace'));

const statusText = computed<string>(() =>
  props.running ? t('narrow.running') : t('narrow.idle'),
);

// The wide ChatHeader owns the same active-thread downloads. Narrow layout
// replaces that header, so its top bar must retain those actions instead of
// hiding the capabilities with the desktop-only chrome.
const exportMenuOpen = ref(false);
const exportMenuRoot = ref<HTMLElement | null>(null);
const hasExportActions = computed(() => Boolean(props.sessionId) && (
  props.summaryExportAvailable || props.threadDataExportAvailable
));

function closeExportMenu(): void {
  exportMenuOpen.value = false;
  if (typeof document !== 'undefined') {
    document.removeEventListener('mousedown', onDocumentMouseDown);
  }
}

function onDocumentMouseDown(event: MouseEvent): void {
  if (exportMenuRoot.value?.contains(event.target as Node)) return;
  closeExportMenu();
}

function toggleExportMenu(): void {
  if (exportMenuOpen.value) {
    closeExportMenu();
    return;
  }
  exportMenuOpen.value = true;
  if (typeof document !== 'undefined') {
    document.addEventListener('mousedown', onDocumentMouseDown);
  }
}

function exportSession(): void {
  if (!props.sessionId || !props.summaryExportAvailable) return;
  closeExportMenu();
  emit('exportSession', props.sessionId);
}

function exportThreadData(): void {
  if (!props.sessionId || !props.threadDataExportAvailable) return;
  closeExportMenu();
  emit('exportThreadData', props.sessionId);
}

watch(
  () => [props.sessionId, props.summaryExportAvailable, props.threadDataExportAvailable],
  closeExportMenu,
);
onUnmounted(closeExportMenu);
</script>

<template>
  <div class="topbar">
    <IconButton
      v-if="readingModeEnabled"
      class="wsq reading-mode-entry"
      size="sm"
      :label="t('focus.enterReadingMode')"
      :aria-pressed="false"
      data-reading-mode-toggle
      @click="emit('enterReadingMode')"
    >
      <Icon name="file-text" size="sm" />
    </IconButton>
    <span v-else class="wsq">{{ chip }}</span>

    <button
      type="button"
      class="tb-mid"
      :aria-label="t('narrow.openSwitcher')"
      @click="emit('openSwitcher')"
    >
      <span class="tb-path">
        <span class="ws">{{ wsName }}</span>
        <template v-if="sessionTitle">
          <span class="sl">/</span>
          <span class="se">{{ sessionTitle }}</span>
        </template>
        <span class="cv">⌄</span>
      </span>
      <span class="tb-sub">
        <span class="rd" :class="{ on: running }" />
        <span>{{ statusText }}</span>
        <template v-if="branch"> · {{ branch }}</template>
        <template v-if="sessionCount > 0"> · {{ t('narrow.sessionCount', { n: sessionCount }) }}</template>
      </span>
    </button>

    <div class="tb-actions">
      <div v-if="hasExportActions" ref="exportMenuRoot" class="tb-session-actions">
        <IconButton
          size="lg"
          :label="t('header.exportOptions')"
          :aria-expanded="exportMenuOpen"
          aria-haspopup="menu"
          @click.stop="toggleExportMenu"
        >
          <Icon name="download" size="lg" />
        </IconButton>
        <Menu v-if="exportMenuOpen" class="tb-session-menu" @click.stop>
          <MenuItem v-if="summaryExportAvailable" size="lg" @click="exportSession">
            <Icon name="download" size="sm" />
            {{ t('header.exportSession') }}
          </MenuItem>
          <MenuItem v-if="threadDataExportAvailable" size="lg" @click="exportThreadData">
            <Icon name="download" size="sm" />
            {{ t('header.exportThreadData') }}
          </MenuItem>
        </Menu>
      </div>

      <slot name="utility-actions" />

      <IconButton
        size="lg"
        :label="t('narrow.openSettings')"
        @click="emit('openSettings')"
      >
        <Icon name="sliders" size="lg" />
      </IconButton>
    </div>
  </div>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  /* Grow the bar by the top inset so the 50px content row stays below the
     status bar / notch in standalone PWA mode and landscape. */
  height: calc(50px + var(--safe-top));
  flex: none;
  padding: var(--safe-top) max(12px, var(--safe-right)) 0 max(12px, var(--safe-left));
  border-bottom: 1px solid var(--color-line);
  background: var(--color-bg);
  font-family: var(--font-ui);
}

/* Workspace square */
.wsq {
  flex: none;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-md);
  background: var(--color-text);
  color: var(--color-bg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  font-weight: var(--weight-medium);
  font-size: var(--ui-font-size-sm);
}
.reading-mode-entry:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-text) 88%, var(--color-bg));
  color: var(--color-bg);
}

/* Middle tappable zone */
.tb-mid {
  flex: 1;
  min-width: 0;
  height: 100%;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 1px;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  text-align: left;
}

.tb-path {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: var(--ui-font-size-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tb-path .ws { color: var(--color-text); }
.tb-path .sl { color: var(--color-text-faint); }
.tb-path .se {
  color: var(--color-text);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tb-path .cv { color: var(--color-text-faint); flex: none; }

.tb-sub {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: max(9px, calc(var(--ui-font-size) - 3.5px));
  color: var(--color-text-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tb-sub .rd {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--color-text-faint);
}
.tb-sub .rd.on { background: var(--color-success); }

.tb-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: none;
}
.tb-session-actions {
  position: relative;
  flex: none;
}
.tb-session-menu {
  position: absolute;
  z-index: var(--z-dropdown);
  top: calc(100% + 4px);
  right: 0;
}

.topbar .tb-path { font-family: var(--sans); }
</style>
