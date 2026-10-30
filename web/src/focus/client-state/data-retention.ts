import { ref } from 'vue';
import { i18n } from '../../i18n';
import { pruneBrowserData, setBrowserRetentionDays } from '../../lib/dataRetention';
import type { FocusWebApiPort } from '../api';
import type { FocusDataRetentionPolicy } from '../types';

export function createDataRetention(api: FocusWebApiPort) {
  const policy = ref<FocusDataRetentionPolicy | null>(null);
  const busy = ref(false);
  const notice = ref('');
  let timer: ReturnType<typeof setInterval> | null = null;
  let disposed = false;
  function install(value: FocusDataRetentionPolicy): void {
    if (disposed) return;
    policy.value = value;
    setBrowserRetentionDays(value.records_days);
  }
  async function refresh(): Promise<boolean> {
    if (!api.readDataRetention || busy.value || disposed) return false;
    busy.value = true;
    try { install(await api.readDataRetention()); return !disposed; }
    catch { if (!disposed) notice.value = i18n.global.t('focus.retentionUnavailable'); return false; }
    finally { busy.value = false; }
  }
  async function update(changes: Partial<FocusDataRetentionPolicy>): Promise<void> {
    if (!api.updateDataRetention || busy.value || disposed) return;
    busy.value = true;
    notice.value = '';
    try { install(await api.updateDataRetention(changes)); }
    catch { if (!disposed) notice.value = i18n.global.t('focus.retentionSaveFailed'); }
    finally { busy.value = false; }
  }
  async function prune(): Promise<void> {
    if (!api.pruneData || busy.value || disposed) return;
    busy.value = true;
    notice.value = '';
    try {
      const result = await api.pruneData();
      if (disposed) return;
      install(result.policy);
      let local = 0;
      let failed = Object.keys(result.errors).length > 0;
      try { local = pruneBrowserData(); } catch { failed = true; }
      notice.value = i18n.global.t('focus.retentionCleaned', { server: result.records, browser: local })
        + (failed ? ` ${i18n.global.t('focus.retentionPartial')}` : '');
    } catch { if (!disposed) notice.value = i18n.global.t('focus.retentionCleanFailed'); }
    finally { busy.value = false; }
  }
  async function sweep(): Promise<void> {
    if (await refresh()) {
      try { pruneBrowserData(); }
      catch { notice.value = i18n.global.t('focus.retentionBrowserFailed'); }
    }
  }
  function start(): void {
    if (disposed || timer !== null || !api.readDataRetention) return;
    void sweep();
    timer = setInterval(() => { void sweep(); }, 30 * 60 * 1000);
  }
  function dispose(): void {
    disposed = true;
    if (timer !== null) clearInterval(timer);
    timer = null;
  }
  return { policy, busy, notice, refresh, update, prune, start, dispose };
}
export type DataRetentionOwner = ReturnType<typeof createDataRetention>;
