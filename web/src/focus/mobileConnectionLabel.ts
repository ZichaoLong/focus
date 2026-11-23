import { computed, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { FocusTransportConnectionState } from './focusTransportSession';

export function useMobileConnectionLabel(connection: () => FocusTransportConnectionState) {
  const { t } = useI18n();
  const online = ref(navigator.onLine !== false);
  const update = () => { online.value = navigator.onLine !== false; };
  window.addEventListener('online', update);
  window.addEventListener('offline', update);
  onUnmounted(() => {
    window.removeEventListener('online', update);
    window.removeEventListener('offline', update);
  });
  const delayed = ref(false);
  watch(() => online.value && connection() === 'connecting', (connecting, _, cleanup) => {
    delayed.value = false;
    if (connecting) {
      const timer = setTimeout(() => { delayed.value = true; }, 700);
      cleanup(() => clearTimeout(timer));
    }
  }, { immediate: true });
  return computed(() => {
    if (!online.value) return t('focus.savedOffline');
    if (connection() === 'disconnected') return t('focus.siteUnreachable');
    return delayed.value ? t('focus.connectingInstance') : '';
  });
}
