import { ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createThreadVisibility, type ThreadVisibilityOwner } from '../../../src/focus/client-state/thread-visibility';
import { STORAGE_KEYS } from '../../../src/lib/storage';

const owners: ThreadVisibilityOwner[] = [];
const listeners = new Set<(event: StorageEvent) => void>();
const key = (instance: string, thread: string) => (
  `${STORAGE_KEYS.hiddenThreadPrefix}${encodeURIComponent(instance)}:${encodeURIComponent(thread)}`
);

function make(instance = ref('one')) {
  const owner = createThreadVisibility(instance);
  owners.push(owner);
  return owner;
}

function storageEvent(key: string | null, storageArea: Storage = localStorage): void {
  for (const listener of listeners) listener({ key, storageArea } as StorageEvent);
}

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key: string) => values.get(key) ?? null,
    key: (index: number) => [...values.keys()][index] ?? null,
    removeItem: (key: string) => { values.delete(key); },
    setItem: (key: string, value: string) => { values.set(key, value); },
  });
  vi.stubGlobal('window', {
    addEventListener: (_name: string, handler: (event: StorageEvent) => void) => listeners.add(handler),
    removeEventListener: (_name: string, handler: (event: StorageEvent) => void) => listeners.delete(handler),
  });
});

afterEach(() => {
  owners.splice(0).forEach(owner => owner.dispose());
  expect(listeners.size).toBe(0);
  vi.unstubAllGlobals();
});

describe('browser and instance thread visibility', () => {
  it('persists exact thread ids across reloads, with explicit restore and no inherited fork state', () => {
    const first = make();
    first.setHidden('parent', true);
    first.setShowHidden(true);
    const reloaded = make();
    expect([...reloaded.hiddenIds.value]).toEqual(['parent']);
    expect(reloaded.hiddenIds.value.has('fork')).toBe(false);
    expect(reloaded.showHidden.value).toBe(false);
    reloaded.setHidden('parent', false);
    expect(make().hiddenIds.value.size).toBe(0);
    expect(localStorage.length).toBe(0);
  });

  it('waits for instance identity and isolates instances even with punctuation in their names', () => {
    const instance = ref('');
    const owner = make(instance);
    owner.setHidden('thread:one', true);
    expect(localStorage.length).toBe(0);
    instance.value = 'a:b';
    owner.setHidden('thread:one', true);
    owner.setShowHidden(true);
    instance.value = 'a';
    expect(owner.hiddenIds.value.size).toBe(0);
    expect(owner.showHidden.value).toBe(false);
    owner.setHidden('b:thread:one', true);
    instance.value = 'a:b';
    expect([...owner.hiddenIds.value]).toEqual(['thread:one']);
    expect(localStorage.length).toBe(2);
  });

  it('merges edits to different threads across tabs and rereads delayed events', () => {
    const first = make();
    const second = make();
    first.setHidden('a', true);
    second.setHidden('b', true);
    storageEvent(key('one', 'a'));
    storageEvent(key('one', 'b'));
    expect([...first.hiddenIds.value].sort()).toEqual(['a', 'b']);
    expect([...second.hiddenIds.value].sort()).toEqual(['a', 'b']);
    first.setHidden('a', false);
    storageEvent(key('one', 'a'));
    expect([...second.hiddenIds.value]).toEqual(['b']);
    localStorage.setItem(key('other', 'c'), '1');
    storageEvent(key('other', 'c'));
    expect([...second.hiddenIds.value]).toEqual(['b']);
    localStorage.clear();
    storageEvent(null);
    expect(first.hiddenIds.value.size).toBe(0);
    expect(second.hiddenIds.value.size).toBe(0);
  });

  it('ignores corrupt preferences and session-storage events', () => {
    localStorage.setItem(key('one', 'valid'), '1');
    localStorage.setItem(key('one', 'invalid-value'), 'true');
    localStorage.setItem(`${STORAGE_KEYS.hiddenThreadPrefix}one:%E0`, '1');
    localStorage.setItem(key('one', ' '), '1');
    const owner = make();
    expect([...owner.hiddenIds.value]).toEqual(['valid']);
    localStorage.clear();
    storageEvent(null, {} as Storage);
    expect([...owner.hiddenIds.value]).toEqual(['valid']);
  });

  it('keeps working in memory when storage is unavailable, and retires listeners on dispose', () => {
    vi.stubGlobal('localStorage', {
      get length() { throw Error('denied'); },
      setItem: () => { throw Error('quota'); },
      removeItem: () => { throw Error('denied'); },
    });
    const owner = make();
    owner.setHidden('a', true);
    expect(owner.hiddenIds.value.has('a')).toBe(true);
    owner.setHidden('a', false);
    expect(owner.hiddenIds.value.size).toBe(0);
    owner.dispose();
    owner.setHidden('a', true);
    owner.setShowHidden(true);
    expect(owner.hiddenIds.value.size).toBe(0);
    expect(owner.showHidden.value).toBe(false);
  });
});
