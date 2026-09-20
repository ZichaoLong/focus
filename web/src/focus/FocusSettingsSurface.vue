<script setup lang="ts">
import type { ColorScheme } from '../composables/client/useAppearance';
import type { ComposerSendShortcut } from '../components/chat/composerSendShortcut';
import FocusSettingsDialog from './FocusSettingsDialog.vue';
import type { useFocusWebClient } from './useFocusWebClient';
import type { FocusBackendResetPreview } from './types';

type FocusClient = ReturnType<typeof useFocusWebClient>;

const props = defineProps<{
  open: boolean;
  client: FocusClient;
  colorScheme: ColorScheme;
  activityFaviconEnabled: boolean;
  composerSendShortcut: ComposerSendShortcut;
  setColorScheme: (value: ColorScheme) => void;
  setActivityFaviconEnabled: (value: boolean) => void;
  setComposerSendShortcut: (value: ComposerSendShortcut) => void;
  confirmBackendReset: (preview: FocusBackendResetPreview) => Promise<void>;
  confirmUpdateSource: (url: string) => Promise<void>;
  confirmFocusUpdate: (operationId: string) => Promise<void>;
}>();

const emit = defineEmits<{ 'update:open': [value: boolean] }>();
</script>

<template>
  <FocusSettingsDialog
    :open="props.open"
    :color-scheme="props.colorScheme"
    :turn-window-limit="props.client.turnWindowLimit.value"
    :activity-favicon-enabled="props.activityFaviconEnabled"
    :composer-send-shortcut="props.composerSendShortcut"
    :connection="props.client.connection.value"
    :approval-policy="props.client.approvalPolicy.value"
    :approval-policies="props.client.meta.value?.approval_policies ?? []"
    :reasoning-effort="props.client.thinking.value ?? ''"
    :reasoning-effort-options="props.client.reasoningEffortOptions.value"
    :permissions-profile-id="props.client.permissionsProfileId.value"
    :permissions-profiles="props.client.meta.value?.permissions_profiles ?? []"
    :runtime-identity="props.client.meta.value?.runtime_identity ?? null"
    :archived-threads="props.client.archivedThreads.value"
    :archived-loading="props.client.archivedLoading.value"
    :archived-truncated="props.client.archivedTruncated.value"
    :archived-limit="props.client.archivedLimit.value"
    :lifecycle-busy-by-thread="props.client.mutationBusyByThread.value"
    :backend-reset-preview="props.client.backendResetPreview.value"
    :backend-reset-result="props.client.backendResetResult.value"
    :backend-reset-loading="props.client.backendResetLoading.value"
    :backend-reset-busy="props.client.backendResetBusy.value"
    :backend-reset-outcome-unknown="props.client.backendResetOutcomeUnknown.value"
    :update-status="props.client.updateStatus.value"
    :update-loading="props.client.updateLoading.value"
    :update-busy="props.client.updateBusy.value"
    @update:open="emit('update:open', $event)"
    @set-color-scheme="props.setColorScheme($event)"
    @set-turn-window-limit="props.client.setTurnWindowLimit($event)"
    @set-activity-favicon-enabled="props.setActivityFaviconEnabled($event)"
    @set-composer-send-shortcut="props.setComposerSendShortcut($event)"
    @set-approval-policy="props.client.setApprovalPolicy($event)"
    @set-reasoning-effort="props.client.setReasoningEffort($event)"
    @set-permissions-profile="props.client.setPermissionsProfile($event)"
    @refresh-archived="props.client.refreshArchivedThreads"
    @unarchive="props.client.unarchiveThread($event)"
    @delete-thread="(threadId, confirmation) => props.client.deleteThread(threadId, confirmation)"
    @refresh-backend-reset="props.client.refreshBackendReset"
    @confirm-backend-reset="props.confirmBackendReset"
    @refresh-update="props.client.refreshUpdateStatus"
    @configure-update-source="props.confirmUpdateSource"
    @check-update="(target, commit) => props.client.checkUpdate(target, commit)"
    @apply-update="props.confirmFocusUpdate"
  />
</template>
