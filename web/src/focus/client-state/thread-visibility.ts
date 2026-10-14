import { computed, readonly, ref, watch, type Ref } from 'vue';
import { safeGetString, safeRemove, safeSetString, STORAGE_KEYS } from '../../lib/storage';

export interface ThreadVisibilityOwner {
  readonly hiddenIds: Readonly<Ref<ReadonlySet<string>>>;
  readonly showHidden: Readonly<Ref<boolean>>;
  setHidden(threadId: string, hidden: boolean): void;
  setShowHidden(value: boolean): void;
  dispose(): void;
}

/** Browser-local directory preference; never acquires runtime or navigation authority. */
export function createThreadVisibility(instance: Readonly<Ref<string>>): ThreadVisibilityOwner {
  const hiddenIds = ref(new Set<string>());
  const showHidden = ref(false);
  const prefix = computed(() => instance.value
    ? `${STORAGE_KEYS.hiddenThreadPrefix}${encodeURIComponent(instance.value)}:`
    : '');
  let disposed = false;

  function readHiddenIds(): Set<string> {
    const result = new Set<string>();
    if (!prefix.value) return result;
    try {
      const storage = globalThis.localStorage;
      for (let index = 0; index < storage.length; index++) {
        const key = storage.key(index);
        if (!key?.startsWith(prefix.value) || storage.getItem(key) !== '1') continue;
        try {
          const id = decodeURIComponent(key.slice(prefix.value.length));
          if (id && id === id.trim()) result.add(id);
        } catch { /* Ignore a malformed preference key. */ }
      }
    } catch { /* Storage may be unavailable; basic chat remains usable. */ }
    return result;
  }

  const stop = watch(prefix, () => {
    hiddenIds.value = readHiddenIds();
    showHidden.value = false;
  }, { immediate: true, flush: 'sync' });

  function replaceHidden(id: string, hidden: boolean): void {
    const next = new Set(hiddenIds.value);
    if (hidden) next.add(id);
    else next.delete(id);
    hiddenIds.value = next;
  }

  function setHidden(threadId: string, hidden: boolean): void {
    const id = threadId.trim();
    if (disposed || !prefix.value || !id) return;
    // One key per thread prevents edits to different threads in other tabs
    // from overwriting each other through a shared read/modify/write array.
    const key = prefix.value + encodeURIComponent(id);
    if (hidden) safeSetString(key, '1');
    else safeRemove(key);
    replaceHidden(id, hidden);
  }

  function onStorage(event: StorageEvent): void {
    if (disposed || !prefix.value) return;
    try {
      if (event.storageArea !== globalThis.localStorage) return;
    } catch { return; }
    if (event.key === null) {
      hiddenIds.value = readHiddenIds();
    } else if (event.key.startsWith(prefix.value)) {
      try {
        const id = decodeURIComponent(event.key.slice(prefix.value.length));
        if (id && id === id.trim()) replaceHidden(id, safeGetString(event.key) === '1');
      } catch { /* Ignore a malformed preference key. */ }
    }
  }
  globalThis.window?.addEventListener?.('storage', onStorage);

  return {
    hiddenIds: readonly(hiddenIds),
    showHidden: readonly(showHidden),
    setHidden,
    setShowHidden(value) { if (!disposed) showHidden.value = value; },
    dispose() {
      disposed = true;
      stop();
      globalThis.window?.removeEventListener?.('storage', onStorage);
    },
  };
}
