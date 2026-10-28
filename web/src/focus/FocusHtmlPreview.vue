<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import type { FilePreviewRequest } from '../types';
import { parseLocalFileHref } from '../lib/filePathLinks';
import { focusWebEndpointPath } from './focusWire.generated';

const props = defineProps<{ text: string; anchor?: string }>();
const emit = defineEmits<{ openFile: [target: FilePreviewRequest] }>();
const { t } = useI18n();
const frame = ref<HTMLIFrameElement | null>(null);
const ready = ref(false);
const notice = ref('');
let channel: MessageChannel | null = null;
let timeout: ReturnType<typeof setTimeout> | undefined;
let disposed = false;

function load(): void {
  // document.write in the sandbox also emits load. Never hand a second port or
  // source to a document that already ran file scripts or navigated elsewhere.
  if (channel || disposed || !frame.value?.contentWindow) return;
  channel = new MessageChannel();
  channel.port1.onmessage = event => {
    if (disposed) return;
    const message: unknown = event.data;
    if (!message || typeof message !== 'object' || !('type' in message)) return;
    if (message.type === 'rendered') { ready.value = true; clearTimeout(timeout); }
    else if (message.type === 'blocked-resource') notice.value = 'focus.filePreviewHtmlResources';
    else if (message.type === 'script-error') notice.value = 'focus.filePreviewHtmlScriptError';
    else if (message.type === 'link' && 'href' in message && typeof message.href === 'string' && message.href.length <= 8192) {
      const target = parseLocalFileHref(message.href);
      if (target) emit('openFile', target);
      else notice.value = 'focus.filePreviewHtmlExternalLink';
    }
  };
  frame.value.contentWindow.postMessage({ type: 'focus-html-preview', html: props.text }, '*', [channel.port2]);
}

onMounted(() => {
  timeout = setTimeout(() => { if (!ready.value) notice.value = 'focus.filePreviewHtmlFailed'; }, 10_000);
});

onBeforeUnmount(() => {
  disposed = true;
  clearTimeout(timeout);
  channel?.port1.close();
  channel?.port2.close();
});
</script>

<template>
  <div class="html-preview">
    <p v-if="notice" class="html-preview-notice" role="status">{{ t(notice) }}</p>
    <p v-else-if="!ready" class="html-preview-notice" role="status">{{ t('focus.filePreviewHtmlStarting') }}</p>
    <iframe ref="frame" :src="focusWebEndpointPath('html_preview') + (anchor ? `#${encodeURIComponent(anchor)}` : '')" :title="t('focus.filePreviewHtmlTitle')"
      sandbox="allow-scripts" allow="fullscreen *" referrerpolicy="no-referrer" tabindex="0" @load="load" />
  </div>
</template>

<style scoped>
.html-preview { display: flex; flex-direction: column; flex: 1; min-height: 0; }
.html-preview iframe { flex: 1; min-height: 0; width: 100%; border: 0; background: white; }
.html-preview-notice { flex: none; margin: 0; padding: var(--space-2) var(--space-3); font-size: var(--text-sm); color: var(--color-text-muted); }
</style>
