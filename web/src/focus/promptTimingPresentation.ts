import type { PromptTimingReader, PromptTimingView } from '../components/chat/promptTiming';
import type { PromptTimingStore } from './promptTimingStore';
import type { PromptTimingRecord } from './promptTimingTypes';

export const timingDate = (value: number) => new Date(value).toLocaleString(undefined, {
  year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', fractionalSecondDigits: 3,
});

export function createPromptTimingReader(store: PromptTimingStore, t: (key: string) => string): PromptTimingReader {
  function present(record: PromptTimingRecord | null, id: string): PromptTimingView {
    const local = store.local(id);
    const browser = local?.browser ?? record?.browser;
    const lines: PromptTimingView['lines'] = [];
    const add = (label: string, value: string) => lines.push({ label: t(`focus.timing.${label}`), value });
    if (record?.received_at_ms) add('serviceReceived', timingDate(record.received_at_ms));
    if (record) add('result', t(`focus.timing.result_${record.result}`));
    else add('missing', t('focus.timing.notFound'));
    if (browser?.result && browser.result !== record?.result) add('browserResult', t(`focus.timing.result_${browser.result}`));
    if (browser?.elapsed_ms !== undefined) add('roundTrip', `${browser.elapsed_ms} ms`);
    if (record) {
      const received = record.stages.find(stage => stage.name === 'service_received');
      const settled = record.stages.find(stage => stage.name === 'settled');
      if (received && settled && settled.elapsed_ms >= received.elapsed_ms) {
        add('serviceElapsed', `${Math.round((settled.elapsed_ms - received.elapsed_ms) * 1000) / 1000} ms`);
      }
    }
    add('upstream', t('focus.timing.collectionNotIntegrated'));
    add('identity', id);
    return { submittedAtMs: record?.submitted_at_ms, lines, diagnostic: JSON.stringify({ server: record, browser: local ?? null }, null, 2) };
  }
  return {
    local: id => { const record = store.local(id); return record ? { submittedAtMs: record.submitted_at_ms } : undefined; },
    async read(id) { const result = await store.read(id); return present(result.record, id); },
  };
}
