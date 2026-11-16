import { createApp, h, ref } from 'vue';
import { i18n } from '../../src/i18n';
import '../../src/style.css';
import FocusFileDownloadDialog from '../../src/focus/FocusFileDownloadDialog.vue';
import { FocusWebApi } from '../../src/focus/api';

i18n.global.locale.value = 'en';
const api = new FocusWebApi();
await api.initialize();
const name = new URLSearchParams(location.search).get('file') || 'sample.pdf';
createApp({ setup() {
  const dialog = ref<InstanceType<typeof FocusFileDownloadDialog> | null>(null);
  return () => [h('button', { onClick: () => dialog.value?.open(`/work/${name}`, '/work') }, 'Open file'),
    h(FocusFileDownloadDialog, { ref: dialog, api })];
} }).use(i18n).mount('#app');
