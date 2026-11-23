import { createApp } from 'vue';
import i18n from '../i18n';
import '../style.css';
import { loadMarkdown } from '../components/chat/LazyMarkdown.vue';
import SavedConversation from './SavedConversation.vue';

// Lazy chunks may import the shared runtime from this entry. Finish evaluating it before mounting.
const mount = () => createApp(SavedConversation).use(i18n).mount('#app');
void loadMarkdown().then(mount, mount);
