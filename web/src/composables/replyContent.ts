import type { InjectionKey, Ref } from 'vue';
import type { ChatTurn } from '../types';

export interface ReplyContentState { text: string | null; loading: boolean; error: string }
export interface ReplyContentLease {
  state: Readonly<Ref<ReplyContentState>>;
  retry(): void;
  release(): void;
}
export interface ReplyContentReader { acquire(turn: ChatTurn): ReplyContentLease }
export const replyContentReaderKey: InjectionKey<ReplyContentReader> = Symbol('replyContentReader');
