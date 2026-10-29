import type { PromptTimingReader, PromptTimingView } from '../components/chat/promptTiming';
import type { PromptTimingStore } from './promptTimingStore';
import type { PromptTimingRecord } from './promptTimingTypes';

export const timingDate = (value: number) => new Date(value).toLocaleString(undefined, {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
});

export function createPromptTimingReader(store: PromptTimingStore, t: (key: string) => string): PromptTimingReader {
  function present(record: PromptTimingRecord | null, id: string, codexRecordedAtMs?: number): PromptTimingView {
    const local = store.local(id);
    const browser = local?.browser ?? record?.browser;
    const lines: PromptTimingView['lines'] = [];
    const add = (label: string, value: string) => lines.push({ label: t(`focus.timing.${label}`), value });
    if (codexRecordedAtMs === undefined) {
      if (record) add('result', t(`focus.timing.result_${record.result}`));
      else add('missing', t('focus.timing.notFound'));
      if (browser?.result && browser.result !== record?.result) add('browserResult', t(`focus.timing.result_${browser.result}`));
    }
    const output = record?.first_output;
    add('firstOutput', output?.status === 'observed' ? timingDate(output.at_ms)
      : t(`focus.timing.output_${output?.status ?? 'not_recorded'}`));
    add('identity', id);
    const durations: Record<string, number> = {};
    if (browser?.elapsed_ms !== undefined) durations.browser_submit = browser.elapsed_ms;
    if (record) {
      for (const [start, end, label] of [
        ['service_received', 'prepare_started', 'prepare'],
        ['metadata_rpc_started', 'metadata_rpc_returned', 'metadata_rpc'],
        ['goal_rpc_started', 'goal_rpc_returned', 'goal_rpc'],
        ['app_server_rpc_started', 'app_server_rpc_returned', 'input_rpc'],
        ['service_received', 'settled', 'focus_submit'],
      ]) {
        const a = record.stages.find(stage => stage.name === start), b = record.stages.find(stage => stage.name === end);
        if (a && b && b.elapsed_ms >= a.elapsed_ms) durations[label!] = Math.round((b.elapsed_ms - a.elapsed_ms) * 1000) / 1000;
      }
      const received = record.stages.find(stage => stage.name === 'service_received');
      if (received && output?.status === 'observed' && output.elapsed_ms >= received.elapsed_ms) {
        durations.focus_first_output = Math.round((output.elapsed_ms - received.elapsed_ms) * 1000) / 1000;
      }
    }
    return {
      submittedAtMs: record?.submitted_at_ms, receivedAtMs: record?.received_at_ms ?? undefined, lines,
      diagnostic: JSON.stringify({ server: record, browser: local ?? null, codex_recorded_at_ms: codexRecordedAtMs,
        durations_ms: durations, model_upstream: { collection: 'not_integrated' } }, null, 2),
    };
  }
  return {
    local: id => { const record = store.local(id); return record ? { submittedAtMs: record.submitted_at_ms } : undefined; },
    async read(id, codexRecordedAtMs) { const result = await store.read(id); return present(result.record, id, codexRecordedAtMs); },
  };
}
