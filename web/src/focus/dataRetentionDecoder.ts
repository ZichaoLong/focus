import type { FocusDataRetentionPolicy, FocusDataPruneResult } from './types';
import { hasFocusWebRequiredFields } from './focusWire.generated';

function object(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}
export function decodeDataRetention(value: unknown): FocusDataRetentionPolicy | null {
  if (!object(value) || !hasFocusWebRequiredFields('data_retention', value)
    || ![7, 30, 90].includes(value.records_days as number)
    || ![7, 30, 90].includes(value.attachments_days as number)) return null;
  return value as unknown as FocusDataRetentionPolicy;
}
export function decodeDataPrune(value: unknown): FocusDataPruneResult | null {
  const count = (value: unknown) => Number.isSafeInteger(value) && (value as number) >= 0;
  if (!object(value) || !hasFocusWebRequiredFields('data_prune', value)
    || !decodeDataRetention(value.policy) || !object(value.results) || !object(value.errors)
    || !count(value.records) || !count(value.bytes_freed)
    || Object.values(value.results).some(row => !object(row) || !count(row.records) || !count(row.bytes_freed))
    || Object.values(value.errors).some(error => typeof error !== 'string')) return null;
  return value as unknown as FocusDataPruneResult;
}
