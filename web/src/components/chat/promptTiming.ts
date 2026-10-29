import type { InjectionKey } from 'vue';
export interface PromptTimingView {
  submittedAtMs?: number;
  receivedAtMs?: number;
  lines: Array<{ label: string; value: string }>;
  diagnostic: string;
}
export interface PromptTimingReader {
  local(id: string): { submittedAtMs: number } | undefined;
  read(id: string, codexRecordedAtMs?: number): Promise<PromptTimingView>;
}
export const promptTimingKey: InjectionKey<PromptTimingReader> = Symbol('prompt-timing-reader');
