import { isCanonicalWebMutationId } from './webPromptMutation';
import { FOCUS_WEB_RECORDS, hasFocusWebRequiredFields, isFocusWebWireEnum, type FocusWebWireEnum } from './focusWire.generated';

export interface PromptTimingRecord {
  submission_id: string;
  thread_id: string;
  turn_id: string;
  item_id: string;
  submitted_at_ms: number;
  received_at_ms: number | null;
  result: FocusWebWireEnum<'prompt_timing_result'>;
  reason_code: string;
  epoch: string;
  stages: Array<{ name: string; at_ms: number; elapsed_ms: number }>;
  browser: { completed_at_ms?: number; elapsed_ms?: number; result?: string; disconnects?: number };
  updated_at_ms: number;
}

export interface BrowserTimingRecord {
  submission_id: string;
  thread_id: string;
  submitted_at_ms: number;
  browser: PromptTimingRecord['browser'];
}

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const time = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v > 0 && v <= 8_640_000_000_000_000;
const duration = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
export function isBrowserTimingRecord(v: unknown): v is BrowserTimingRecord {
  if (!object(v) || !hasFocusWebRequiredFields('browser_timing', v) || !isCanonicalWebMutationId(v.submission_id)
    || typeof v.thread_id !== 'string' || v.thread_id.length > 128 || !time(v.submitted_at_ms) || !object(v.browser)) return false;
  return Object.entries(v.browser).every(([key, value]) => key === 'completed_at_ms' ? time(value)
    : key === 'elapsed_ms' || key === 'disconnects' ? duration(value) && value <= 86_400_000
    : key === 'result' && isFocusWebWireEnum('prompt_browser_result', value));
}

export function isPromptTimingRecord(v: unknown): v is PromptTimingRecord {
  if (!isBrowserTimingRecord(v) || !object(v)) return false;
  const record: Record<string, unknown> = v as unknown as Record<string, unknown>;
  return isFullTimingRecord(record);
}
function isFullTimingRecord(v: Record<string, unknown>): boolean {
  return object(v)
    && hasFocusWebRequiredFields('prompt_timing', v)
    && Object.keys(v).sort().join(',') === [...FOCUS_WEB_RECORDS.prompt_timing.requiredFields].sort().join(',')
    && ['turn_id', 'item_id', 'result', 'reason_code', 'epoch'].every(key => typeof v[key] === 'string')
    && isFocusWebWireEnum('prompt_timing_result', v.result)
    && (v.received_at_ms === null || time(v.received_at_ms)) && time(v.updated_at_ms)
    && Array.isArray(v.stages) && v.stages.length <= 20 && v.stages.every(stage => object(stage)
      && Object.keys(stage).sort().join(',') === 'at_ms,elapsed_ms,name' && typeof stage.name === 'string'
      && stage.name.length <= 64 && time(stage.at_ms) && duration(stage.elapsed_ms));
}

export function decodePromptTiming(value: unknown): { record: PromptTimingRecord | null } | null {
  return object(value) && Object.keys(value).join(',') === 'record'
    && (value.record === null || isPromptTimingRecord(value.record)) ? { record: value.record } : null;
}
export function decodePromptTimingList(value: unknown): { records: PromptTimingRecord[] } | null {
  return object(value) && Object.keys(value).join(',') === 'records' && Array.isArray(value.records)
    && value.records.length <= 32 && value.records.every(isPromptTimingRecord) ? { records: value.records } : null;
}
export function decodeTimingSync(value: unknown): { accepted: true } | null {
  return object(value) && Object.keys(value).join(',') === 'accepted' && value.accepted === true ? { accepted: true } : null;
}
