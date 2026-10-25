import { computed, ref, watch, type Ref } from 'vue';
import type { FocusWebApiPort } from '../api';
import type { FocusNavigationProfile } from '../focusNavigationProfile';
import { FocusApiError, type FocusPromptResultReceipt, type FocusThreadSnapshot } from '../types';
import { isWebPromptClientUserMessageId } from '../webPromptMutation';
import { FocusPromptError, webPromptTransportDiagnostic, type WebPromptDiagnostic } from '../webPromptDiagnostic';
import { createWebPromptResultLocatorStore, type WebPromptResultLocator } from '../webPromptResultLocators';

export type PromptResultMessageKey =
  | 'promptKnownNoEffectAfterReload'
  | 'promptOutcomeUnknown'
  | 'promptPending'
  | 'promptResultUnavailable';

export interface PromptResultNotice extends WebPromptResultLocator {
  message: string;
  diagnostic: string;
}

interface PromptResultsOptions {
  api: Pick<FocusWebApiPort, 'readPromptResult'>;
  navigation: Pick<FocusNavigationProfile,
    'activeThreadId' | 'scopeReceipt' | 'scopeReceiptIsCurrent' | 'isDisposed'>;
  snapshot: Readonly<Ref<FocusThreadSnapshot | null>>;
  connection: Readonly<Ref<string>>;
  submitting: Readonly<Ref<boolean>>;
  reconnectEventTransport(): void;
  invalidateWireProjection(): void;
  promptMessage(key: PromptResultMessageKey, values: { reason: string }): string;
  clearPromptError(locator: WebPromptResultLocator): void;
  reportFatalError(error: unknown): boolean;
}

/** Owns GET reconciliation and ephemeral notices; locators never grant replay authority. */
export function createPromptResults(options: PromptResultsOptions) {
  const locators = createWebPromptResultLocatorStore();
  const notices = ref<Array<PromptResultNotice & { state: string; dismissed: boolean }>>([]);
  const inFlight = new Map<string, { generation: number; promise: Promise<void> }>();
  let generation = 0;
  let disposed = false;

  function readyScope() {
    const scope = options.navigation.scopeReceipt.value;
    return !disposed && !options.navigation.isDisposed
      && !options.submitting.value
      && options.connection.value === 'connected'
      && scope?.selectedThreadId
      && options.navigation.activeThreadId.value === scope.selectedThreadId
      && options.navigation.scopeReceiptIsCurrent(scope)
      && options.snapshot.value?.thread.id === scope.selectedThreadId
      ? scope : null;
  }

  function sameLocator(left: WebPromptResultLocator, right: WebPromptResultLocator): boolean {
    return left.threadId === right.threadId && left.mutationId === right.mutationId;
  }

  function forget(locator: WebPromptResultLocator): void {
    locators.forget(locator);
    notices.value = notices.value.filter((notice) => !sameLocator(notice, locator));
    options.clearPromptError(locator);
  }

  function isExact(result: FocusPromptResultReceipt, locator: WebPromptResultLocator): boolean {
    return result.thread_id === locator.threadId && result.mutation_id === locator.mutationId
      && isWebPromptClientUserMessageId(result.client_user_message_id, locator.mutationId);
  }

  function settle(result: FocusPromptResultReceipt, locator: WebPromptResultLocator): boolean {
    if (!isExact(result, locator)) {
      options.invalidateWireProjection();
      return false;
    }
    if (result.status === 'succeeded' || result.status === 'known_no_effect') forget(locator);
    return true;
  }

  function present(key: PromptResultMessageKey, locator: WebPromptResultLocator, result: WebPromptDiagnostic): void {
    const previous = notices.value.find((notice) => sameLocator(notice, locator));
    const state = `${key}:${result.reason_code}`;
    const error = new FocusPromptError(options.promptMessage(key, {
      reason: result.reason_code ? ` (${result.reason_code})` : '',
    }), result);
    options.clearPromptError(locator);
    notices.value = [
      ...notices.value.filter((notice) => !sameLocator(notice, locator)),
      { ...locator, message: error.message, diagnostic: error.diagnostic, state,
        dismissed: previous?.state === state && previous.dismissed },
    ].slice(-32);
  }

  async function reconcile(threadId: string, supersedePending = false): Promise<void> {
    const scope = readyScope();
    if (!scope || scope.selectedThreadId !== threadId) return;
    // A server result-change notification can arrive while an older GET is pending.
    if (supersedePending) generation += 1;
    const observedGeneration = generation;
    const current = () => generation === observedGeneration && readyScope() === scope;
    await Promise.all(locators.list().filter((locator) => locator.threadId === threadId).map((locator) => {
      const key = `${locator.threadId}:${locator.mutationId}`;
      const pending = inFlight.get(key);
      if (pending?.generation === observedGeneration) return pending.promise;
      const promise = (async () => {
        try {
          const result = await options.api.readPromptResult(locator.threadId, locator.mutationId);
          // A navigation/connection boundary or a terminal POST can supersede this read.
          if (!current() || !locators.list().some((item) => sameLocator(item, locator))) return;
          if (!settle(result, locator)) return;
          if (result.status === 'known_no_effect') present('promptKnownNoEffectAfterReload', locator, result);
          else if (result.status === 'outcome_unknown') present('promptOutcomeUnknown', locator, result);
          else if (result.status === 'pending') present('promptPending', locator, result);
        } catch (error) {
          if (!current() || !locators.list().some((item) => sameLocator(item, locator))) return;
          if (options.reportFatalError(error)) return;
          if (error instanceof FocusApiError && error.effectEvidence === 'pre_effect'
            && error.code === 'prompt_result_unavailable') {
            forget(locator);
            present('promptResultUnavailable', locator,
              webPromptTransportDiagnostic(locator, 'outcome_unknown', error.code, 'result_lookup'));
          } else if (error instanceof FocusApiError && error.code === 'web_writer_disconnected') {
            // The hello, not this lookup error, owns connection readiness.
            options.reconnectEventTransport();
          }
          // A transient GET failure says nothing new about the original POST.
          // Retain the locator and use the next ready scope/reload to check it.
        } finally {
          if (inFlight.get(key)?.generation === observedGeneration) inFlight.delete(key);
        }
      })();
      inFlight.set(key, { generation: observedGeneration, promise });
      return promise;
    }));
  }

  // Invalidate immediately at every navigation/transport boundary, including ABA.
  // Query only after hello, exact materialization, and live Composer settlement.
  // A GET must not settle before the POST later reports a lost response.
  const stop = watch(readyScope, (scope) => {
    generation += 1;
    if (scope) void reconcile(scope.selectedThreadId);
  }, { flush: 'sync' });

  return {
    notices: computed(() => notices.value.filter((notice) => (
      notice.threadId === options.navigation.activeThreadId.value && !notice.dismissed
    ))),
    dismiss(mutationId: string): void {
      const notice = notices.value.find((item) => (
        item.threadId === options.navigation.activeThreadId.value && item.mutationId === mutationId
      ));
      if (notice) notice.dismissed = true;
    },
    remember: locators.remember,
    forget,
    isExact,
    settle,
    reconcile,
    dispose(): void {
      disposed = true;
      generation += 1;
      stop();
      inFlight.clear();
      notices.value = [];
    },
  };
}
