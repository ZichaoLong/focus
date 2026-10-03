import { describe, expect, it } from 'vitest';
import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createI18n } from 'vue-i18n';
import ReplyTime from '../src/components/chat/ReplyTime.vue';
import type { ReplyMetadata } from '../src/types';
import conversation from '../src/i18n/locales/en/conversation';

async function render(reply: ReplyMetadata) {
  const app = createSSRApp({ render: () => h(ReplyTime, { reply }) });
  app.use(createI18n({ legacy: false, locale: 'en', messages: { en: { conversation } } }));
  return renderToString(app);
}

describe('source reply timestamps', () => {
  it('does not invent a timestamp for historical or untimed live messages', async () => {
    expect(await render({ state: 'unknown' })).not.toContain('<button');
    expect(await render({ state: 'generating' })).not.toContain('<button');
  });
  it('shows start time while generating, then prefers completion time', async () => {
    const start = new Date(2026, 9, 1, 12, 34).getTime(); const end = start + 2 * 60_000;
    expect(await render({ state: 'generating', startedAtMs: start })).toContain('12:34');
    expect(await render({ state: 'generating', startedAtMs: start })).toContain('Generating');
    const complete = await render({ state: 'complete', startedAtMs: start, completedAtMs: end });
    expect(complete).toContain('12:36'); expect(complete).not.toContain('Generating');
  });
});
