import { saveReadingBookmark, threadReading } from '../components/chat/readingBookmark';
import { documentReloadDelay, isFocusSessionRejection, reserveDocumentReload } from './documentRecovery';
import { checkpointThread, hasMobileFeature, recoveryStorage } from '../lib/mobileHost';
import { computed, ref, watch } from 'vue';
import { i18n } from '../i18n';
import { FocusWebApi, type FocusWebApiPort } from './api';
import { ClientIntentClock } from './clientIntentClock';
import { decodeFocusOperatorStatus } from './projectionEventDecoder';
import { createFocusTransportSession } from './focusTransportSession';
import { createFocusClientView } from './focusClientView';
import {
  createFocusBackendResetTransaction,
  type FocusBackendResetExecutionOutcome,
} from './focusBackendReset';
import {
  createFocusMutationActions,
  type FocusMutationActions,
} from './mutations/actions';
export type {
  UnknownLifecycleMutation,
  UnknownProcessLocalMutation,
  UnknownSubmissionDraft,
  UnknownSubmissionHandoff,
} from './mutations/actions';
import { createFocusProjectionSync } from './focusProjectionSync';
import type { FocusProjectionSync } from './focusProjectionSync';
import { createFocusHistoryNavigation } from './focusHistoryNavigation';
import { createFocusTranscript } from './focusTranscript';
import { createFocusPromptHistory } from './focusPromptHistory';
import {
  createFocusNavigationProfile,
} from './focusNavigationProfile';
import { createWebNextTurnSettings } from './client-state/web-next-turn-settings';
import { createDataRetention } from './client-state/data-retention';
import { createBrowserTurnWindow } from './client-state/browser-turn-window';
import { createThreadInspection } from './client-state/thread-inspection';
import { createRuntimeNoticeOwner } from './client-state/runtime-notices';
import { FocusPromptError } from './webPromptDiagnostic';
import type { WebPromptResultLocator } from './webPromptResultLocators';
import {
  FocusApiError,
  isStaleWebReadError,
  type FocusMeta,
  type FocusForkResult,
  type FocusHistoryEditPrompt,
  type FocusOperatorStatus,
  type FocusOperatorStatusFreshness,
  type FocusUpdateStatus,
  type FocusSummaryExportSelection,
} from './types';

const THREAD_QUERY_KEY = 'thread';
export { AUTO_MODEL_ID } from './focusClientView';
const DEFAULT_OPERATOR_STATUS_POLL_MS = 15_000;
const MIN_OPERATOR_STATUS_POLL_MS = 1_000;
const MAX_OPERATOR_STATUS_POLL_MS = 60_000;
const UPDATE_RECONNECT_TIMEOUT_MS = 120_000;

function updateThreadQuery(threadId: string): void {
  const url = new URL(window.location.href);
  if (threadId) url.searchParams.set(THREAD_QUERY_KEY, threadId);
  else url.searchParams.delete(THREAD_QUERY_KEY);
  history.replaceState(history.state, '', `${url.pathname}${url.search}`);
}

export function useFocusWebClient(api: FocusWebApiPort = new FocusWebApi()) {
  // The Gateway may replace a copied sessionStorage hint with a distinct
  // writer identity. Keep the acknowledged identity reactive so two tabs on
  // the same thread never share one localStorage composer key.
  const operatorStatus = ref<FocusOperatorStatus | null>(null);
  const operatorStatusFreshness = ref<FocusOperatorStatusFreshness>('loading');
  const operatorStatusStale = computed(() => operatorStatusFreshness.value === 'stale');
  const dataRetention = createDataRetention(api);
  const initialized = ref(false);
  const loading = ref(false);
  const summaryExporting = ref(false);
  const threadDataExporting = ref(false);
  const updateStatus = ref<FocusUpdateStatus | null>(null);
  const updateLoading = ref(false);
  const updateBusy = ref(false);
  const updateStatusStale = ref(false);
  const updateNotice = ref('');
  const updateObservedAt = ref(0);
  const updateApplyStarted = ref(false);
  const updateOperationActive = computed(() => (
    updateStatus.value?.state === 'checking' || updateStatus.value?.state === 'cancelling'
    || updateStatus.value?.state === 'applying'
    || updateApplyStarted.value
  ));
  const updateActionsDisabled = computed(() => (
    updateBusy.value || updateLoading.value || updateOperationActive.value
    || updateStatusStale.value || updateStatus.value?.state === 'unknown'
  ));
  const authRequired = ref(false);
  let parked = false;
  const outerAuthRequired = ref(false);
  // A copied/reloaded document can lose its memory-only document capability
  // while another document keeps the resumable client hint.  Do not keep
  // retrying that stale capability: a browser reload must register a fresh
  // document identity first.
  const documentFailure = ref<'document_replaced' | 'document_unregistered' | null>(null);
  const documentReloadRequired = computed(() => documentFailure.value !== null);
  const errorPresentation = ref({ message: '', diagnostic: '' });
  const forkNotes = ref<Record<string, FocusForkResult>>({});
  const historyEdits = ref<Record<string, { prompt: FocusHistoryEditPrompt; restoreAutomatically: boolean }>>({});
  let promptErrorLocator: WebPromptResultLocator | null = null;
  const errorMessage = computed(() => errorPresentation.value.message);
  let operatorStatusTimer: ReturnType<typeof setTimeout> | null = null;
  let operatorStatusRefreshPromise: Promise<void> | null = null;
  let updatePollTimer: ReturnType<typeof setTimeout> | null = null;
  let updateReloadTimer: ReturnType<typeof setTimeout> | null = null;
  let updateApplyStartedAt = 0;
  const intentClock = new ClientIntentClock();
  const turnWindow = createBrowserTurnWindow();
  let projection!: FocusProjectionSync;
  let transcript: ReturnType<typeof createFocusTranscript>;
  let promptHistory: ReturnType<typeof createFocusPromptHistory>;
  let mutationActions!: FocusMutationActions;
  let clearHistoryView = (): void => {};
  const settings = createWebNextTurnSettings({
    api,
    modelIsAvailable: (modelId) => (
      modelId === 'focus:auto'
      || projection?.meta.value?.models.some((model) => model.id === modelId) === true
    ),
    supportedReasoningEfforts: (modelId) => (
      projection?.meta.value?.models
        .find((model) => model.id === modelId)
        ?.supported_reasoning_efforts
        .map((option) => option.effort) ?? []
    ),
    runtimeEpochMismatch: () => projection?.invalidateWireProjection(),
    reportError,
  });
  const navigation = createFocusNavigationProfile({
    intentClock,
    api,
    initialClientId: api.clientId,
    defaultWorkspace: () => projection.meta.value?.default_working_dir ?? '',
    clearSnapshot: () => projection.clearSnapshot(),
    clearHistoryView: () => clearHistoryView(),
    updateThreadQuery,
    reportError,
    clearError,
    setNavigationLoading: (value) => {
      loading.value = value;
    },
    threadUnavailableReason: (threadId) => {
      const listed = projection.threads.value.find((thread) => thread.id === threadId);
      return listed?.selectable === false
        ? listed.unavailable_reason
          || `Open this thread from Focus instance ${listed.loaded_instance || 'that owns it'}.`
        : '';
    },
    workspaceNavigationBlockReason: () => (
      activeThreadId.value
      && mutationActions.owner.value.relation === 'self'
      && (
        mutationActions.running.value
        || (snapshot.value?.pending_requests.length ?? 0) > 0
      )
        ? 'Wait for this browser-owned operation to finish before starting a new workspace conversation.'
        : ''
    ),
  });
  const {
    threadScope,
    activeThreadId,
    draftWorkspaceId,
    scopeReady,
    composerReady,
  } = navigation;
  const stopThreadCheckpoint = watch([initialized, scopeReady, activeThreadId], ([ready, confirmed, thread]) => {
    if (ready && confirmed) checkpointThread(thread);
  });
  const runtimeNotices = createRuntimeNoticeOwner(activeThreadId);
  projection = createFocusProjectionSync({
    api,
    intentClock,
    turnWindowLimit: turnWindow.limit,
    navigation,
    settings,
    onTranscriptDelta: (event, detail) => { transcript?.handleDelta(event, detail); promptHistory?.handleDelta(detail); },
    onHistoryInvalidated: () => {
      clearHistoryView();
      promptHistory?.reset();
      threadInspection.clearToolDetail();
      threadInspection.clearSearch();
    },
    onProjectionReload: () => {
      if (transcript?.enabled.value) transcript.prepareReload();
      else clearHistoryView();
      promptHistory?.reset();
      threadInspection.clearToolDetail();
      threadInspection.clearSearch();
    },
    transport: {
      hasOpenedEventSocket: () => transportSession.snapshot.value.hasOpenedEventSocket,
      requestProjectionReload: () => transportSession.requestProjectionReload(),
      scheduleProjectionReloadRetry: () => transportSession.scheduleProjectionReloadRetry(),
      cancelProjectionReloadRetry: () => transportSession.cancelProjectionReloadRetry(),
      resetProjectionReloadBackoff: () => transportSession.resetProjectionReloadBackoff(),
      scheduleProjectionRefresh: () => transportSession.scheduleProjectionRefresh(),
      scheduleThreadListRefresh: () => transportSession.scheduleThreadListRefresh(),
    },
    reportError,
    requireAuthentication,
    projectionAccessIsAvailable: () => !authRequired.value && !documentReloadRequired.value,
    currentErrorMessage: () => errorMessage.value,
    clearErrorMessageIf: (message) => {
      if (message && errorMessage.value === message) clearError();
    },
    activeThreadWasRemoved: () => {
      navigation.clearToRepairDraft(
        workspacesView.value[0]?.id || meta.value?.default_working_dir || '',
      );
    },
    captureUnknownMutationSnapshot: (threadId) => (
      mutationActions.captureUnknownMutationSnapshot(threadId)
    ),
    reconcileUnknownMutation: (receipt, mutation) => {
      return mutationActions.reconcileUnknownMutation(receipt, mutation);
    },
    settleUnknownMutationFromEvent: (threadId, mutationId, operation, disposition) => {
      mutationActions.settleUnknownMutationFromEvent(
        threadId,
        mutationId,
        operation,
        disposition,
      );
    },
  });
  navigation.bindProjection(projection);
  const {
    meta: metaEnvelope,
    threads,
    searchThreads,
    archivedThreads,
    snapshot,
    runtimeEpoch,
    revision,
    snapshotInvalidated,
    archivedLoading,
    archivedTruncated,
    archivedLimit,
    reloadInFlight,
  } = projection;
  transcript = createFocusTranscript({
    api, snapshot, activeThreadId,
    savedReadingItem: thread => threadReading(thread)?.bookmark ?? null,
    forgetReadingItem: (thread, turn, item) => {
      const saved = threadReading(thread)?.bookmark;
      if (saved?.turn === turn && saved.item === item) saveReadingBookmark(thread, null);
    },
    reportFatalError,
    isDisposed: () => navigation.isDisposed || authRequired.value || documentReloadRequired.value,
  });
  // Request loading can finish before a covering snapshot is installed when
  // navigation converges through fresh metadata and projection recovery stays
  // in the background. Keep that selected target in an honest loading state;
  // only an authoritative targetless profile may expose the new-chat surface.
  const conversationLoading = computed(() => (
    loading.value
    || (transcript.enabled.value && transcript.loading.value && transcript.turns.value.length === 0)
    || (
      activeThreadId.value !== ''
      && snapshot.value?.thread.id !== activeThreadId.value
    )
  ));
  promptHistory = createFocusPromptHistory({ api, snapshot, enabled: transcript.enabled, reportError,
    isDisposed: () => navigation.isDisposed || authRequired.value || documentReloadRequired.value });
  const historyNavigation = createFocusHistoryNavigation({
    api,
    snapshot: computed(() => transcript.enabled.value ? null : snapshot.value),
    activeThreadId,
    turnLimit: turnWindow.limit,
    reportError,
    isDisposed: () => navigation.isDisposed,
  });
  clearHistoryView = () => { historyNavigation.clearHistoryWindow(); transcript.reset(); };
  const meta = computed<FocusMeta | null>(() => {
    const envelope = metaEnvelope.value;
    const writerProfile = navigation.writerProfile.value;
    const nextTurnSettings = settings.snapshot.value;
    return envelope && writerProfile && nextTurnSettings
      ? {
          ...envelope,
          writer_profile: writerProfile,
          next_turn_settings: nextTurnSettings,
        }
      : null;
  });
  const threadInspection = createThreadInspection({
    api,
    metaCapabilities: computed(() => {
      const capabilities = metaEnvelope.value?.capabilities;
      return capabilities
        ? {
            tool_detail: capabilities.tool_detail,
            history_search: capabilities.history_search,
          }
        : null;
    }),
    accessAvailable: computed(() => (
      !authRequired.value && !documentReloadRequired.value
    )),
    snapshot,
    activeThreadId,
    resolveTurnCursorTarget: (cursor, turnId, itemId) => transcript.enabled.value
      ? transcript.locate(turnId, itemId)
      : historyNavigation.resolveTurnCursorTarget(cursor, turnId),
    cancelTurnCursorTarget: () => { transcript.cancelTarget(); historyNavigation.cancelDetailIntent(); },
    reportError,
    isDisposed: () => navigation.isDisposed,
  });
  const thinking = settings.reasoningEffort;
  // Focus's empty wire value is explicit Auto, not an absent Kimi preference.
  // Feed Composer its non-concrete "on" sentinel so shared model defaults do
  // not materialize a fake Low/High label while effort segments stay usable.
  const composerThinking = computed(() => thinking.value ?? 'on');
  const approvalPolicy = settings.approvalPolicy;
  const permissionsProfileId = settings.permissionsProfileId;
  const refreshThreads = projection.refreshThreads;
  const refreshArchivedThreads = projection.refreshArchivedThreads;
  const refreshActiveThread = projection.refreshActiveThread;
  async function reloadAll(): Promise<void> {
    await projection.reloadAll();
    if (!navigation.isDisposed && !snapshotInvalidated.value) {
      // A fresh snapshot may keep the same revision. Explicitly hydrate the
      // retired view in that case instead of waiting for a revision watcher.
      if (transcript.enabled.value && !transcript.loading.value) void transcript.resumeAfterReload();
      promptHistory.refreshVisible();
    }
    reconcileMaterializedPromptResults();
  }
  const backendReset = createFocusBackendResetTransaction({ api, reloadAll });
  const transportSession = createFocusTransportSession({
    mayConnect: () => (
      !parked && !authRequired.value
      && !documentReloadRequired.value
      && meta.value !== null
    ),
    openEventSocket: (handlers) => api.connectEvents(handlers),
    probeEventAccess: async (signal) => {
      await api.meta(signal);
    },
    onHandshakeProbeError: (error) => {
      if (requiresDocumentReload(error)) {
        requireDocumentReload(error);
        return 'stop';
      }
      if (error instanceof FocusApiError && error.status === 401) {
        requireAuthentication(!isFocusSessionRejection(error));
        return 'stop';
      }
      return 'retry';
    },
    onConnectionError: reportError,
    onSocketOpened: () => {
      // Runtime health is an independent projection and every event socket
      // boundary is a freshness boundary for it.
      void refreshOperatorStatus();
    },
    onHandshakeReady: (reconnected) => {
      void api.promptTimings?.sync();
      // Gateway emits hello only after the document connection transaction.
      // It is the freshness boundary for document-bound action capabilities;
      // WebSocket open alone is not. A newer initial hello will synchronously
      // replace this queued lightweight read with an authoritative reload in
      // projection handling.
      if (reconnected) transportSession.requestProjectionReload();
      else transportSession.scheduleProjectionRefresh();
    },
    onEvent: (event) => {
      if (event.type === 'prompt_timing_changed') api.promptTimings?.changed(String(event.detail?.submission_id ?? ''));
      runtimeNotices.handleEvent(event);
      projection.handleEvent(event);
      if (event.type === 'thread_invalidated' && event.thread_id
        && ['web_prompt_succeeded', 'web_prompt_outcome_unknown',
          'web_prompt_result_observed'].includes(event.reason ?? '')) {
        void mutationActions.reconcilePromptResultsForThread(event.thread_id, true);
      }
    },
    onInvalidEvent: () => {
      runtimeNotices.reset();
      projection.invalidateWireProjection();
    },
    refreshProjection: async () => {
      await refreshThreads();
      await refreshActiveThread();
    },
    refreshThreadList: async () => {
      await refreshThreads();
    },
    reloadProjection: reloadAll,
    mayRetryProjectionReload: () => (
      !parked && projection.mayRetryProjectionReload()
    ),
    onScheduledTaskError: reportError,
  });
  const connection = computed(() => transportSession.snapshot.value.connection);

  function operatorStatusPollDelayMs(): number {
    const requested = Number(operatorStatus.value?.poll_after_seconds) * 1_000;
    if (!Number.isFinite(requested) || requested <= 0) {
      return DEFAULT_OPERATOR_STATUS_POLL_MS;
    }
    return Math.min(Math.max(requested, MIN_OPERATOR_STATUS_POLL_MS), MAX_OPERATOR_STATUS_POLL_MS);
  }

  function clearOperatorStatusTimer(): void {
    if (operatorStatusTimer === null) return;
    clearTimeout(operatorStatusTimer);
    operatorStatusTimer = null;
  }

  function scheduleOperatorStatusRefresh(): void {
    clearOperatorStatusTimer();
    if (
      parked || transportSession.snapshot.value.disposed
      || authRequired.value
      || documentReloadRequired.value
    ) return;
    operatorStatusTimer = setTimeout(() => {
      operatorStatusTimer = null;
      void refreshOperatorStatus();
    }, operatorStatusPollDelayMs());
  }

  async function refreshOperatorStatus(): Promise<void> {
    clearOperatorStatusTimer();
    if (operatorStatusRefreshPromise) return operatorStatusRefreshPromise;
    if (
      parked || transportSession.snapshot.value.disposed
      || authRequired.value
      || documentReloadRequired.value
    ) return;
    operatorStatusRefreshPromise = (async () => {
      try {
        const nextStatus = decodeFocusOperatorStatus(await api.operatorStatus());
        if (!nextStatus) throw new Error('Focus Web received a malformed operator status projection.');
        if (transportSession.snapshot.value.disposed) return;
        operatorStatus.value = nextStatus;
        operatorStatusFreshness.value = 'fresh';
      } catch (error) {
        if (transportSession.snapshot.value.disposed) return;
        if (requiresDocumentReload(error)) {
          requireDocumentReload(error);
        } else if (error instanceof FocusApiError && error.status === 401) {
          requireAuthentication(!isFocusSessionRejection(error));
        } else {
          // Keep the last successful warning projection visible. A failed
          // health read is uncertainty, never proof that old warnings
          // recovered or that no new warning exists.
          operatorStatusFreshness.value = 'stale';
        }
      } finally {
        operatorStatusRefreshPromise = null;
        scheduleOperatorStatusRefresh();
      }
    })();
    return operatorStatusRefreshPromise;
  }

  const clientView = createFocusClientView({
    meta,
    threads,
    searchThreads,
    snapshot,
    snapshotInvalidated,
    connection,
    threadScope,
    activeThreadId,
    draftWorkspaceId,
    scopeReady,
    settingsModel: settings.model,
  });
  const {
    reasoningEffortOptions,
    models,
    selectedModelId,
    workspacesView,
    sessions,
    searchSessions,
    workspaceGroups,
    activeThread,
    activeSessionActionCapabilities,
    canCompact,
    activeWorkspaceId,
    visibleWorkspace,
    status,
    turns: snapshotTurns,
    tasks,
    goal,
    pendingApprovals,
    questions,
    pendingBySession,
  } = clientView;
  // The client view keeps semantic state derived from the authoritative live
  // snapshot. Presentation alone may replace that snapshot's recent tail with
  // one bounded historical detail page.
  void snapshotTurns;
  const turns = computed(() => transcript.enabled.value ? transcript.turns.value : historyNavigation.visibleTurns.value);
  const viewingHistory = computed(() => transcript.enabled.value
    ? transcript.historical.value : historyNavigation.historyWindow.value !== null);
  const composerScopeId = navigation.composerScopeId;
  mutationActions = createFocusMutationActions({
    api,
    intentClock,
    navigation,
    projection,
    connection,
    reconnectEventTransport: () => transportSession.connect(),
    activeThread,
    canCompact,
    attachmentsAreAvailable: () => (
      meta.value?.capabilities.attachments === true
      && !snapshotInvalidated.value
      && !authRequired.value
      && !documentReloadRequired.value
    ),
    defaultDraftWorkspace: () => (
      workspacesView.value[0]?.id || meta.value?.default_working_dir || ''
    ),
    promptMessage: (key, values) => String(i18n.global.t(
      `focus.${key}`,
      values ?? { reason: '' },
    )),
    reportError,
    reportFatalError,
    clearError,
    clearPromptError,
  });
  const {
    starting,
    actionBusy,
    mutationBusyByThread,
    unknownLifecycleMutations,
    unknownProcessLocalMutations,
    unknownSubmissionDraft,
    unknownSubmissionDrafts,
    running,
    owner,
    canSubmit,
    unknownThreadCreateDraftExists,
    canRetryUnknownSubmission,
    canInterrupt,
    pendingApprovalActions,
    pendingQuestionActions,
    promptResultNotices,
    dismissPromptResultNotice,
    reconcilePromptResultsForThread,
    renameThread,
    forkThread: forkThreadMutation,
    editPrompt: editPromptMutation,
    compact,
    review,
    createGoal,
    controlGoal,
    closeThread,
    archiveThread,
    unarchiveThread,
    deleteThread,
    uploadAttachment,
    submit: submitMutation,
    discardUnknownSubmission,
    takeUnknownSubmissionForRetry,
    verifyUnknownLifecycleMutation,
    unlockUnknownLifecycleMutation,
    discardUnknownProcessLocalMutation,
    interrupt,
    respondApproval,
    respondQuestion,
    dismissQuestion,
  } = mutationActions;

  function submit(
    ...parameters: Parameters<FocusMutationActions['submit']>
  ): ReturnType<FocusMutationActions['submit']> {
    historyNavigation.clearHistoryWindow();
    if (transcript.enabled.value && transcript.historical.value) void transcript.load();
    return submitMutation(...parameters);
  }

  let recoverablePage = false;
  let accessReloadTimer: ReturnType<typeof setTimeout> | undefined;
  function canRebuildPage(): boolean {
    return !parked && !navigation.isDisposed && typeof document !== 'undefined' && document.visibilityState === 'visible'
      && !starting.value && !actionBusy.value && !Object.keys(mutationBusyByThread.value).length
      && !unknownProcessLocalMutations.value.length && !unknownLifecycleMutations.value.length
      && !Object.keys(pendingApprovalActions.value).length && !Object.keys(pendingQuestionActions.value).length
      && !backendReset.executing.value && !backendReset.outcomeUnknown.value && !updateBusy.value && !updateOperationActive.value;
  }
  if (hasMobileFeature('resume')) window.__focusCanRebuild = canRebuildPage;

  function recoverDocumentIfIdle(): void {
    clearTimeout(accessReloadTimer);
    if (!recoverablePage || !meta.value || !canRebuildPage()) return;
    const delay = documentReloadDelay();
    if (delay === null) return;
    if (delay > 0) {
      accessReloadTimer = setTimeout(recoverDocumentIfIdle, delay);
      return;
    }
    if (!reserveDocumentReload()) return;
    recoverablePage = false;
    reloadDocument();
  }

  function requireAuthentication(outer = false): void {
    outerAuthRequired.value = outer;
    recoverablePage = !outer;
    authRequired.value = true;
    clearError();
    clearOperatorStatusTimer();
    transportSession.suspend();
    recoverDocumentIfIdle();
  }

  function requiresDocumentReload(error: unknown): boolean {
    return error instanceof FocusApiError
      && (error.code === 'document_replaced' || error.code === 'document_unregistered');
  }

  function requireDocumentReload(error: unknown): void {
    recoverablePage = error instanceof FocusApiError && error.code === 'document_unregistered';
    documentFailure.value = recoverablePage ? 'document_unregistered' : 'document_replaced';
    clearError();
    clearOperatorStatusTimer();
    transportSession.suspend();
    recoverDocumentIfIdle();
  }

  function reportFatalError(error: unknown): boolean {
    if (!requiresDocumentReload(error)
      && !(error instanceof FocusApiError && error.status === 401)) return false;
    reportError(error);
    return true;
  }

  function reportError(error: unknown): void {
    // A staged read can legitimately lose its document/observation fence
    // while a newer read is becoming authoritative.  The owning read path
    // drops that result; keep the internal 409 out of the user-facing banner
    // when it reaches this shared presentation boundary.
    if (isStaleWebReadError(error)) return;
    if (requiresDocumentReload(error)) {
      requireDocumentReload(error);
      return;
    }
    if (error instanceof FocusApiError && error.status === 401) {
      requireAuthentication(!isFocusSessionRejection(error));
      return;
    }
    promptErrorLocator = error instanceof FocusPromptError ? error.locator : null;
    errorPresentation.value = {
      message: error instanceof Error ? error.message : String(error),
      diagnostic: error instanceof FocusPromptError ? error.diagnostic : '',
    };
  }

  function clearPromptError(locator: WebPromptResultLocator): void {
    if (promptErrorLocator?.threadId === locator.threadId
      && promptErrorLocator.mutationId === locator.mutationId) clearError();
  }

  function clearError(): void {
    promptErrorLocator = null;
    errorPresentation.value = { message: '', diagnostic: '' };
  }

  async function refreshBackendReset(): Promise<void> {
    clearError();
    const observed = await backendReset.refreshPreview();
    if (observed !== null) return;
    const error = backendReset.previewError.value;
    if (error !== null && !reportFatalError(error)) reportError(error);
  }

  function clearUpdatePoll(): void {
    if (updatePollTimer !== null) {
      clearTimeout(updatePollTimer);
      updatePollTimer = null;
    }
  }

  function scheduleUpdatePoll(): void {
    clearUpdatePoll();
    if (parked || navigation.isDisposed || authRequired.value || documentReloadRequired.value) return;
    const state = updateStatus.value?.state;
    if (state !== 'checking' && state !== 'cancelling' && state !== 'applying' && !updateApplyStarted.value) return;
    updatePollTimer = setTimeout(() => {
      updatePollTimer = null;
      void refreshUpdateStatus({ silent: true });
    }, 1500);
  }

  async function refreshUpdateStatus(options: { silent?: boolean } = {}): Promise<void> {
    if (updateBusy.value) return;
    await readUpdateStatus(options);
  }

  function installUpdateStatus(observed: FocusUpdateStatus): void {
    if (observed.operation_id !== updateStatus.value?.operation_id
      || observed.state !== updateStatus.value?.state) {
      updateObservedAt.value = Date.now();
    }
    updateStatus.value = observed;
    updateStatusStale.value = false;
    if (observed.state === 'applying' && !updateApplyStarted.value) {
      updateApplyStarted.value = true;
      updateApplyStartedAt = Date.now();
    } else if (observed.state !== 'applying' && observed.state !== 'succeeded') {
      updateApplyStarted.value = false;
      updateApplyStartedAt = 0;
    }
    if (!updateOperationActive.value) updateNotice.value = '';
  }

  async function readUpdateStatus(options: { silent?: boolean } = {}): Promise<void> {
    if (parked || updateLoading.value || navigation.isDisposed || authRequired.value || documentReloadRequired.value) return;
    updateLoading.value = true;
    try {
      const observed = await api.updateStatus();
      if (navigation.isDisposed) return;
      installUpdateStatus(observed);
      if (observed.state === 'succeeded' && updateApplyStarted.value && updateReloadTimer === null) {
        updateReloadTimer = setTimeout(() => {
          updateReloadTimer = null;
          if (!parked) window.location.reload();
        }, 1200);
      }
      scheduleUpdatePoll();
    } catch (error) {
      if (navigation.isDisposed) return;
      updateStatusStale.value = true;
      // The old process intentionally loses its memory-only session during a
      // restart. A 401/409 after an apply is therefore positive evidence that
      // the new process is reachable, but not evidence that the installation
      // succeeded; reload the complete document and let the new process report
      // its durable journal. Network failures remain bounded and visible.
      if (updateApplyStarted.value) {
        const elapsed = Date.now() - updateApplyStartedAt;
        const knownNewProcess = error instanceof FocusApiError
          && (isFocusSessionRejection(error) || error.code === 'document_unregistered' || error.code === 'document_replaced');
        if (knownNewProcess) {
          if (updateReloadTimer === null) {
            updateReloadTimer = setTimeout(() => {
              updateReloadTimer = null;
              if (!parked) window.location.reload();
            }, 300);
          }
        } else if (elapsed < UPDATE_RECONNECT_TIMEOUT_MS) {
          scheduleUpdatePoll();
        } else {
          clearUpdatePoll();
          reportError(new Error('Focus 更新器未能在限定时间内恢复；请检查 service 状态和更新 journal。'));
        }
      } else {
        if (!reportFatalError(error) && !options.silent) reportError(error);
        scheduleUpdatePoll();
      }
    } finally {
      updateLoading.value = false;
    }
  }

  async function reconcileUpdateRejection(error: unknown): Promise<void> {
    if (navigation.isDisposed) return;
    if (error instanceof FocusApiError && error.status === 409 && error.code === 'update_rejected') {
      await readUpdateStatus();
      if (navigation.isDisposed) return;
      if (!updateStatusStale.value && updateOperationActive.value) {
        updateNotice.value = i18n.global.t('focus.updateAlreadyActive');
        return;
      }
    }
    reportError(error);
  }

  async function configureUpdateSource(url: string): Promise<void> {
    if (updateActionsDisabled.value || navigation.isDisposed || authRequired.value || documentReloadRequired.value) return;
    clearUpdatePoll();
    updateBusy.value = true;
    updateNotice.value = '';
    clearError();
    try {
      const observed = await api.configureUpdateSource(url.trim(), 'change-source');
      if (!navigation.isDisposed) installUpdateStatus(observed);
    } catch (error) {
      await reconcileUpdateRejection(error);
    } finally {
      updateBusy.value = false;
    }
  }

  async function checkUpdate(target: 'stable' | 'main', commit: string): Promise<void> {
    if (updateActionsDisabled.value || navigation.isDisposed || authRequired.value || documentReloadRequired.value) return;
    clearUpdatePoll();
    updateBusy.value = true;
    updateNotice.value = '';
    updateApplyStarted.value = false;
    updateApplyStartedAt = 0;
    clearError();
    try {
      const observed = await api.checkUpdate(target, commit.trim());
      if (navigation.isDisposed) return;
      installUpdateStatus(observed);
      scheduleUpdatePoll();
    } catch (error) {
      await reconcileUpdateRejection(error);
    } finally {
      updateBusy.value = false;
    }
  }

  async function cancelUpdate(operationId: string): Promise<void> {
    const operation = updateStatus.value;
    if (updateBusy.value || updateLoading.value || updateStatusStale.value
      || navigation.isDisposed || authRequired.value || documentReloadRequired.value
      || !operation || operation.operation_id !== operationId || operation.installation_started
      || (operation.state !== 'checking' && !(operation.state === 'cancelling' && operation.error))) return;
    clearUpdatePoll();
    updateBusy.value = true;
    updateNotice.value = '';
    clearError();
    try {
      const observed = await api.cancelUpdate(operationId);
      if (!navigation.isDisposed) installUpdateStatus(observed);
    } catch (error) {
      // A lost response cannot prove cancellation. Read the journal, without
      // replaying the POST or enabling a competing check from stale state.
      updateStatusStale.value = true;
      if (error instanceof FocusApiError && error.status === 409 && error.code === 'update_rejected') {
        await reconcileUpdateRejection(error);
      } else {
        if (!reportFatalError(error)) reportError(error);
        await readUpdateStatus({ silent: true });
      }
    } finally {
      updateBusy.value = false;
      scheduleUpdatePoll();
    }
  }

  async function applyUpdate(operationId: string): Promise<void> {
    if (updateActionsDisabled.value || navigation.isDisposed || authRequired.value || documentReloadRequired.value
      || updateStatus.value?.state !== 'ready' || updateStatus.value.operation_id !== operationId) return;
    clearUpdatePoll();
    updateBusy.value = true;
    updateNotice.value = '';
    updateApplyStarted.value = true;
    updateObservedAt.value = Date.now();
    updateApplyStartedAt = Date.now();
    clearError();
    try {
      const observed = await api.applyUpdate(operationId, operationId);
      if (navigation.isDisposed) return;
      installUpdateStatus(observed);
      scheduleUpdatePoll();
    } catch (error) {
      if (navigation.isDisposed) return;
      const preEffect = error instanceof FocusApiError
        && error.effectEvidence === 'pre_effect';
      if (preEffect) {
        updateApplyStarted.value = false;
        updateApplyStartedAt = 0;
        await reconcileUpdateRejection(error);
      } else {
        // The POST may have reached the updater just before the service went
        // away. Keep the operation in the unknown/reconnect path instead of
        // inviting a second apply click or losing the only durable receipt.
        if (updateStatus.value?.operation_id === operationId
          && updateStatus.value.state === 'ready') {
          updateStatus.value = {
            ...updateStatus.value,
            state: 'applying',
            message: 'Update request submitted; waiting for the service to return.',
            restart_required: true,
          };
        }
        scheduleUpdatePoll();
      }
    } finally {
      updateBusy.value = false;
    }
  }

  async function executeBackendReset(
    preview: Parameters<typeof backendReset.execute>[0],
  ): Promise<FocusBackendResetExecutionOutcome> {
    clearError();
    const outcome = await backendReset.execute(preview);
    if (outcome.disposition === 'known-no-effect') {
      const presentedError = outcome.refreshError ?? outcome.error;
      if (!reportFatalError(presentedError)) reportError(presentedError);
    } else if (outcome.disposition === 'succeeded' && outcome.reloadError !== null) {
      reportError(outcome.reloadError);
    }
    return outcome;
  }

  function reconcileMaterializedPromptResults(): void {
    const threadId = activeThreadId.value;
    if (!threadId || !scopeReady.value
      || snapshot.value?.thread.id !== threadId) return;
    void reconcilePromptResultsForThread(threadId);
  }

  async function forkThread(threadId: string): Promise<void> {
    const floor = navigation.captureNavigationStateFloor();
    const result = await forkThreadMutation(threadId);
    if (!result) return;
    if (result.name_warning || result.list_visibility === 'not_found') {
      forkNotes.value = { ...forkNotes.value, [result.thread_id]: result };
    }
    if (result.visibility_diagnostic) {
      runtimeNotices.addDiagnostic(result.thread_id, result.visibility_diagnostic);
    }
    if (navigation.navigationStateFloorIsCurrent(floor)) {
      await selectThread(result.thread_id);
    }
  }

  async function editPrompt(threadId: string, target: { turn_id: string; item_id: string }): Promise<void> {
    if (Object.hasOwn(historyEdits.value, threadId)) return;
    const navigationFloor = navigation.captureNavigationStateFloor();
    const prepared: { prompt?: FocusHistoryEditPrompt } = {};
    const succeeded = await editPromptMutation(threadId, target, prompt => {
      historyEdits.value[threadId] = { prompt, restoreAutomatically: false };
      prepared.prompt = historyEdits.value[threadId]!.prompt;
    });
    if (!prepared.prompt || navigation.isDisposed || activeThreadId.value !== threadId) return;
    clearHistoryView();
    let installed = false;
    try {
      installed = await projection.refreshActiveThread();
    } catch (error) {
      if (!navigation.isDisposed && !reportFatalError(error)
        && navigation.navigationStateFloorIsCurrent(navigationFloor)) reportError(error);
      return;
    }
    // A completed read may have been stale or superseded without installing a snapshot.
    if (!installed || navigation.isDisposed
      || !navigation.navigationStateFloorIsCurrent(navigationFloor)) return;
    const draft = historyEdits.value[threadId];
    if (succeeded && draft?.prompt === prepared.prompt) draft.restoreAutomatically = true;
  }

  async function selectThread(threadId: string): Promise<void> {
    await navigation.selectThread(threadId);
    reconcileMaterializedPromptResults();
  }
  const openWorkspaceDraft = navigation.openWorkspaceDraft;

  const setThreadScope = navigation.changeThreadScope;

  async function loadAllSessionsForSearch(): Promise<void> {
    await projection.loadAllSessionsForSearch();
  }

  function downloadAttachment(fileId: string): Promise<Blob> {
    return api.attachmentBlob(fileId);
  }

  async function exportThreadSummary(threadId: string, selection?: FocusSummaryExportSelection): Promise<Blob | null> {
    const normalizedThreadId = threadId.trim();
    if (
      !normalizedThreadId
      || summaryExporting.value
      || threadDataExporting.value
      || navigation.isDisposed
    ) return null;
    summaryExporting.value = true;
    clearError();
    try {
      return await api.exportThreadSummary(normalizedThreadId, selection);
    } catch (error) {
      if (!navigation.isDisposed) reportError(error);
      return null;
    } finally {
      summaryExporting.value = false;
    }
  }

  async function exportThreadData(threadId: string): Promise<Blob | null> {
    const normalizedThreadId = threadId.trim();
    if (
      !normalizedThreadId
      || summaryExporting.value
      || threadDataExporting.value
      || navigation.isDisposed
    ) return null;
    threadDataExporting.value = true;
    clearError();
    try {
      return await api.exportThreadData(normalizedThreadId);
    } catch (error) {
      if (!navigation.isDisposed) reportError(error);
      return null;
    } finally {
      threadDataExporting.value = false;
    }
  }

  async function loadOlderMessages(sessionId: string): Promise<boolean> {
    if (sessionId !== activeThreadId.value) return false;
    return transcript.enabled.value ? transcript.older() : historyNavigation.loadOlderPage();
  }

  function returnToLiveTail(): void {
    historyNavigation.clearHistoryWindow();
    if (transcript.enabled.value) void transcript.load();
  }

  async function resolveHistoryPromptTarget(turnId: string): Promise<boolean> {
    if (!transcript.enabled.value) return historyNavigation.resolvePromptTarget(turnId);
    const prompt = promptHistory.outline.value.find((entry) => entry.id === turnId);
    promptHistory.pause();
    return prompt ? !!await transcript.locate(prompt.rawTurnId, prompt.itemId) : false;
  }

  let turnWindowChangeGeneration = 0;
  async function setTurnWindowLimit(value: unknown): Promise<void> {
    if (!turnWindow.setLimit(value)) return;
    const generation = ++turnWindowChangeGeneration;
    historyNavigation.resetForTurnLimitChange();
    projection.applyTurnWindowLimit();
    if (!activeThreadId.value || navigation.isDisposed) {
      await historyNavigation.completeTurnLimitChange(false);
      return;
    }
    let installed = false;
    try {
      installed = await projection.refreshActiveThread();
    } catch (error) {
      if (generation === turnWindowChangeGeneration && !navigation.isDisposed) {
        reportError(error);
      }
    }
    if (generation !== turnWindowChangeGeneration || navigation.isDisposed) return;
    await historyNavigation.completeTurnLimitChange(installed);
  }

  const selectModel = settings.selectModel;
  const setThinking = settings.setThinking;
  const setReasoningEffort = settings.setReasoningEffort;
  const setApprovalPolicy = settings.setApprovalPolicy;
  const setPermissionsProfile = settings.setPermissionsProfile;

  let initialRetry: ReturnType<typeof setTimeout> | undefined;
  let initialDelay = 1000;
  let initialReadFailed = false;
  function wakeDocument(): void {
    if (parked || typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    if (recoverablePage) recoverDocumentIfIdle();
    else if (initialReadFailed && !loading.value) void load();
  }
  window.addEventListener?.('online', wakeDocument);
  window.addEventListener?.('focus-host-resume', wakeDocument);
  if (typeof document !== 'undefined') document.addEventListener?.('visibilitychange', wakeDocument);

  function setTabActive(active: boolean): boolean {
    if (navigation.isDisposed || !initialized.value || !meta.value) return false;
    if (parked === !active) return true;
    parked = !active;
    if (parked) {
      window.dispatchEvent(new Event('focus-host-pause'));
      transportSession.suspend();
      clearOperatorStatusTimer();
      clearUpdatePoll();
      clearTimeout(initialRetry);
      clearTimeout(accessReloadTimer);
    } else {
      transportSession.connect();
      scheduleUpdatePoll();
      wakeDocument();
    }
    return true;
  }
  if (hasMobileFeature('tabs')) window.__focusSetTabActive = setTabActive;

  async function load(): Promise<void> {
    if (parked || navigation.isDisposed || loading.value) return;
    clearTimeout(initialRetry);
    initialReadFailed = false;
    // Capture the deep link before initial durable-profile convergence may
    // replace browser history with that profile's target.
    let requestedThreadId = new URL(window.location.href)
      .searchParams.get(THREAD_QUERY_KEY)?.trim() ?? '';
    if (!requestedThreadId && hasMobileFeature('resume')) {
      try { requestedThreadId = recoveryStorage().getItem('focus-web.last-thread') ?? ''; } catch { /* private storage */ }
    }
    loading.value = true;
    authRequired.value = false;
    clearError();
    try {
      const initialMeta = await api.initialize();
      if (navigation.isDisposed) return;
      intentClock.rebase(api.intentGenerationFloor);
      navigation.registerClient(api.clientId);
      projection.installInitialMeta(initialMeta);
      dataRetention.start();
      mutationActions.installInitialState(initialMeta);
      // Runtime health is an independent, ephemeral projection. It must not
      // hold the durable thread shell or event connection behind its deadline.
      void refreshOperatorStatus();
      await refreshThreads();
      if (navigation.isDisposed) return;
      await navigation.restoreInitialTarget({
        requestedThreadId,
        recoveryThreadId: unknownSubmissionDraft.value?.threadId.trim() ?? '',
        // Session-local unknown evidence is a retry fence, not selection
        // authority. A concrete recovery target still wins inside the owner;
        // otherwise materialize the durable server selection exactly.
        persistedThreadId: initialMeta.writer_profile.selected_thread_id.trim(),
      });
      if (navigation.isDisposed) return;
      initialDelay = 1000;
      transportSession.connect();
    } catch (error) {
      if (navigation.isDisposed) return;
      reportError(error);
      if (!authRequired.value && !documentReloadRequired.value
        && (error instanceof TypeError || (error instanceof FocusApiError && error.status >= 500))) {
        initialReadFailed = true;
        initialRetry = setTimeout(wakeDocument, initialDelay);
        initialDelay = Math.min(initialDelay * 2, 30_000);
      }
    } finally {
      if (!navigation.isDisposed) {
        initialized.value = true;
        loading.value = false;
      }
    }
  }

  function dispose(): void {
    stopThreadCheckpoint();
    if (window.__focusSetTabActive === setTabActive) delete window.__focusSetTabActive;
    if (window.__focusCanRebuild === canRebuildPage) delete window.__focusCanRebuild;
    clearTimeout(accessReloadTimer);
    clearTimeout(initialRetry);
    window.removeEventListener?.('online', wakeDocument);
    window.removeEventListener?.('focus-host-resume', wakeDocument);
    if (typeof document !== 'undefined') document.removeEventListener?.('visibilitychange', wakeDocument);
    // The document is leaving; pending stream deltas no longer have a visible
    // consumer. Cancel their presentation callbacks instead of doing one last
    // Markdown/DOM pass during teardown.
    projection.dispose();
    backendReset.dispose();
    mutationActions.dispose();
    settings.dispose();
    dataRetention.dispose();
    threadInspection.dispose();
    historyNavigation.dispose();
    promptHistory.dispose();
    transcript.dispose();
    runtimeNotices.reset();
    navigation.dispose();
    loading.value = false;
    clearOperatorStatusTimer();
    clearUpdatePoll();
    if (updateReloadTimer !== null) {
      clearTimeout(updateReloadTimer);
      updateReloadTimer = null;
    }
    transportSession.dispose();
  }

  function reloadDocument(): void {
    window.location.reload();
  }

  return {
    api,
    meta,
    operatorStatus,
    operatorStatusFreshness,
    operatorStatusStale,
    runtimeNoticePresentation: runtimeNotices.presentation,
    backendResetPreview: backendReset.preview,
    backendResetResult: backendReset.result,
    backendResetLoading: backendReset.previewPending,
    backendResetBusy: backendReset.executing,
    backendResetOutcomeUnknown: backendReset.outcomeUnknown,
    threads,
    archivedThreads,
    snapshot,
    activeThreadId,
    threadScope,
    initialized,
    loading,
    summaryExporting,
    threadDataExporting,
    updateStatus,
    updateLoading,
    updateBusy,
    updateOperationActive,
    updateActionsDisabled,
    updateStatusStale,
    updateNotice,
    updateObservedAt,
    conversationLoading,
    starting,
    loadingMore: computed(() => transcript.enabled.value ? transcript.loading.value : historyNavigation.loading.value),
    loadingMoreError: computed(() => transcript.enabled.value ? !!transcript.error.value : historyNavigation.error.value),
    historyHasMore: computed(() => transcript.enabled.value ? transcript.hasOlder.value : historyNavigation.hasMore.value),
    transcript,
    viewingHistory,
    historyOutline: computed(() => transcript.enabled.value ? promptHistory.outline.value : historyNavigation.outline.value),
    historyOutlineTruncated: computed(() => transcript.enabled.value ? promptHistory.truncated.value : historyNavigation.outlineTruncated.value),
    historyOutlineLoading: computed(() => transcript.enabled.value ? promptHistory.loading.value : historyNavigation.outlineLoading.value),
    historyOutlineError: computed(() => transcript.enabled.value ? promptHistory.error.value : historyNavigation.outlineError.value),
    historyOutlineHasMore: computed(() => transcript.enabled.value ? promptHistory.hasMore.value : historyNavigation.outlineHasMore.value),
    toolDetail: threadInspection.toolDetail,
    toolDetailLocator: threadInspection.toolDetailLocator,
    toolDetailLoading: threadInspection.toolDetailLoading,
    toolDetailError: threadInspection.toolDetailError,
    toolDetailScanStatus: threadInspection.toolDetailScanStatus,
    toolDetailScannedItems: threadInspection.toolDetailScannedItems,
    toolDetailAvailable: threadInspection.toolDetailAvailable,
    toolDetailUnavailableReason: threadInspection.toolDetailUnavailableReason,
    conversationSearchPage: threadInspection.searchPage,
    conversationSearchLoading: threadInspection.searchLoading,
    conversationSearchError: threadInspection.searchError,
    conversationSearchAvailable: threadInspection.historySearchAvailable,
    conversationSearchUnavailableReason: threadInspection.historySearchUnavailableReason,
    archivedLoading,
    archivedTruncated,
    archivedLimit,
    reloadInFlight,
    turnWindowLimit: turnWindow.limit,
    actionBusy,
    mutationBusyByThread,
    authRequired,
    outerAuthRequired,
    documentReloadRequired,
    documentFailure,
    errorMessage,
    errorPresentation,
    forkNote: computed(() => forkNotes.value[activeThreadId.value] ?? null),
    dismissForkNote: (threadId: string) => { delete forkNotes.value[threadId]; },
    historyEditPrompt: computed(() => historyEdits.value[activeThreadId.value]?.prompt ?? null),
    historyEditReady: computed(() => historyEdits.value[activeThreadId.value]?.restoreAutomatically ?? false),
    consumeHistoryEditPrompt: (threadId: string, prompt: FocusHistoryEditPrompt) => {
      if (historyEdits.value[threadId]?.prompt === prompt) delete historyEdits.value[threadId];
    },
    promptResultNotices,
    dismissPromptResultNotice,
    unknownSubmissionDraft,
    unknownSubmissionDrafts,
    unknownLifecycleMutations,
    unknownProcessLocalMutations,
    connection,
    runtimeEpoch,
    revision,
    snapshotInvalidated,
    models,
    reasoningEffortOptions,
    selectedModelId,
    thinking,
    composerThinking,
    approvalPolicy,
    permissionsProfileId,
    dataRetention,
    nextTurnSettings: settings.snapshot,
    workspacesView,
    workspaceGroups,
    sessions,
    searchSessions,
    activeWorkspaceId,
    composerScopeId,
    scopeReady,
    composerReady,
    visibleWorkspace,
    activeThread,
    activeSessionActionCapabilities,
    canCompact,
    turns,
    tasks,
    goal,
    running,
    owner,
    canSubmit,
    unknownThreadCreateDraftExists,
    canRetryUnknownSubmission,
    canInterrupt,
    status,
    pendingApprovals,
    questions,
    pendingBySession,
    pendingApprovalActions,
    pendingQuestionActions,
    load,
    dispose,
    reloadDocument,
    reloadAll,
    refreshOperatorStatus,
    refreshBackendReset,
    refreshUpdateStatus,
    configureUpdateSource,
    checkUpdate,
    cancelUpdate,
    applyUpdate,
    executeBackendReset,
    selectThread,
    forkThread,
    editPrompt,
    setThreadScope,
    loadAllSessionsForSearch,
    openWorkspaceDraft,
    renameThread,
    compact,
    review,
    createGoal,
    controlGoal,
    closeThread,
    archiveThread,
    refreshArchivedThreads,
    unarchiveThread,
    deleteThread,
    uploadAttachment,
    downloadAttachment,
    exportThreadSummary,
    listExportTurns: (threadId: string, cursor?: string, signal?: AbortSignal) => api.listExportTurns(threadId, cursor, signal),
    previewExportTurn: (threadId: string, turnId: string, content: FocusSummaryExportSelection['content'], signal?: AbortSignal) => api.exportThreadSummary(
      threadId, { scope: 'selected', turn_ids: [turnId], content }, signal,
    ),
    exportThreadData,
    submit,
    discardUnknownSubmission,
    takeUnknownSubmissionForRetry,
    verifyUnknownLifecycleMutation,
    unlockUnknownLifecycleMutation,
    discardUnknownProcessLocalMutation,
    loadOlderMessages,
    returnToLiveTail,
    resolveHistoryPromptTarget,
    cancelHistoryPromptTarget: () => { transcript.cancelTarget(); historyNavigation.cancelDetailIntent(); },
    setHistoryOutlineVisible: promptHistory.setVisible,
    loadMoreHistoryOutline: () => transcript.enabled.value ? promptHistory.loadMore() : historyNavigation.loadMoreOutline(),
    readToolDetail: threadInspection.readToolDetail,
    clearToolDetail: threadInspection.clearToolDetail,
    cancelToolDetail: threadInspection.cancelToolDetail,
    searchConversation: threadInspection.searchConversation,
    resolveConversationSearchOccurrence: threadInspection.resolveSearchOccurrence,
    clearConversationSearch: threadInspection.clearSearch,
    interrupt,
    respondApproval,
    respondQuestion,
    dismissQuestion,
    selectModel,
    setThinking,
    setReasoningEffort,
    setApprovalPolicy,
    setPermissionsProfile,
    setTurnWindowLimit,
  };
}
