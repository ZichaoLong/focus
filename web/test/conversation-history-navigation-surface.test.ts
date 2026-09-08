import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

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

function expectBefore(value: string, first: string, second: string): void {
  const firstIndex = value.indexOf(first);
  const secondIndex = value.indexOf(second, firstIndex);
  expect(firstIndex).toBeGreaterThanOrEqual(0);
  expect(secondIndex).toBeGreaterThan(firstIndex);
}

describe('ConversationPane bounded history navigation surface', () => {
  it('accepts an external outline while retaining the local-turn fallback', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');

    expect(pane).toContain('conversationTocItems?: ConversationTocItem[];');
    expect(pane).toContain(
      'resolveConversationTocTarget?: (turnId: string) => Promise<boolean>;',
    );
    expect(pane).toContain('cancelConversationTocTarget?: () => void;');
    expect(pane).toContain(
      '() => props.conversationTocItems ?? localConversationTocItems.value',
    );
    expect(pane).toContain(':items="displayedConversationTocItems"');
  });

  it('surfaces the external outline limit in both locales', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const toc = source('../src/components/chat/ConversationToc.vue');
    const en = source('../src/i18n/locales/en/conversation.ts');
    const zh = source('../src/i18n/locales/zh/conversation.ts');

    expect(pane).toContain('conversationTocTruncated?: boolean;');
    expect(pane).toContain(':truncated="conversationTocTruncated"');
    expect(toc).toContain('truncated?: boolean;');
    expect(toc).toContain('v-if="truncated" class="toc-truncated"');
    expect(toc).toContain("t('conversation.tocTruncated')");
    expect(toc).toContain("t('conversation.loadMoreOutline')");
    expect(pane).toContain(':has-more="conversationTocHasMore"');
    expect(pane).toContain('@load-more="loadMoreConversationToc?.()"');
    expect(en).toContain("tocTruncated: 'Only the latest 200 prompts are shown'");
    expect(zh).toContain("tocTruncated: '仅显示最近 200 条 Prompt'");
  });

  it('keeps the wide-rail load-more control above its transparent hover bridge', () => {
    const toc = source('../src/components/chat/ConversationToc.vue');
    const hoverBridge = between(toc, '.conversation-toc::before {', '\n}');
    const loadMoreControl = between(toc, '.toc-more {', '\n}');

    expect(hoverBridge).toContain('z-index: 0;');
    expect(loadMoreControl).toContain('position: relative;');
    expect(loadMoreControl).toContain('z-index: 1;');
    expect(toc).toContain('@click="emit(\'loadMore\')"');
  });

  it('keeps the wide rail and adds one shared compact Prompt history dialog', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const toc = source('../src/components/chat/ConversationToc.vue');
    const en = source('../src/i18n/locales/en/conversation.ts');
    const zh = source('../src/i18n/locales/zh/conversation.ts');

    expect(toc).toContain('const railVisible = computed(');
    expect(toc).toContain('const dialogAvailable = computed(');
    expect(toc).toContain('const compactVisible = computed(');
    expect(toc).toContain('props.inlineVisible !== false');
    expect(toc).toContain('(props.mobile || !fits.value)');
    expect(toc).toContain('v-if="railVisible"');
    expect(toc).toContain('v-if="compactVisible"');
    expect(toc).toContain('class="toc-compact-trigger"');
    expect(toc).toContain('<Dialog');
    expect(toc).toContain('<Menu class="toc-compact-list"');
    expect(toc).toContain('<MenuItem');
    expect(toc).toContain("t('conversation.promptHistory')");
    expect(pane).toContain(':select-target="scrollToTurn"');
    expect(en).toContain("promptHistory: 'Prompt history'");
    expect(zh).toContain("promptHistory: 'Prompt 历史'");

    const compactVisibility = between(
      toc,
      'const compactVisible = computed(',
      'async function selectItem',
    );
    expect(compactVisibility).not.toContain('occluded');
  });

  it('shares the compact dialog with an external reading-mode trigger', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const toc = source('../src/components/chat/ConversationToc.vue');

    expect(toc).toContain('inlineVisible?: boolean;');
    expect(toc).toContain('function openCompactDialog(): void {');
    expect(toc).toContain('if (dialogAvailable.value) compactOpen.value = true;');
    expect(toc).toContain('defineExpose({ openCompactDialog });');
    expect(toc).toContain('compactVisible,');
    expect(toc).toContain('if (!isVisible) compactOpen.value = false;');
    expect(toc).toContain('dialogAvailable,');
    expect(toc).toContain('if (!isAvailable) compactOpen.value = false;');
    expect(toc).toContain('watch(() => props.inlineVisible !== false');
    expect(toc).toContain('@click="openCompactDialog"');
    expect(pane).toContain('ref="conversationTocRef"');
    expect(pane).toContain(':inline-visible="!readingMode"');
    expect(pane).toContain('conversationTocRef.value?.openCompactDialog();');
    expect(pane).toContain('openPromptHistory,');
  });

  it('closes the compact dialog only after the latest target is installed', () => {
    const toc = source('../src/components/chat/ConversationToc.vue');
    const handler = between(
      toc,
      'async function selectItem(turnId: string): Promise<void> {',
      '// The nav is rendered only while',
    );

    const awaitResolver = handler.indexOf(
      'installed = await props.selectTarget(turnId);',
    );
    const closeAfterReceipt = handler.indexOf(
      'if (installed && generation === selectionGeneration) compactOpen.value = false;',
    );

    expect(awaitResolver).toBeGreaterThanOrEqual(0);
    expect(closeAfterReceipt).toBeGreaterThan(awaitResolver);
    expect(handler).toContain("else emit('select', turnId);");

    const dismissalFence = between(
      toc,
      '// A historical resolver may outlive an Esc/overlay/close-button dismissal.',
      'onBeforeUnmount(() =>',
    );
    expect(dismissalFence).toContain('watch(');
    expect(dismissalFence).toContain('compactOpen,');
    expect(dismissalFence).toContain('if (wasOpen && !isOpen) selectionGeneration += 1;');
    expect(dismissalFence).toContain("{ flush: 'sync' }");
  });

  it('keeps the mobile Prompt trigger below the separate mobile top bar', () => {
    const app = source('../src/focus/FocusApp.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');
    const toc = source('../src/components/chat/ConversationToc.vue');
    const topBar = source('../src/components/mobile/MobileTopBar.vue');

    const mobileTopBar = app.indexOf('<MobileTopBar');
    const main = app.indexOf('<main class="focus-main">', mobileTopBar);
    const conversationPane = app.indexOf('<ConversationPane', main);
    expect(mobileTopBar).toBeGreaterThanOrEqual(0);
    expect(main).toBeGreaterThan(mobileTopBar);
    expect(conversationPane).toBeGreaterThan(main);
    expect(app).toContain('.focus-app.mobile {\n  display: flex;\n  flex-direction: column;');
    expect(topBar).toContain('height: calc(50px + var(--safe-top));');
    expect(pane).toContain('position: relative;\n  container-type: inline-size;');
    expect(toc).toContain('.toc-compact-trigger.is-mobile { top: var(--space-3); }');
  });

  it('routes Prompt targets through one resolver-and-scroll intent owner', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const app = source('../src/focus/FocusApp.vue');
    const client = source('../src/focus/useFocusWebClient.ts');
    const owner = between(
      pane,
      'const promptNavigation = createPromptNavigationIntent<',
      'async function scrollToTurn(turnId: string): Promise<boolean> {',
    );
    const handlers = between(
      pane,
      'async function scrollToTurn(turnId: string): Promise<boolean> {',
      '// --- Scroll anchoring for expand/collapse interactions',
    );

    expect(owner).toContain('resolveTarget: async (turnId) => (');
    expect(owner).toContain('props.resolveConversationTocTarget(turnId)');
    expect(owner).toContain('cancelTargetResolution: () => props.cancelConversationTocTarget?.()');
    expect(owner).toContain('flushRender: async () => { await nextTick(); }');
    expect(owner).toContain('locateTarget: (turnId) => {');
    expect(owner).toContain('const paneRect = pane.getBoundingClientRect();');
    expect(owner).toContain('const targetRect = target.getBoundingClientRect();');
    expect(owner).toContain('pane.scrollTo({');
    expect(owner).toContain('top: centeredPromptScrollTop({');
    expect(owner).toContain('scrollTop: pane.scrollTop');
    expect(owner).toContain('paneTop: paneRect.top');
    expect(owner).toContain('targetTop: targetRect.top');
    expect(owner).toContain("behavior: 'smooth',");
    expect(owner).not.toContain('scrollIntoView');
    expect(owner).toContain('stopScrollWrites: stopPromptCompetingScrollWrites');
    expect(owner).toContain('onActivityChange: onPromptNavigationActivity');
    expect(handlers).toContain('return promptNavigation.navigate(turnId);');
    expect(handlers).toContain('return promptNavigation.navigateRendered(turnId);');
    expect(app).toContain(':cancel-conversation-toc-target="client.cancelHistoryPromptTarget"');
    expect(client).toContain('cancelHistoryPromptTarget: historyNavigation.cancelDetailIntent');
  });

  it('does not treat programmatic Prompt navigation as permission to replace the page', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const chat = source('../src/components/chat/ChatPane.vue');
    const navigation = between(
      pane,
      'async function scrollToTurn(turnId: string): Promise<boolean> {',
      '// --- Scroll anchoring for expand/collapse interactions',
    );
    const userIntent = between(
      pane,
      'function stopFollowingForUserIntent(): void {',
      "function nestedScrollerCanMove(event: Event, direction: 'up' | 'down'): boolean",
    );
    const sentinel = between(
      chat,
      'function observeTopSentinel(): void {',
      'onMounted(observeTopSentinel);',
    );

    expect(pane).toContain('const historyAutoLoadArmed = ref(false);');
    expect(pane).toContain(':history-auto-load-armed="historyAutoLoadArmed"');
    expect(navigation).toContain('historyAutoLoadArmed.value = false;');
    expect(userIntent).toContain('historyAutoLoadArmed.value = true;');
    expect(chat).toContain('historyAutoLoadArmed?: boolean;');
    expect(sentinel).toContain('props.historyAutoLoadArmed');
    expect(sentinel).toContain("emit('loadOlderMessages', 'sentinel');");
    expect(sentinel).not.toContain('!props.isFollowing');

    const loader = between(
      pane,
      "async function handleLoadOlderMessages(source: 'sentinel' | 'button'): Promise<void> {",
      'function attrEscape(value: string)',
    );
    const authorization = loader.indexOf("source === 'button' || historyAutoLoadArmed.value");
    const consume = loader.indexOf('historyAutoLoadArmed.value = false;', authorization);
    const guard = loader.indexOf('if (!authorized) return;', consume);
    const captureLoader = loader.indexOf('const loadOlderMessages = props.loadOlderMessages;', guard);
    const fence = loader.indexOf('const fence = claimOrdinaryScrollAuthority();', captureLoader);
    const firstFlush = loader.indexOf('await nextTick();', fence);
    const preRequestFence = loader.indexOf(
      'if (!scrollWriteFenceIsCurrent(fence)) return;',
      firstFlush,
    );
    const request = loader.indexOf(
      'const installed = await loadOlderMessages(requestedSessionId);',
      preRequestFence,
    );
    const secondFlush = loader.indexOf('await nextTick();', request);
    const continuationFence = loader.indexOf(
      'if (!scrollWriteFenceIsCurrent(fence)) return;',
      secondFlush,
    );
    expect(authorization).toBeGreaterThanOrEqual(0);
    expect(consume).toBeGreaterThan(authorization);
    expect(guard).toBeGreaterThan(consume);
    expect(captureLoader).toBeGreaterThan(guard);
    expect(fence).toBeGreaterThan(captureLoader);
    expect(preRequestFence).toBeGreaterThan(firstFlush);
    expect(request).toBeGreaterThan(preRequestFence);
    expect(continuationFence).toBeGreaterThan(secondFlush);
  });

  it('gives active Prompt navigation exclusive ownership of following and anchoring', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const activity = between(
      pane,
      'function onPromptNavigationActivity(activity: PromptNavigationActivity): void {',
      'function restorePromptNavigationFailure',
    );
    const scroll = between(
      pane,
      'function onPanesScroll(): void {',
      'function onPanesScrollEnd(): void {',
    );
    const bottom = between(
      pane,
      'function scrollToBottom(smooth = false): void {',
      'async function handleReturnToLiveTail',
    );
    const stableFollow = between(
      pane,
      'function scheduleStableFollow(maxFrames = 36): void {',
      'type ScrollKey = {',
    );
    const mutation = between(
      pane,
      'function onContentMutated(): void {',
      'function onVisibilityChange(): void {',
    );

    expect(activity).toContain('following.value = false;');
    expect(activity).toContain('historyAutoLoadArmed.value = false;');
    expect(scroll).toContain('if (promptNavigation.ownsScroll()) {');
    expect(scroll.indexOf('if (promptNavigation.ownsScroll()) {')).toBeLessThan(
      scroll.indexOf('if (isPinned()) {'),
    );
    expect(bottom).toContain('if (promptNavigation.ownsScroll()) return;');
    expect(stableFollow).toContain(
      'if (historyLoadInProgress.value || promptNavigation.ownsScroll()) return;',
    );
    expect(pane).toContain(
      'const ordinaryFollowFrame = createConversationFollowFrame((mode) => {\n  if (historyLoadInProgress.value || promptNavigation.ownsScroll()) return;',
    );
    expect(mutation).toContain('promptNavigation.notifyLayoutChange();');
    expect(pane).toContain(
      'resizeObserver = new ResizeObserver(() => {\n        if (componentDisposed) return;\n        promptNavigation.notifyLayoutChange();',
    );
    expect(pane).toContain('@scrollend.passive="onPanesScrollEnd"');
    expect(pane).toContain("'prompt-navigation-active': promptNavigationActive");
    expect(pane).toContain('.panes.prompt-navigation-active {\n  overflow-anchor: none;');
  });

  it('fences deferred observer setup and callbacks after component disposal', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const lifecycle = between(
      pane,
      'onMounted(() => {',
      'function focusComposer(): void {',
    );

    expect(pane).toContain('let componentDisposed = false;');
    expect(lifecycle).toContain(
      'componentDisposed = false;\n  void nextTick(() => {\n    if (componentDisposed) return;',
    );
    expect(lifecycle).toContain(
      'resizeObserver = new ResizeObserver(() => {\n        if (componentDisposed) return;',
    );
    expect(lifecycle).toContain(
      'onUnmounted(() => {\n  componentDisposed = true;\n  if (contentObserver) contentObserver.disconnect();',
    );
  });

  it('fences ordinary async scroll writers and cancels Prompt ownership on global input', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const fences = between(
      pane,
      'let scrollWriteGeneration = 0;',
      '// Wheel, touch, and scrollbar input arrive before',
    );
    const keyboard = between(
      pane,
      'function onWindowKeydown(event: KeyboardEvent): void {',
      'function ensureContentObserved(): void {',
    );
    const userScrollAuthority = between(
      pane,
      'function claimUserScrollAuthority(): void {',
      '// Wheel, touch, and scrollbar input arrive before',
    );
    const touch = between(
      pane,
      'function onPanesTouchStart(event: TouchEvent): void {',
      'function onWindowKeydown(event: KeyboardEvent): void {',
    );
    const touchMove = between(
      pane,
      'function onPanesTouchMove(event: TouchEvent): void {',
      'function onWindowKeydown(event: KeyboardEvent): void {',
    );

    expect(fences).toContain('generation: scrollWriteGeneration');
    expect(fences).toContain('fence.generation === scrollWriteGeneration');
    expect(fences).toContain('fence.sessionId === props.sessionId');
    expect(fences).toContain('fence.reloadKey === props.fileReloadKey');
    expect(fences).toContain('fence.pane === panesRef.value');
    expect(fences).toContain('&& !promptNavigation.ownsScroll();');
    expect(fences).toContain('function claimOrdinaryScrollAuthority(): ScrollWriteFence {');
    expect(fences).toContain('promptNavigation.cancel();\n  scrollWriteGeneration += 1;');
    expect(userScrollAuthority).toContain(
      'if (historyLoadInProgress.value && !promptNavigation.ownsScroll()) {',
    );
    expect(userScrollAuthority).toContain('cancelOrdinaryScrollWrites();\n    return;');
    expect(userScrollAuthority).toContain('claimOrdinaryScrollAuthority();');
    expect(keyboard).toContain("['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)");
    expect(keyboard).toContain("event.key === 'PageUp'");
    expect(keyboard).toContain("event.key === 'End'");
    expect(keyboard).toContain('if (upward) stopFollowingForUserIntent();');
    expect(keyboard).toContain('claimUserScrollAuthority();');
    expect(touch).toContain('claimUserScrollAuthority();');
    expect(touchMove).not.toContain('claimUserScrollAuthority();');
    expect(pane).toContain("window.addEventListener('keydown', onWindowKeydown, true);");
    expect(pane).toContain("window.removeEventListener('keydown', onWindowKeydown, true);");
    expect(pane).toContain(
      'onUnmounted(() => {\n  componentDisposed = true;\n  if (contentObserver) contentObserver.disconnect();',
    );
    expect(pane).toContain('cancelScheduledFollow();\n  promptNavigation.cancel();');
  });

  it('keeps ordinary smooth following bounded by its cancellation guard', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const bottom = between(
      pane,
      'function scrollToBottom(smooth = false): void {',
      'async function handleReturnToLiveTail',
    );
    const stableFollow = between(
      pane,
      'function scheduleStableFollow(maxFrames = 36): void {',
      'type ScrollKey = {',
    );
    const scrollEnd = between(
      pane,
      'function onPanesScrollEnd(): void {',
      'function scrollToBottom(smooth = false): void {',
    );

    const instantGuard = bottom.indexOf(
      'if (!smooth && performance.now() < smoothScrollUntil) return;',
    );
    const armGuard = bottom.indexOf(
      'smoothScrollUntil = performance.now() + SMOOTH_SCROLL_GUARD_MS;',
      instantGuard,
    );
    const smoothWrite = bottom.indexOf(
      "el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });",
      armGuard,
    );
    expect(instantGuard).toBeGreaterThanOrEqual(0);
    expect(armGuard).toBeGreaterThan(instantGuard);
    expect(smoothWrite).toBeGreaterThan(armGuard);
    expect(stableFollow).toContain(
      'performance.now() < smoothScrollUntil\n      || (stableFrames < 3 && frames < maxFrames)',
    );
    expect(scrollEnd).toContain('if (promptNavigation.notifyLayoutChange()) return;');
    expect(scrollEnd).toContain('scheduleStableFollow(8);');
  });

  it('bounds scrollbar intent by pointer identity, final direction, and lost release', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const drag = between(
      pane,
      'function abandonScrollbarDrag(): void {',
      'let lastTouchY: number | null = null;',
    );

    expect(drag).toContain('event.pointerId !== drag.pointerId');
    expect(drag).toContain('finalTop < drag.startTop - 1');
    expect(drag).toContain('finalTop > drag.startTop + 1');
    expect(drag).toContain('abandonScrollbarDrag();');
    expect(drag).toContain('startTop: el.scrollTop');
    expect(pane).toContain("window.addEventListener('blur', onWindowBlur);");
    expect(pane).toContain("window.removeEventListener('blur', onWindowBlur);");
  });

  it('leaves a replacement history window before following the rendered live tail', () => {
    const client = source('../src/focus/useFocusWebClient.ts');
    const app = source('../src/focus/FocusApp.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');

    const clientHandler = between(
      client,
      'function returnToLiveTail(): void {',
      'let turnWindowChangeGeneration',
    );
    expect(clientHandler).toContain('historyNavigation.clearHistoryWindow();');
    expect(client).toContain('returnToLiveTail,');
    expect(app).toContain(':return-to-live-tail="client.returnToLiveTail"');
    expect(pane).toContain('returnToLiveTail?: () => void;');

    const paneHandler = between(
      pane,
      'async function handleReturnToLiveTail(): Promise<void> {',
      'async function handleLoadOlderMessages',
    );
    const clearWindow = paneHandler.indexOf('props.returnToLiveTail?.();');
    const renderTick = paneHandler.indexOf('await nextTick();', clearWindow);
    const scroll = paneHandler.indexOf('scrollToBottom(true);', renderTick);
    const settle = paneHandler.indexOf('scheduleStableFollow(16);', scroll);
    expect(clearWindow).toBeGreaterThanOrEqual(0);
    expect(renderTick).toBeGreaterThan(clearWindow);
    expect(scroll).toBeGreaterThan(renderTick);
    expect(settle).toBeGreaterThan(scroll);
    expect(pane).toContain('viewingHistory?: boolean;');
    expect(app).toContain(':viewing-history="client.viewingHistory.value"');
    expect(pane).toContain('v-if="showPill || viewingHistory || promptNavigationActive"');
    expect(pane).toContain('@click="handleReturnToLiveTail"');
  });

  it('cancels Prompt ownership before opening conversation search', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const handler = between(
      pane,
      'function handleConversationSearch(): void {',
      '// --- Scroll anchoring for expand/collapse interactions',
    );

    const claim = handler.indexOf('claimOrdinaryScrollAuthority();');
    const disarm = handler.indexOf('historyAutoLoadArmed.value = false;', claim);
    const open = handler.indexOf("emit('searchConversation');", disarm);
    expect(claim).toBeGreaterThanOrEqual(0);
    expect(disarm).toBeGreaterThan(claim);
    expect(open).toBeGreaterThan(disarm);
    expect(pane).toContain('@search="handleConversationSearch"');
  });

  it('prepares every timeline-producing dock mutation before emitting it', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const handlers = between(
      pane,
      'function handleQuestionAnswer(qid: string, resp: QuestionResponse): void {',
      'let contentObserver: MutationObserver | null = null;',
    );
    const questionAnswer = between(
      handlers,
      'function handleQuestionAnswer',
      'function handleQuestionDismiss',
    );
    const questionDismiss = between(
      handlers,
      'function handleQuestionDismiss',
      'function handleApproval',
    );
    const approval = between(handlers, 'function handleApproval', 'function handleCompact');
    const compact = between(handlers, 'function handleCompact', 'function handleControlGoal');
    const goal = between(
      pane,
      'function handleControlGoal',
      'let contentObserver: MutationObserver | null = null;',
    );

    expectBefore(
      questionAnswer,
      'followAfterUserAction();',
      "emit('answer', qid, resp);",
    );
    expectBefore(
      questionDismiss,
      'followAfterUserAction();',
      "emit('dismiss', qid);",
    );
    expectBefore(
      approval,
      'followAfterUserAction();',
      "emit('approval', id, response);",
    );
    expectBefore(
      compact,
      'followAfterUserAction();',
      "emit('compact');",
    );
    expect(goal).toContain("if (action === 'resume') followAfterUserAction();");
    expect(goal).not.toContain("action === 'pause'");
    expect(goal).not.toContain("action === 'cancel'");
    expect(pane).toContain('@dismiss="handleQuestionDismiss"');
    expect(pane).toContain('@approval="handleApproval"');
    expect(pane).toContain('@control-goal="handleControlGoal"');
    expect(pane).toContain('@compact="handleCompact"');
  });

  it('prepares confirmed goal and review effects without moving on dialog open', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const app = source('../src/focus/FocusApp.vue');
    const goal = between(
      app,
      'async function submitGoal(objective: string): Promise<void> {',
      'async function submitReview',
    );
    const review = between(
      app,
      'async function submitReview(target: Record<string, unknown>): Promise<void> {',
      'let appHeightRaf',
    );

    expect(pane).toContain('prepareTimelineMutation: followAfterUserAction,');
    expectBefore(
      goal,
      'conversationPaneRef.value?.prepareTimelineMutation();',
      'await client.createGoal(objective);',
    );
    expectBefore(
      review,
      'conversationPaneRef.value?.prepareTimelineMutation();',
      'await client.review(target);',
    );
    expect(app).toContain('@goal-session="showGoalDialog = true"');
    expect(app).toContain('@review-session="showReviewDialog = true"');
  });

  it('keeps an invisible DOM anchor for a Prompt with no visible user content', () => {
    const pane = source('../src/components/chat/ChatPane.vue');

    expect(pane).toContain('function userTurnHasPresentation(turn: ChatTurn): boolean');
    expect(pane).toContain('v-if="userTurnHasPresentation(turn)" class="u-turn"');
    expect(pane).toContain('class="turn-anchor empty-user-anchor"');
    expect(pane).toContain(':data-turn-id="turn.id"');
    expect(pane).toContain('aria-hidden="true"');
  });

  it('lands replacement-style top loads at the new page bottom without prepend restoration', () => {
    const pane = source('../src/components/chat/ConversationPane.vue');
    const handler = between(
      pane,
      "async function handleLoadOlderMessages(source: 'sentinel' | 'button'): Promise<void> {",
      'function attrEscape(value: string)',
    );

    const load = handler.indexOf('const installed = await loadOlderMessages(requestedSessionId);');
    const renderTick = handler.indexOf('await nextTick();', load);
    const continuationGuard = handler.indexOf(
      'if (!scrollWriteFenceIsCurrent(fence)) return;',
      renderTick,
    );
    const receiptGuard = handler.indexOf('if (!installed) return;', continuationGuard);
    const stopFollowing = handler.indexOf('following.value = false;', receiptGuard);
    const revealLatest = handler.indexOf('showPill.value = true;', stopFollowing);
    const bottom = handler.indexOf('el2.scrollTop = el2.scrollHeight;', revealLatest);

    expect(load).toBeGreaterThanOrEqual(0);
    expect(renderTick).toBeGreaterThan(load);
    expect(continuationGuard).toBeGreaterThan(renderTick);
    expect(receiptGuard).toBeGreaterThan(continuationGuard);
    expect(stopFollowing).toBeGreaterThan(receiptGuard);
    expect(revealLatest).toBeGreaterThan(stopFollowing);
    expect(bottom).toBeGreaterThan(revealLatest);
    expect(pane).toContain("'history-loading': historyLoadInProgress");
    expect(pane).toContain('historyLoadInProgress.value || promptNavigation.ownsScroll()');
    expect(pane).not.toContain('HistoryScrollSnapshot');
    expect(pane).not.toContain('pendingHistoryRestoreBySession');
    expect(pane).not.toContain('historyScrollDelta');
    expect(pane).not.toContain('history-prepending');
  });
});
