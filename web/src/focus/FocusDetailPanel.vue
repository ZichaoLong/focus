<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import AgentDetailPanel from '../components/chat/AgentDetailPanel.vue';
import ThinkingPanel from '../components/chat/ThinkingPanel.vue';
import ToolDiffPanel from '../components/chat/ToolDiffPanel.vue';
import Button from '../components/ui/Button.vue';
import type { AgentMember, AppGoal, ToolCall, ToolMedia } from '../types';
import FocusConversationSearchPanel from './FocusConversationSearchPanel.vue';
import FocusMediaPanel from './FocusMediaPanel.vue';
import FocusRuntimeDetailsPanel from './FocusRuntimeDetailsPanel.vue';
import FocusToolSourceDetailPanel from './FocusToolSourceDetailPanel.vue';
import type { RuntimeDetailsPresentation } from './runtimeDetailsPresentation';
import type {
  FocusConversationSearchOccurrence,
  FocusThreadConversationSearchPage,
  FocusThreadToolDetailPayload,
  FocusThreadInspectionUnavailableReason,
} from './types';

const props = defineProps<{
  target: 'runtimeDetails' | 'thinking' | 'toolDiff' | 'conversationSearch' | 'media' | 'agent';
  runtimeDetailsPresentation: RuntimeDetailsPresentation;
  goal: AppGoal | null;
  canControlGoal: boolean;
  actionBusy: boolean;
  errorMessage: string;
  thinkingText: string;
  tool: ToolCall | null;
  toolDetail: FocusThreadToolDetailPayload | null;
  toolDetailChangeIndex: number | null;
  toolDetailLoading: boolean;
  toolDetailError: boolean;
  toolDetailScanStatus: 'idle' | 'loading' | 'scanning' | 'not_found' | 'found' | 'cancelled' | 'error';
  toolDetailScannedItems: number;
  toolDetailUnavailableReason: FocusThreadInspectionUnavailableReason | null;
  conversationSearchUnavailableReason: FocusThreadInspectionUnavailableReason | null;
  conversationSearchLoading: boolean;
  conversationSearchError: boolean;
  conversationSearchPage: FocusThreadConversationSearchPage | null;
  mediaTarget: ToolMedia | null;
  agentMember: AgentMember | null;
}>();

const { t } = useI18n();
const toolDetailUnavailableMessage = computed(() => {
  const reason = props.toolDetailUnavailableReason;
  if (reason === null) return '';
  const keys: Record<FocusThreadInspectionUnavailableReason, string> = {
    build_unsupported: 'tools.detail.unavailableBuild',
    document_unavailable: 'tools.detail.unavailableDocument',
    legacy_history: 'tools.detail.unavailableLegacy',
    no_active_thread: 'tools.detail.unavailableNoThread',
    runtime_unsupported: 'tools.detail.unavailableRuntime',
    thread_not_materialized: 'tools.detail.unavailableMaterializing',
    unknown_history: 'tools.detail.unavailableUnknown',
  };
  return t(keys[reason]);
});
const fullToolDetailSource = computed(() => (
  props.toolDetail?.view === 'full' ? props.toolDetail.source : null
));

const emit = defineEmits<{
  close: [];
  controlGoal: [action: 'pause' | 'resume' | 'cancel'];
  cancelToolDetail: [];
  retryToolDetail: [];
  searchConversation: [query: string];
  nextConversationSearchPage: [];
  selectConversationSearchOccurrence: [occurrence: FocusConversationSearchOccurrence];
}>();
</script>

<template>
  <FocusRuntimeDetailsPanel
    v-if="target === 'runtimeDetails'"
    :presentation="runtimeDetailsPresentation"
    :goal="goal"
    :can-control-goal="canControlGoal"
    :action-busy="actionBusy"
    :error-message="errorMessage"
    @close="emit('close')"
    @control-goal="emit('controlGoal', $event)"
  />
  <ThinkingPanel
    v-else-if="target === 'thinking'"
    :text="thinkingText"
    @close="emit('close')"
  />
  <FocusToolSourceDetailPanel
    v-else-if="target === 'toolDiff' && fullToolDetailSource"
    :source="fullToolDetailSource"
    :change-index="toolDetailChangeIndex"
    @close="emit('close')"
  />
  <div v-else-if="target === 'toolDiff' && tool" class="focus-tool-detail-preview">
    <ToolDiffPanel
      :tool="tool"
      :loading="toolDetailLoading"
      :error="toolDetailError"
      :scan-status="toolDetailScanStatus"
      :scanned-items="toolDetailScannedItems"
      :unavailable-message="toolDetailUnavailableMessage"
      @close="emit('close')"
      @cancel-tool-detail="emit('cancelToolDetail')"
    />
    <Button v-if="!toolDetailLoading && !toolDetailUnavailableReason && ['error', 'cancelled', 'not_found'].includes(toolDetailScanStatus)"
      @click="emit('retryToolDetail')">{{ t('tools.detail.refresh') }}</Button>
  </div>
  <FocusConversationSearchPanel
    v-else-if="target === 'conversationSearch'"
    :unavailable-reason="conversationSearchUnavailableReason"
    :loading="conversationSearchLoading"
    :error="conversationSearchError"
    :page="conversationSearchPage"
    @close="emit('close')"
    @search="emit('searchConversation', $event)"
    @next="emit('nextConversationSearchPage')"
    @select="emit('selectConversationSearchOccurrence', $event)"
  />
  <FocusMediaPanel
    v-else-if="target === 'media' && mediaTarget"
    :media="mediaTarget"
    @close="emit('close')"
  />
  <AgentDetailPanel
    v-else-if="target === 'agent' && agentMember"
    :member="agentMember"
    @close="emit('close')"
  />
</template>

<style scoped>
.focus-tool-detail-preview {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.focus-tool-detail-preview :deep(.tdp) {
  flex: 1;
  min-height: 0;
  height: auto;
}
</style>
