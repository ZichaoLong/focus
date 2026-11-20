// WebView can acknowledge localStorage writes several seconds before they reach disk.
// Only text drafts and reading preferences are mirrored here. Writer and request
// records continue to use their existing owners.
let database: IDBDatabase | undefined;
let draftPrefix = '';
let readingPrefix = '';

function belongs(key: string): boolean {
  return key.startsWith(draftPrefix) || ['thread-reading.v1', 'reading-thread', 'reading-bookmark'].some(keyName => key === readingPrefix + keyName);
}

function transaction(db: IDBDatabase): IDBTransaction {
  return db.transaction('presentation', 'readwrite', { durability: 'strict' });
}

export async function openMobilePresentation(instance: string): Promise<void> {
  if (typeof indexedDB === 'undefined') return;
  database?.close();
  database = undefined;
  const db = await new Promise<IDBDatabase | undefined>(resolve => {
    let blocked = false;
    const open = indexedDB.open('focus-mobile.presentation.' + instance, 1);
    open.onupgradeneeded = () => open.result.createObjectStore('presentation');
    open.onsuccess = () => { if (blocked) open.result.close(); else resolve(open.result); };
    open.onerror = () => resolve(undefined);
    open.onblocked = () => { blocked = true; resolve(undefined); };
  });
  if (!db) return;
  draftPrefix = 'kimi-web.draft.mobile:' + instance + ':';
  readingPrefix = 'focus-mobile.' + instance + '.focus-web.';
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = transaction(db);
      const store = tx.objectStore('presentation');
      const initialized = store.get('initialized');
      const saved = new Map<string, string>();
      const scan = store.openCursor();
      scan.onsuccess = () => {
        const cursor = scan.result;
        if (cursor) {
          if (typeof cursor.key === 'string' && belongs(cursor.key) && typeof cursor.value === 'string')
            saved.set(cursor.key, cursor.value);
          cursor.continue();
          return;
        }
        try {
          const keys = Object.keys(localStorage).filter(belongs);
          if (initialized.result !== true) {
            for (const key of keys) store.put(localStorage.getItem(key), key);
            store.put(true, 'initialized');
          } else {
            for (const key of keys) if (!saved.has(key)) localStorage.removeItem(key);
            for (const [key, value] of saved) localStorage.setItem(key, value);
          }
        } catch { tx.abort(); }
      };
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error);
    });
    database = db;
    db.onversionchange = () => { database = undefined; db.close(); };
  } catch { db.close(); } // Web Storage remains usable when IndexedDB is unavailable.
}

export function persistMobilePresentation(key: string, value: string | null): void {
  if (!database || !belongs(key)) return;
  try {
    const store = transaction(database).objectStore('presentation');
    if (value === null) store.delete(key);
    else store.put(value, key);
  } catch { /* The live editor still has its Web Storage copy. */ }
}
