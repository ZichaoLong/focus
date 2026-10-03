import type { InjectionKey } from 'vue';

/** Lives with the bounded transcript row, surviving its children's unmounts. */
export const markdownChunkHeightsKey: InjectionKey<Map<number, number>> = Symbol('markdownChunkHeights');
