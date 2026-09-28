import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createI18n } from 'vue-i18n';
import { describe, expect, it } from 'vitest';
import FocusPromptDiagnostic from '../src/focus/FocusPromptDiagnostic.vue';
import { FocusPromptError, webPromptTransportDiagnostic } from '../src/focus/webPromptDiagnostic';
import focus from '../src/i18n/locales/zh/focus';

const locator = { threadId: 'thread-1', mutationId: '00000000-0000-4000-8000-000000000001' };

describe('Web prompt diagnostic presentation', () => {
  it('never copies input or capabilities from an extended result object', () => {
    const diagnostic = webPromptTransportDiagnostic(locator, 'outcome_unknown', 'transport_error');
    const error = new FocusPromptError('Result unknown', {
      ...diagnostic,
      ...{ text: 'private prompt', attachment_ids: ['private attachment'], token: 'private capability' },
    });
    const value = JSON.parse(error.diagnostic);
    expect(value.observed_thread_status).toBeNull();
    expect(value.mode).toBeNull();
    expect(value.stage).toBe('browser_transport');
    expect(value.diagnostic_id).toBe(locator.mutationId);
    expect(Number.isNaN(Date.parse(value.recorded_at))).toBe(false);
    expect(error.diagnostic).not.toContain('private');
    expect(value).not.toHaveProperty('client_user_message_id');
  });

  it('renders unknown upstream state as selectable escaped text in collapsed details', async () => {
    const error = new FocusPromptError('Not sent', {
      ...webPromptTransportDiagnostic(locator, 'known_no_effect', 'thread_state_unconfirmed'),
      observed_thread_status: '<script>alert(1)</script>',
    });
    const app = createSSRApp({ render: () => h(FocusPromptDiagnostic, { diagnostic: error.diagnostic }) });
    app.use(createI18n({ legacy: false, locale: 'zh', messages: { zh: { focus } } }));
    const html = await renderToString(app);
    expect(html).toContain('复制诊断详情');
    expect(html).toMatch(/<details\b[^>]*>/u);
    expect(html).not.toMatch(/<details\b[^>]*\bopen\b/u);
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain(locator.mutationId);
  });
});
