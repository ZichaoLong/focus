<script setup lang="ts">
import { shallowRef, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import type { TokensResult } from 'shiki';
import { useIsDark } from '../composables/useIsDark';

const props = defineProps<{ text: string; language: string }>();
const { t } = useI18n();
const dark = useIsDark();
const result = shallowRef<TokensResult | null>(null);
const failed = ref(false);
watch([() => props.text, () => props.language, dark], async (_, __, onCleanup) => {
  let current = true;
  onCleanup(() => { current = false; });
  failed.value = false;
  try {
    const { highlightPreviewCode } = await import('./filePreviewHighlight');
    const highlighted = await highlightPreviewCode(props.text, props.language, dark.value);
    if (current) result.value = highlighted;
  } catch { if (current) { result.value = null; failed.value = true; } }
}, { immediate: true });
</script>

<template>
  <div class="file-preview-code" :style="result ? { background: result.bg, color: result.fg } : undefined">
    <p v-if="failed" role="status">{{ t('focus.filePreviewHighlightFailed') }}</p>
    <pre v-if="result" :aria-label="language"><code><span v-for="(line, index) in result.tokens" :key="index" class="code-line"><span v-for="(token, part) in line" :key="part"
      :style="{ color: token.color, fontStyle: (token.fontStyle ?? 0) & 1 ? 'italic' : undefined, fontWeight: (token.fontStyle ?? 0) & 2 ? 'bold' : undefined,
        textDecoration: (token.fontStyle ?? 0) & 4 ? 'underline' : undefined }">{{ token.content }}</span>{{ index < result.tokens.length - 1 ? '\n' : '' }}</span></code></pre>
    <pre v-else :aria-label="language">{{ text }}</pre>
  </div>
</template>

<style scoped>
.file-preview-code { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; padding: var(--space-4); }
.file-preview-code pre { margin: 0; font: 400 14px/22px var(--font-mono); white-space: pre; tab-size: 4; }
.file-preview-code p { font-size: var(--text-sm); }
</style>
