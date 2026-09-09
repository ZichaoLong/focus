import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick, ref, type Ref } from 'vue';
import { useMentionMenu } from '../src/composables/useMentionMenu';
import type { FileItem } from '../src/types';

interface MockTextarea {
  value: string;
  selectionStart: number;
  setSelectionRange: (start: number, end: number) => void;
  focus: () => void;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function setup(initialText = '', searchFiles?: (q: string) => Promise<FileItem[]>) {
  const textarea: MockTextarea = {
    value: initialText,
    // Caret defaults to the end of the text.
    selectionStart: initialText.length,
    setSelectionRange(start: number) {
      this.selectionStart = start;
    },
    focus: () => {},
  };
  const text = ref(initialText);
  const textareaRef = ref(textarea as unknown as HTMLTextAreaElement) as Ref<HTMLTextAreaElement | null>;
  const mention = useMentionMenu({
    text,
    textareaRef,
    autosize: () => {},
    searchFiles: () => searchFiles,
  });
  return { text, textarea, mention };
}

describe('useMentionMenu — update', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('stays closed when there is no @token', async () => {
    const searchFiles = vi.fn().mockResolvedValue([]);
    const { mention } = setup('hello', searchFiles);
    mention.update();
    await vi.advanceTimersByTimeAsync(200);
    expect(mention.open.value).toBe(false);
    expect(searchFiles).not.toHaveBeenCalled();
  });

  it('stays closed when searchFiles is not provided', async () => {
    const { mention } = setup('@a');
    mention.update();
    await vi.advanceTimersByTimeAsync(200);
    expect(mention.open.value).toBe(false);
  });

  it('opens with search results after the debounce', async () => {
    const searchFiles = vi.fn().mockResolvedValue([{ path: 'src/a.ts', name: 'a.ts' }]);
    const { mention } = setup('@a', searchFiles);
    mention.update();
    expect(mention.open.value).toBe(true);
    expect(mention.loading.value).toBe(true);
    expect(mention.items.value).toEqual([]);
    await vi.advanceTimersByTimeAsync(200);
    expect(searchFiles).toHaveBeenCalledWith('a');
    expect(mention.open.value).toBe(true);
    expect(mention.items.value).toEqual([{ path: 'src/a.ts', name: 'a.ts' }]);
    expect(mention.loading.value).toBe(false);
    expect(mention.active.value).toBe(0);
  });

  it('clears items and stops loading when the search throws', async () => {
    const searchFiles = vi.fn().mockRejectedValue(new Error('boom'));
    const { mention } = setup('@a', searchFiles);
    mention.update();
    await vi.advanceTimersByTimeAsync(200);
    expect(mention.items.value).toEqual([]);
    expect(mention.loading.value).toBe(false);
  });

  it('never publishes an older search while the latest token is pending', async () => {
    const older = deferred<FileItem[]>();
    const latest = deferred<FileItem[]>();
    const searchFiles = vi.fn((query: string) => (
      query === 'a' ? older.promise : latest.promise
    ));
    const { text, textarea, mention } = setup('@a', searchFiles);

    mention.update();
    await vi.advanceTimersByTimeAsync(200);
    expect(searchFiles).toHaveBeenCalledWith('a');

    text.value = '@ab';
    textarea.value = '@ab';
    textarea.selectionStart = 3;
    mention.update();
    expect(mention.open.value).toBe(true);
    expect(mention.loading.value).toBe(true);
    expect(mention.items.value).toEqual([]);
    await vi.advanceTimersByTimeAsync(200);
    expect(searchFiles).toHaveBeenCalledWith('ab');

    older.resolve([{ path: 'src/old.ts', name: 'old.ts' }]);
    await Promise.resolve();
    expect(mention.loading.value).toBe(true);
    expect(mention.items.value).toEqual([]);

    latest.resolve([{ path: 'src/latest.ts', name: 'latest.ts' }]);
    await Promise.resolve();
    expect(mention.loading.value).toBe(false);
    expect(mention.items.value).toEqual([{ path: 'src/latest.ts', name: 'latest.ts' }]);
  });

  it('invalidates an in-flight search when the mention token disappears', async () => {
    const pending = deferred<FileItem[]>();
    const { text, textarea, mention } = setup('@a', () => pending.promise);

    mention.update();
    await vi.advanceTimersByTimeAsync(200);
    text.value = 'plain';
    textarea.value = 'plain';
    textarea.selectionStart = 5;
    mention.update();
    expect(mention.open.value).toBe(false);
    expect(mention.loading.value).toBe(false);

    pending.resolve([{ path: 'src/stale.ts', name: 'stale.ts' }]);
    await Promise.resolve();
    expect(mention.open.value).toBe(false);
    expect(mention.loading.value).toBe(false);
    expect(mention.items.value).toEqual([]);
  });
});

describe('useMentionMenu — select', () => {
  it('replaces the @token with the chosen path', async () => {
    const { text, textarea, mention } = setup('hello @a');
    textarea.value = 'hello @a';
    mention.select({ path: 'src/a.ts', name: 'a.ts' });
    expect(text.value).toBe('hello src/a.ts');
    expect(mention.open.value).toBe(false);
    await nextTick();
  });

  it('is a no-op when there is no @token', () => {
    const { text, mention } = setup('hello');
    mention.select({ path: 'src/a.ts', name: 'a.ts' });
    expect(text.value).toBe('hello');
  });
});
