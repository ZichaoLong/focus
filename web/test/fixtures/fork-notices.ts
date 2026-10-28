import { createApp, h, ref } from 'vue';
import { i18n } from '../../src/i18n';
import FocusPrimaryNotices from '../../src/focus/FocusPrimaryNotices.vue';
import type { FocusForkResult } from '../../src/focus/types';
i18n.global.locale.value = 'zh';

const note = ref<FocusForkResult | null>({ accepted: true, thread_id: 'branch-exact-id',
  source_thread_id: 'parent', name_warning: '分支已创建，命名未确认。', list_visibility: 'not_found', visibility_diagnostic: '', edit_prompt: null });
createApp({ setup: () => () => h(FocusPrimaryNotices, {
  documentReloadRequired: false, projectionStale: false, projectionReloading: false,
  backendResetOutcomeUnknown: false, error: { message: '', diagnostic: '' },
  promptResultNotices: [], primaryRuntimeErrors: [],
  unknownSubmissionDrafts: [], unknownProcessLocalMutations: [], unknownLifecycleMutations: [],
  mutationBusyByThread: {}, connection: 'connected', canRecoverUnknownSubmission: () => false,
  forkNote: note.value, onDismissForkNote: () => { note.value = null; },
}) }).use(i18n).mount('#app');
