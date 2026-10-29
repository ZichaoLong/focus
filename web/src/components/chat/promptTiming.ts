import type { InjectionKey, Ref } from 'vue';
export interface PromptTimingView {
  submittedAtMs?: number;
  lines: Array<{ label: string; value: string }>;
  diagnostic: string;
}
export interface PromptTimingReader {
  revision: Readonly<Ref<number>>;
  changedId: Readonly<Ref<string>>;
  local(id: string): { submittedAtMs: number } | undefined;
  read(id: string): Promise<PromptTimingView>;
}
export const promptTimingKey: InjectionKey<PromptTimingReader> = Symbol('prompt-timing-reader');
