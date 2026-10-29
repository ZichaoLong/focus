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
    add('result', t(`focus.timing.result_${record?.result ?? 'unconfirmed'}`));
    if (browser?.result) add('browserResult', t(`focus.timing.result_${browser.result}`));
    if (record?.reason_code) add('reason', record.reason_code);
    if (browser?.elapsed_ms !== undefined) add('roundTrip', `${browser.elapsed_ms} ms`);
    if (browser?.completed_at_ms) add('browserCompleted', timingDate(browser.completed_at_ms));
    if (browser?.disconnects) add('disconnects', String(browser.disconnects));
    if (record) {
      for (const [start, end, label] of [
        ['service_received', 'prepare_started', 'prepareWait'],
        ['metadata_rpc_started', 'metadata_rpc_returned', 'metadataRpc'],
        ['goal_rpc_started', 'goal_rpc_returned', 'goalRpc'],
        ['app_server_rpc_started', 'app_server_rpc_returned', 'promptRpc'],
        ['service_received', 'settled', 'serviceElapsed'],
      ]) {
        const a = record.stages.find(stage => stage.name === start), b = record.stages.find(stage => stage.name === end);
        if (a && b && b.elapsed_ms >= a.elapsed_ms) add(label!, `${Math.round((b.elapsed_ms - a.elapsed_ms) * 1000) / 1000} ms`);
      }
      for (const stage of record.stages) add(stage.name, timingDate(stage.at_ms));
      add('updated', timingDate(record.updated_at_ms));
    } else add('missing', t('focus.timing.missingHelp'));
    add('upstream', t('focus.timing.notCollected'));
    add('identity', id);
    return { submittedAtMs: record?.submitted_at_ms, lines, diagnostic: JSON.stringify({ server: record, browser: local ?? null }, null, 2) };
  }
  return {
    revision: store.revision, changedId: store.changedId,
    local: id => { const record = store.local(id); return record ? { submittedAtMs: record.submitted_at_ms } : undefined; },
    async read(id) { const result = await store.read(id); return present(result.record, id); },
  };
}
