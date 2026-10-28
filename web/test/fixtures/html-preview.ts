import { createApp, h, ref } from 'vue';
import { i18n } from '../../src/i18n';
import '../../src/style.css';
import FocusFileDownloadDialog from '../../src/focus/FocusFileDownloadDialog.vue';
import { FocusWebApi } from '../../src/focus/api';

i18n.global.locale.value = 'en';
const api = new FocusWebApi();
await api.initialize();
createApp({ setup() {
  const dialog = ref<InstanceType<typeof FocusFileDownloadDialog> | null>(null);
  return () => [h('button', { onClick: () => dialog.value?.open('/work/presentations/deck/index.html', '/work') }, 'Open report'),
    h(FocusFileDownloadDialog, { ref: dialog, api })];
} }).use(i18n).mount('#app');
