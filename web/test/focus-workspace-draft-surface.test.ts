import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

describe('Focus targetless workspace draft surface', () => {
  it('defines the responsive shell as viewport width rather than device type', () => {
    const viewport = source('../src/composables/useNarrowViewport.ts');
    const app = source('../src/focus/FocusApp.vue');

    expect(viewport).toContain('export const NARROW_VIEWPORT_MAX_WIDTH = 640;');
    expect(viewport).toContain('window.matchMedia(NARROW_VIEWPORT_QUERY)');
    expect(viewport).toContain('export function useNarrowViewport(): Ref<boolean>');
    expect(viewport).not.toMatch(/navigator|userAgent|touchPoints/u);
    expect(app).toContain('const isNarrowViewport = useNarrowViewport();');
    expect(app).not.toMatch(/\b(?:isMobile|useIsMobile|MobileTopBar|MobileSwitcherSheet)\b/u);
  });

  it('uses one responsive ConversationPane for wide and narrow empty composers', () => {
    const app = source('../src/focus/FocusApp.vue');

    expect(app.match(/<ConversationPane\b/gu)).toHaveLength(1);
    expect(app).toContain(':narrow-viewport="isNarrowViewport"');
    expect(app).toContain(':session-id="client.activeThreadId.value"');
    expect(app).toContain(':composer-ready="client.scopeReady.value"');
    expect(app).toContain(':status="client.status.value"');
    expect(app).toContain(
      ':draft-create-outcome-unknown="client.unknownThreadCreateDraftExists.value"',
    );
  });

  it('shows the targetless Composer only when no thread is selected', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const app = source('../src/focus/FocusApp.vue');

    expect(pane).toContain('const showTargetlessComposer = computed(() => (');
    expect(pane).toContain('!props.sessionId');
    expect(pane).toContain('&& props.turns.length === 0');
    expect(pane).toContain('&& !props.sessionLoading');
    expect(pane.match(/v-if="[^"]*showTargetlessComposer[^"]*"/gu)).toHaveLength(3);
    expect(pane).not.toContain('turns.length === 0 && !sessionLoading');
    expect(app).toContain(':session-loading="client.conversationLoading.value"');
  });

  it('shows the exact confirmed targetless cwd without treating workspace inventory as authority', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');

    expect(pane).toContain('return w?.name || props.workspaceName || props.status.cwd;');
    expect(pane).toContain('!props.sessionId');
    expect(pane).toContain('&& props.composerReady');
    expect(pane).toContain('&& !props.starting');
    expect(pane).toContain('&& !props.draftCreateOutcomeUnknown');
    expect(pane).toContain('&& !!props.status.cwd');
    expect(pane).toContain("t('focus.newConversationCwdHint', { path: status.cwd })");
  });

  it('keeps the next-conversation hint hidden after a create has an unknown outcome', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const app = source('../src/focus/FocusApp.vue');

    expect(pane).toContain('draftCreateOutcomeUnknown?: boolean;');
    expect(pane).toContain('&& !props.draftCreateOutcomeUnknown');
    expect(app).toContain(
      ':draft-create-outcome-unknown="client.unknownThreadCreateDraftExists.value"',
    );
  });

  it('keeps the cwd, workspace-picker, and /cd guidance synchronized in English and Chinese', () => {
    const en = source('../src/i18n/locales/en/focus.ts');
    const zh = source('../src/i18n/locales/zh/focus.ts');

    expect(en).toContain(
      "newConversationCwdHint: 'Working directory: {path}. Choose an existing workspace above, or enter /cd <directory> to use another directory on the Focus host; this affects only the next new conversation.'",
    );
    expect(zh).toContain(
      "newConversationCwdHint: '工作目录：{path}。可从上方选择已有工作区，或输入 /cd <目录> 使用 Focus 主机上的其他目录；只影响下一次新会话。'",
    );
  });
});
