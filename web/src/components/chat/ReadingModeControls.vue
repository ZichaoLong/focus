<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { SummaryExportRequest } from '../../types';
import type { RuntimeDetailsTone } from '../../focus/runtimeDetailsPresentation';
import Button from '../ui/Button.vue';
import Icon from '../ui/Icon.vue';
import IconButton from '../ui/IconButton.vue';
import Menu from '../ui/Menu.vue';
import MenuItem from '../ui/MenuItem.vue';

const props = withDefaults(defineProps<{
  narrowViewport?: boolean;
  sessionTitle: string;
  sessionId?: string;
  switcherOpen?: boolean;
  promptHistoryDisabled?: boolean;
  summaryExportAvailable?: boolean;
  threadDataExportAvailable?: boolean;
  exportDisabled?: boolean;
  runtimeDetailsTone?: RuntimeDetailsTone;
  runtimeDetailsOpen?: boolean;
}>(), {
  narrowViewport: false,
  sessionId: '',
  switcherOpen: false,
  promptHistoryDisabled: false,
  summaryExportAvailable: false,
  threadDataExportAvailable: false,
  exportDisabled: false,
  runtimeDetailsTone: 'neutral',
  runtimeDetailsOpen: false,
});

const emit = defineEmits<{
  exit: [];
  switchSession: [];
  promptHistory: [];
  exportSession: [request: SummaryExportRequest];
  exportThreadData: [id: string];
  openRuntimeDetails: [];
  openSettings: [];
}>();

const { t } = useI18n();
const exportMenuOpen = ref(false);
const exportMenuRoot = ref<HTMLElement | null>(null);
const exportButton = ref<InstanceType<typeof IconButton> | null>(null);
const hasExportActions = computed(() => Boolean(props.sessionId) && (
  props.summaryExportAvailable || props.threadDataExportAvailable
));

function closeExportMenu(): void {
  exportMenuOpen.value = false;
  document.removeEventListener('pointerdown', onOutsidePointerDown);
}

function onOutsidePointerDown(event: PointerEvent): void {
  if (!exportMenuRoot.value?.contains(event.target as Node)) closeExportMenu();
}

async function toggleExportMenu(): Promise<void> {
  if (exportMenuOpen.value) {
    closeExportMenu();
    return;
  }
  if (!hasExportActions.value || props.exportDisabled) return;
  exportMenuOpen.value = true;
  document.addEventListener('pointerdown', onOutsidePointerDown);
  await nextTick();
  exportMenuRoot.value?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
}

function onExportKeydown(event: KeyboardEvent): void {
  if (!exportMenuOpen.value) {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      void toggleExportMenu();
    }
    return;
  }
  if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    closeExportMenu();
    exportButton.value?.el?.focus();
    return;
  }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
  event.preventDefault();
  const items = Array.from(exportMenuRoot.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? []);
  if (!items.length) return;
  const current = items.indexOf(document.activeElement as HTMLButtonElement);
  const step = event.key === 'ArrowDown' ? 1 : items.length - 1;
  const target = current < 0 ? (event.key === 'ArrowDown' ? 0 : items.length - 1) : (current + step) % items.length;
  items[target]?.focus();
}

function onExportFocusOut(event: FocusEvent): void {
  if (!exportMenuRoot.value?.contains(event.relatedTarget as Node | null)) closeExportMenu();
}

function exportSession(format: SummaryExportRequest['format']): void {
  if (!props.sessionId || !props.summaryExportAvailable || props.exportDisabled) return;
  closeExportMenu();
  emit('exportSession', { threadId: props.sessionId, format });
}

function exportThreadData(): void {
  if (!props.sessionId || !props.threadDataExportAvailable || props.exportDisabled) return;
  closeExportMenu();
  emit('exportThreadData', props.sessionId);
}

watch(() => [props.sessionId, props.summaryExportAvailable, props.threadDataExportAvailable,
  props.exportDisabled, props.switcherOpen, props.narrowViewport], closeExportMenu);
onUnmounted(closeExportMenu);
</script>

<template>
  <div class="reading-mode-controls" :class="{ 'is-narrow': narrowViewport }">
    <IconButton
      class="reading-mode-exit"
      size="sm"
      :label="t('focus.exitReadingMode')"
      :aria-pressed="true"
      data-reading-mode-toggle
      @click="emit('exit')"
    >
      <Icon name="close" size="sm" />
    </IconButton>
    <Button
      class="reading-session-switch"
      size="sm"
      variant="secondary"
      :aria-label="t('narrow.openSwitcher')"
      aria-haspopup="dialog"
      :aria-expanded="switcherOpen"
      @click="emit('switchSession')"
    >
      <span class="reading-session-title">{{ sessionTitle }}</span>
      <Icon name="chevron-down" size="sm" />
    </Button>
    <IconButton
      class="reading-prompt-history"
      size="sm"
      :disabled="promptHistoryDisabled"
      :label="t('conversation.promptHistory')"
      :title="t('conversation.promptHistory')"
      aria-haspopup="dialog"
      @click="emit('promptHistory')"
    >
      <Icon name="list" size="sm" />
    </IconButton>
    <div
      v-if="hasExportActions"
      ref="exportMenuRoot"
      class="reading-export"
      @keydown="onExportKeydown"
      @focusout="onExportFocusOut"
    >
      <IconButton
        ref="exportButton"
        class="reading-export-button"
        size="sm"
        :disabled="exportDisabled"
        :label="t('header.exportOptions')"
        :aria-expanded="exportMenuOpen"
        aria-haspopup="menu"
        @click.stop="toggleExportMenu"
      >
        <Icon name="download" size="sm" />
      </IconButton>
      <Menu v-if="exportMenuOpen" class="reading-export-menu" @click.stop>
        <MenuItem v-if="summaryExportAvailable" :size="narrowViewport ? 'lg' : 'md'" @click="exportSession('markdown')">
          <Icon name="download" size="sm" />
          {{ t('header.exportSession') }}
        </MenuItem>
        <MenuItem v-if="summaryExportAvailable" :size="narrowViewport ? 'lg' : 'md'" @click="exportSession('print')">
          <Icon name="download" size="sm" />
          {{ t('focus.printSummary') }}
        </MenuItem>
        <MenuItem v-if="threadDataExportAvailable" :size="narrowViewport ? 'lg' : 'md'" @click="exportThreadData">
          <Icon name="download" size="sm" />
          {{ t('header.exportThreadData') }}
        </MenuItem>
      </Menu>
    </div>
    <IconButton
      class="reading-runtime-details"
      size="sm"
      :label="t('focus.runtimeDetailsOpen')"
      :title="t('focus.runtimeDetailsOpen')"
      :aria-expanded="runtimeDetailsOpen"
      @click="closeExportMenu(); emit('openRuntimeDetails')"
    >
      <Icon name="info" size="sm" />
      <span class="reading-runtime-dot" :class="runtimeDetailsTone" aria-hidden="true" />
    </IconButton>
    <IconButton
      class="reading-settings"
      size="sm"
      :label="t('settings.title')"
      :title="t('settings.title')"
      aria-haspopup="dialog"
      @click="closeExportMenu(); emit('openSettings')"
    >
      <Icon name="settings" size="sm" />
    </IconButton>
  </div>
</template>

<style scoped>
.reading-mode-controls {
  z-index: var(--z-sticky);
  height: 48px;
  flex: none;
  display: flex;
  flex-direction: row-reverse;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-4);
}
.reading-mode-controls.is-narrow {
  height: calc(50px + var(--safe-top));
  flex-direction: row;
  padding: var(--safe-top) max(12px, var(--safe-right)) 0 max(12px, var(--safe-left));
}
.reading-mode-exit,
.reading-prompt-history,
.reading-export-button,
.reading-runtime-details,
.reading-settings {
  width: 30px;
  height: 30px;
  background: var(--color-surface-raised);
  border-color: var(--color-line-strong);
  box-shadow: var(--shadow-xs);
}
.reading-mode-controls.is-narrow .reading-prompt-history { margin-left: auto; }
.reading-session-switch {
  flex: 0 1 auto;
  min-width: 0;
  max-width: min(52vw, 240px);
}
.reading-session-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.reading-session-switch :deep(.ui-button__content) {
  min-width: 0;
}
.reading-export { position: relative; flex: none; }
.reading-runtime-details { position: relative; }
.reading-runtime-dot {
  position: absolute;
  top: 3px;
  right: 3px;
  width: 7px;
  height: 7px;
  border-radius: var(--radius-full);
  background: var(--color-text-faint);
}
.reading-runtime-dot.advisory { background: var(--color-warning); }
.reading-runtime-dot.danger { background: var(--color-danger); }
.reading-export-menu {
  position: absolute;
  z-index: var(--z-dropdown);
  top: calc(100% + 4px);
  right: 0;
  width: max-content;
  max-width: calc(100vw - 24px);
}
</style>
