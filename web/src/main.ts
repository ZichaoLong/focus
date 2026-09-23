import { createApp } from 'vue';
import i18n from './i18n';
import { installClientErrorCapture } from './debug/trace';
import '@fontsource-variable/inter/opsz.css';
import '@fontsource-variable/inter/opsz-italic.css';
import '@fontsource-variable/jetbrains-mono/wght.css';
import './style.css';

// Always retain bounded metadata for uncaught failures. With ?debug=1 / the
// debug flag, console output is included too; HMR restores listeners/wrappers.
installClientErrorCapture();

// A print preview is a standalone document, not another active Focus client.
const app = new URLSearchParams(window.location.search).get('print') === 'summary'
  ? await import('./focus/SummaryPrintApp.vue')
  : await import('./focus/FocusApp.vue');
createApp(app.default).use(i18n).mount('#app');
