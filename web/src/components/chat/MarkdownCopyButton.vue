<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { copyTextToClipboard } from '../../lib/clipboard';
import Icon from '../ui/Icon.vue';
import IconButton from '../ui/IconButton.vue';
import Tooltip from '../ui/Tooltip.vue';

const props = defineProps<{ source: string; label: string }>();
const { t } = useI18n();
const status = ref<'idle' | 'copied' | 'failed'>('idle');
const feedback = computed(() => status.value === 'idle' ? '' : t(`filePreview.${status.value}`));
let timer: ReturnType<typeof setTimeout> | undefined;
let revision = 0;

function reset(): void {
  revision += 1;
  clearTimeout(timer);
  status.value = 'idle';
}

async function copy(): Promise<void> {
  reset();
  const request = revision;
  const ok = await copyTextToClipboard(props.source);
  if (request !== revision) return;
  status.value = ok ? 'copied' : 'failed';
  timer = setTimeout(reset, 1800);
}

watch(() => props.source, reset);
onBeforeUnmount(reset);
</script>

<template>
  <span class="md-copy-control">
    <Tooltip :text="feedback || label">
      <IconButton :label="label" @click.stop="copy">
        <Icon :name="status === 'copied' ? 'check' : 'copy'" size="sm" />
      </IconButton>
    </Tooltip>
    <span class="sr-only" role="status" aria-live="polite">{{ feedback }}</span>
  </span>
</template>

<style scoped>
.md-copy-control {
  display: inline-flex;
  flex: none;
  vertical-align: middle;
}
</style>
