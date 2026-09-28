import type { FocusPromptResultReceipt } from './types';
import type { WebPromptResultLocator } from './webPromptResultLocators';

export type WebPromptDiagnostic = Omit<FocusPromptResultReceipt,
  'client_user_message_id' | 'mode'> & { mode: FocusPromptResultReceipt['mode'] | null };

/** Display-only evidence. Never persist input, construct a POST, or grant retry authority. */
export class FocusPromptError extends Error {
  readonly diagnostic: string;

  constructor(message: string, result: WebPromptDiagnostic) {
    super(message);
    this.name = 'FocusPromptError';
    this.diagnostic = JSON.stringify({
      diagnostic_id: result.mutation_id,
      thread_id: result.thread_id,
      recorded_at: new Date(result.recorded_at * 1000).toISOString(),
      result: result.status,
      reason_code: result.reason_code,
      stage: result.diagnostic_stage,
      observed_thread_status: result.observed_thread_status,
      mode: result.mode,
      turn_id: result.turn_id,
    }, null, 2);
  }
}

/** A missing server receipt is not evidence of the backend's current thread state. */
export function webPromptTransportDiagnostic(
  locator: WebPromptResultLocator,
  status: FocusPromptResultReceipt['status'],
  reasonCode: string,
  stage = 'browser_transport',
): WebPromptDiagnostic {
  return {
    thread_id: locator.threadId,
    mutation_id: locator.mutationId,
    status,
    reason_code: reasonCode,
    diagnostic_stage: stage,
    observed_thread_status: null,
    recorded_at: Date.now() / 1000,
    mode: null,
    turn_id: '',
  };
}
