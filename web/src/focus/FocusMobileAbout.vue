<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import Dialog from '../components/ui/Dialog.vue';
import Button from '../components/ui/Button.vue';
import SegmentedControl from '../components/ui/SegmentedControl.vue';
import { mobileApkRequest } from '../lib/mobileHost';
import { focusWebEndpointPath } from './focusWire.generated';
import type { FocusAndroidChannel, FocusUpdateTarget } from './types';

const props = defineProps<{ check: (channel: FocusUpdateTarget) => Promise<FocusAndroidChannel>; instance: string }>();
const emit = defineEmits<{ close: [] }>();
const { t } = useI18n();
const installed = ref<{ version: string; version_code: number; sha256: string } | null>(null);
const target = ref<FocusUpdateTarget>('main');
const result = ref<FocusAndroidChannel | null>(null);
const message = ref('');
const busy = ref(false);
const controller = new AbortController();
try {
  const info = JSON.parse(mobileApkRequest('info'));
  if (!info || typeof info.version !== 'string' || !Number.isSafeInteger(info.version_code) || typeof info.sha256 !== 'string')
    throw new Error(t('focus.mobileIdentityError'));
  installed.value = info;
} catch (error) { message.value = String(error); }
onBeforeUnmount(() => controller.abort());

async function check(): Promise<void> {
  busy.value = true;
  result.value = null;
  message.value = '';
  try { result.value = await props.check(target.value); }
  catch (error) { message.value = String(error); }
  finally { busy.value = false; }
}

async function download(save: boolean): Promise<void> {
  const release = result.value?.release;
  if (!release || busy.value) return;
  busy.value = true;
  message.value = '';
  let installing = false;
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const response = await fetch(focusWebEndpointPath('mobile_android_apk', { digest: release.sha256 }), {
      credentials: 'same-origin', redirect: 'error', signal: controller.signal,
    });
    if (!response.ok || !response.body) throw new Error('HTTP ' + response.status);
    mobileApkRequest('begin', JSON.stringify(release));
    installing = true;
    reader = response.body.getReader();
    for (;;) {
      const block = await reader.read();
      if (block.done) break;
      for (let start = 0; start < block.value.length; start += 24576) {
        controller.signal.throwIfAborted();
        mobileApkRequest('write', btoa(String.fromCharCode(...block.value.subarray(start, start + 24576))));
      }
    }
    const reply = mobileApkRequest(save ? 'save' : 'finish');
    if (save && reply === 'ok') message.value = t('focus.mobileSaved');
    installing = false;
  } catch (error) { message.value = String(error); }
  finally {
    if (installing) { try { mobileApkRequest('abort'); } catch { /* Page already left. */ } }
    await reader?.cancel().catch(() => {});
    reader?.releaseLock();
    busy.value = false;
  }
}
</script>

<template>
  <Dialog :open="true" :title="t('focus.mobileAbout')" :description="installed ? installed.version + ' · ' + instance : instance" @close="emit('close')">
    <div class="mobile-release">
      <SegmentedControl :model-value="target" :options="[{ value: 'main', label: 'main' }, { value: 'stable', label: 'stable' }]"
        :disabled="busy || !installed" @update:model-value="v => { if (!busy && installed && (v === 'main' || v === 'stable')) { target = v; result = null; message = ''; } }" />
      <Button :disabled="busy || !installed" @click="check">{{ t('focus.mobileCheck') }}</Button>
      <template v-if="result">
        <span v-if="result.stale">{{ t('focus.mobileCached', { date: new Date(result.checked_at * 1000).toLocaleString() }) }}</span>
        <template v-if="result.release && installed">
          <strong>{{ result.release.version }} · {{ result.release.source_revision.slice(0, 12) }}</strong>
          <span v-if="result.release.sha256 === installed.sha256">{{ t('focus.mobileInstalled') }}</span>
          <span v-else-if="result.release.version_code < installed.version_code">{{ t('focus.mobileOlder') }}</span>
          <Button v-else variant="primary" :disabled="busy" @click="download(false)">{{ t('focus.mobileInstall') }}</Button>
          <Button v-if="result.release.version_code >= installed.version_code" :disabled="busy" @click="download(true)">{{ t('focus.mobileSave') }}</Button>
        </template>
        <span v-else>{{ t('focus.mobileUnpublished') }}</span>
      </template>
      <span v-if="message" role="status">{{ message }}</span>
    </div>
  </Dialog>
</template>

<style scoped>
.mobile-release { display: grid; gap: var(--space-3); min-width: 0; overflow-wrap: anywhere; }
</style>
