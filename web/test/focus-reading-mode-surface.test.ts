import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { effectScope, ref } from 'vue';
import { describe, expect, it } from 'vitest';
import enFocus from '../src/i18n/locales/en/focus';
import zhFocus from '../src/i18n/locales/zh/focus';
import { useFocusReadingMode } from '../src/focus/focusReadingMode';

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function between(value: string, start: string, end: string): string {
  const startIndex = value.indexOf(start);
  const endIndex = value.indexOf(end, startIndex);
  expect(startIndex).toBeGreaterThanOrEqual(0);
  expect(endIndex).toBeGreaterThan(startIndex);
  return value.slice(startIndex, endIndex);
}

describe('Focus page-level reading mode surface', () => {
  it('keeps the ordinary session switch surfaces while adding one page-owned mode', () => {
    const app = source('../src/focus/FocusApp.vue');
    const readingModeOwner = source('../src/focus/focusReadingMode.ts');
    const header = source('../src/components/chat/ChatHeader.vue');
    const narrowTopBar = source('../src/components/narrow/NarrowTopBar.vue');

    expect(readingModeOwner).toContain("type FocusPresentationMode = 'normal' | 'reading';");
    expect(readingModeOwner).toContain("const presentationMode = ref<FocusPresentationMode>('normal');");
    expect(readingModeOwner).toContain(
      "const readingMode = computed(() => presentationMode.value === 'reading');",
    );
    expect(app).toContain('} = useFocusReadingMode({');
    expect(readingModeOwner).not.toMatch(/localStorage|sessionStorage|STORAGE_KEYS/u);

    const narrowTopBarIndex = app.indexOf('<NarrowTopBar');
    const mainIndex = app.indexOf('<main class="focus-main">', narrowTopBarIndex);
    const conversationPaneIndex = app.indexOf('<ConversationPane', mainIndex);
    expect(narrowTopBarIndex).toBeGreaterThanOrEqual(0);
    expect(mainIndex).toBeGreaterThan(narrowTopBarIndex);
    expect(conversationPaneIndex).toBeGreaterThan(mainIndex);

    expect(narrowTopBar).toContain('class="tb-mid"');
    expect(narrowTopBar).toContain("@click=\"emit('openSwitcher')\"");
    expect(narrowTopBar).toContain('readingModeEnabled?: boolean;');
    expect(narrowTopBar).toContain("@click=\"emit('enterReadingMode')\"");
    expect(header).toContain('readingModeEnabled?: boolean;');
    expect(header).toContain("@click=\"emit('enterReadingMode')\"");
    expect(app).toContain(':reading-mode-enabled="canEnterReadingMode"');
    expect(app).toContain('@enter-reading-mode="enterReadingMode"');
  });

  it('hides shell chrome but keeps the transcript and its body actions mounted', () => {
    const app = source('../src/focus/FocusApp.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');
    const dock = source('../src/components/chat/ChatDock.vue');

    expect(app).toContain("'reading-mode': readingMode");
    expect(app).toMatch(/<Sidebar\s+v-show="!readingMode"/u);
    expect(app).toContain('v-show="!sidebarCollapsed && !readingMode"');
    expect(app).toMatch(/<NarrowTopBar\s+v-else\s+v-show="!readingMode"/u);
    expect(between(app, '<NarrowTopBar', '</NarrowTopBar>'))
      .toContain('class="runtime-details-narrow-trigger"');
    expect(app).toMatch(/<FocusPrimaryNotices\s+v-if="!readingMode"/u);
    expect(app).toContain('v-if="unsupportedNotice && !readingMode"');

    expect(pane).toContain("<section class=\"con\" :class=\"{ 'narrow-viewport': narrowViewport, 'reading-mode': readingMode }\">");
    expect(pane).toMatch(/<ChatHeader[\s\S]*?v-show="!readingMode"/u);
    expect(pane).toMatch(/<ConversationToc\s+v-if="conversationToc"/u);
    expect(pane).toContain(':inline-visible="!readingMode"');
    expect(pane).toMatch(/<ChatDock\s+v-if="!showTargetlessComposer"\s+v-show="!readingMode"/u);
    expect(pane).toContain(':surface-mode="readingMode ? \'hidden\' : composerSurfaceMode"');
    expect(pane).not.toContain('.con.reading-mode :deep(.chat)');

    // The exact async submission and attachment owners stay mounted even while
    // their presentation is hidden.
    expect(dock).toContain('<Composer\n      v-show="!pendingQuestion && !pendingApproval"');
    expect(pane.match(/useAttachmentUpload\(/gu)).toHaveLength(1);
    expect(pane).not.toMatch(/v-if="!readingMode"[^>]*>\s*<ChatDock/gu);

    expect(pane).toContain('<ChatPane');
    expect(pane).toContain('@open-tool-diff="emit(\'openToolDiff\', $event)"');
    expect(pane).toContain('v-if="showPill || viewingHistory || promptNavigationActive"');
    expect(pane).toContain(':style="{ bottom: `${readingMode ? 12 : dockHeight + 12}px` }"');
    expect(app).toContain('<aside\n        v-if="detailOpen"');
    expect(app).not.toContain('v-if="detailOpen && !readingMode"');
  });

  it('offers exit, conversation-switch, and Prompt history actions at the reading edge', () => {
    const app = source('../src/focus/FocusApp.vue');
    const readingModeOwner = source('../src/focus/focusReadingMode.ts');
    const controls = source('../src/components/chat/ReadingModeControls.vue');

    expect(app).toMatch(/<ReadingModeControls\s+v-if="readingMode"/u);
    expect(app).toContain('@exit="exitReadingMode"');
    expect(app).toContain('@switch-session="showNarrowSwitcher = true"');
    expect(app).toContain('@prompt-history="conversationPaneRef?.openPromptHistory()"');
    expect(controls).toContain('class="reading-mode-exit"');
    expect(controls).toContain("@click=\"emit('exit')\"");
    expect(controls).toContain("t('focus.exitReadingMode')");
    expect(controls).toContain('data-reading-mode-toggle');
    expect(controls).toContain('class="reading-session-switch"');
    expect(controls).toContain("@click=\"emit('switchSession')\"");
    expect(controls).toContain("t('narrow.openSwitcher')");
    expect(controls).toContain('aria-haspopup="dialog"');
    expect(controls).toContain(':aria-expanded="switcherOpen"');
    expect(controls).toContain('{{ sessionTitle }}');
    expect(controls).toContain('class="reading-prompt-history"');
    expect(controls).toContain(':disabled="promptHistoryDisabled"');
    expect(controls).toContain("t('conversation.promptHistory')");
    expect(controls).toContain('aria-haspopup="dialog"');
    expect(controls).toContain("@click=\"emit('promptHistory')\"");
    expect(controls).toContain('<Icon name="list" size="sm" />');
    expect(controls).not.toContain('<Dialog');
    expect(app).toContain(':prompt-history-disabled="client.conversationLoading.value"');
    expect(controls).toContain('height: 48px;');
    expect(controls).toContain('flex: none;');
    expect(controls).toContain('.reading-mode-controls.is-narrow {');
    expect(controls).toContain('height: calc(50px + var(--safe-top));');
    expect(controls).toContain(
      'padding: var(--safe-top) max(12px, var(--safe-right)) 0 max(12px, var(--safe-left));',
    );
    expect(controls).toContain(
      '.reading-mode-controls.is-narrow .reading-prompt-history { margin-left: auto; }',
    );

    const switcher = between(app, '<NarrowSwitcherSheet', '</NarrowSwitcherSheet>');
    expect(switcher).toContain('v-if="isNarrowViewport || readingMode"');
    expect(switcher).toContain('@select="client.selectThread($event)"');
    expect(switcher).toContain(':allow-create="!readingMode"');
    expect(switcher).toContain(':allow-session-actions="!readingMode"');

    const exit = between(
      readingModeOwner,
      'function exitReadingMode(): void {',
      '\n  }\n\n  watch(',
    );
    expect(exit.indexOf('options.dismissSwitcher();')).toBeLessThan(
      exit.indexOf("presentationMode.value = 'normal';"),
    );
    expect(app).toContain('dismissSwitcher: () => { showNarrowSwitcher.value = false; },');

    expect(enFocus.enterReadingMode).toBe('Enter reading mode');
    expect(enFocus.exitReadingMode).toBe('Exit reading mode');
    expect(zhFocus.enterReadingMode).toBe('进入阅读模式');
    expect(zhFocus.exitReadingMode).toBe('退出阅读模式');
    expect(Object.keys(enFocus).sort()).toEqual(Object.keys(zhFocus).sort());
  });

  it('allows entry during a session switch and exits only for a settled empty target', () => {
    const app = source('../src/focus/FocusApp.vue');
    const readingModeOwner = source('../src/focus/focusReadingMode.ts');

    expect(app).toContain(`const canEnterReadingMode = computed(() => (
  currentDocumentAccessAvailable.value
  && client.initialized.value
  && Boolean(client.activeThreadId.value)
  && (client.conversationLoading.value || client.turns.value.length > 0)
));`);

    const activeThreadWatcher = between(
      app,
      'watch(client.activeThreadId,',
      'watch(currentDocumentAccessAvailable',
    );
    expect(activeThreadWatcher).toContain('if (!threadId) exitReadingMode();');
    expect(activeThreadWatcher).not.toContain("presentationMode.value = 'normal'");

    const settledEmptyWatcher = between(
      readingModeOwner,
      'watch(\n    [() => options.conversationLoading.value',
      'watch(\n    [\n      () => options.canEnter.value',
    );
    expect(settledEmptyWatcher).toContain(
      'if (readingMode.value && !loading && turnCount === 0) exitReadingMode();',
    );
    expect(settledEmptyWatcher).not.toContain("flush: 'sync'");

    const openDraft = between(
      app,
      'async function openWorkspaceDraft(workspace: string)',
      '\n}\n\nasync function handleSubmit',
    );
    expect(openDraft.indexOf('exitReadingMode();')).toBeLessThan(
      openDraft.indexOf('await client.openWorkspaceDraft(workspace);'),
    );

    const accessWatcher = between(
      app,
      'watch(currentDocumentAccessAvailable',
      'watch(conversationSearchVisible',
    );
    expect(accessWatcher).toContain('exitReadingMode();');
    expect(readingModeOwner).toContain("presentationMode.value = 'reading';");
    expect(readingModeOwner).toContain("presentationMode.value = 'normal';");
  });

  it('captures one document-local reading intent while the initial snapshot loads', () => {
    const app = source('../src/focus/FocusApp.vue');
    const loading = source('../src/components/GlobalLoading.vue');
    const readingModeOwner = source('../src/focus/focusReadingMode.ts');

    expect(readingModeOwner).toContain('const pendingReadingModeIntent = ref(false);');
    expect(readingModeOwner).not.toMatch(/localStorage|sessionStorage|STORAGE_KEYS/u);
    const request = between(
      readingModeOwner,
      'function requestReadingMode(): void {',
      '\n  }\n\n  function exitReadingMode',
    );
    expect(request).toContain('if (!options.documentAccessAvailable.value) return;');
    expect(request).toContain('if (options.canEnter.value) {');
    expect(request).toContain('pendingReadingModeIntent.value = true;');

    const intentWatcher = between(
      readingModeOwner,
      'watch(\n    [\n      () => options.canEnter.value',
      'watch(\n    () => options.documentAccessAvailable.value',
    );
    expect(intentWatcher).toContain('if (canEnter) {');
    expect(intentWatcher).toContain('enterReadingMode();');
    expect(intentWatcher).toContain('if (initialized && meta && !conversationLoading) {');
    expect(intentWatcher).toContain('pendingReadingModeIntent.value = false;');
    expect(intentWatcher).toContain("{ flush: 'sync' }");

    const accessWatcher = between(readingModeOwner, 'watch(\n    () => options.documentAccessAvailable.value', '\n\n  return {');
    expect(accessWatcher.indexOf('pendingReadingModeIntent.value = false;')).toBeLessThan(
      accessWatcher.indexOf('exitReadingMode();'),
    );
    expect(app).toContain(':reading-mode-requested="pendingReadingModeIntent"');
    expect(app).toContain('@request-reading-mode="requestReadingMode"');

    expect(loading).toContain('readingModeRequested?: boolean;');
    expect(loading).toContain('const emit = defineEmits<{ requestReadingMode: [] }>();');
    expect(loading).toContain(':disabled="readingModeRequested"');
    expect(loading).toContain("@click=\"emit('requestReadingMode')\"");
    expect(loading).toContain("'focus.readingModePending' : 'focus.enterReadingMode'");
    expect(enFocus.readingModePending).toBe('Waiting to enter reading mode…');
    expect(zhFocus.readingModePending).toBe('等待进入阅读模式…');
  });

  it('consumes, retains, and clears the pending intent at its lifecycle boundaries', () => {
    const canEnter = ref(false);
    const documentAccessAvailable = ref(true);
    const initialized = ref(false);
    const meta = ref<unknown | null>(null);
    const conversationLoading = ref(true);
    const turns = ref<unknown[]>([]);
    let dismissed = 0;
    const scope = effectScope();
    const mode = scope.run(() => useFocusReadingMode({
      canEnter,
      documentAccessAvailable,
      initialized,
      meta,
      conversationLoading,
      turns,
      dismissSwitcher: () => {},
      dismissChrome: () => { dismissed += 1; },
    }))!;

    mode.requestReadingMode();
    expect(mode.pendingReadingModeIntent.value).toBe(true);
    initialized.value = true;
    conversationLoading.value = false;
    expect(mode.pendingReadingModeIntent.value).toBe(true);

    turns.value = [{}];
    canEnter.value = true;
    expect(mode.pendingReadingModeIntent.value).toBe(false);
    expect(mode.readingMode.value).toBe(true);
    expect(dismissed).toBe(1);

    mode.exitReadingMode();
    canEnter.value = false;
    mode.requestReadingMode();
    meta.value = {};
    expect(mode.pendingReadingModeIntent.value).toBe(false);

    meta.value = null;
    mode.requestReadingMode();
    documentAccessAvailable.value = false;
    expect(mode.pendingReadingModeIntent.value).toBe(false);
    scope.stop();
  });

  it('keeps draft/submission owners mounted and reveals input before imperative focus', () => {
    const app = source('../src/focus/FocusApp.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');
    const dock = source('../src/components/chat/ChatDock.vue');
    const composer = source('../src/components/chat/Composer.vue');

    expect(composer).toContain('requestInput: [];');
    expect(dock).toContain('requestInput: [];');
    expect(dock).toContain("@request-input=\"emit('requestInput')\"");
    expect(pane.match(/@request-input="emit\('exitReadingMode'\)"/gu)).toHaveLength(2);

    expect(composer).toMatch(
      /function loadForEdit\(value: string\): void \{\s+emit\('requestInput'\);\s+requestSurfaceMode\('compact'\);/u,
    );
    expect(composer).toMatch(
      /function focus\(\): void \{\s+emit\('requestInput'\);\s+requestSurfaceMode\('compact'\);\s+void nextTick/u,
    );
    const recovery = between(
      composer,
      'function loadRecovery(value: string): boolean {',
      '\n}\ndefineExpose',
    );
    expect(recovery.indexOf("if (text.value !== '' || attachments.value.length > 0) return false;"))
      .toBeLessThan(recovery.indexOf('loadForEdit(value);'));

    expect(pane).toContain(
      "if (dragging && props.readingMode) emit('exitReadingMode');",
    );
    expect(pane).toContain(
      "if (count > previous && props.readingMode) emit('exitReadingMode');",
    );
    expect(pane).toContain(':surface-mode="readingMode ? \'hidden\' : composerSurfaceMode"');
    expect(pane).toContain('const composerSurfaceMode = ref<ComposerSurfaceMode>(\'compact\');');

    const readingModeOwner = source('../src/focus/focusReadingMode.ts');
    const enter = between(readingModeOwner, 'function enterReadingMode(): void {', '\n  }\n\n  function requestReadingMode');
    const exit = between(readingModeOwner, 'function exitReadingMode(): void {', '\n  }\n\n  watch(');
    expect(readingModeOwner).toContain('.find((button) => button.offsetParent !== null)');
    expect(enter).not.toContain('focusComposer');
    expect(exit).not.toContain('focusComposer');
  });
});
