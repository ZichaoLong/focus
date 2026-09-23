import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';


function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}


describe('Focus Q&A Markdown export surface', () => {
  it('wires wide and narrow export intents to one fixed-name Blob download', () => {
    const app = source('../src/focus/FocusApp.vue');
    const actions = source('../src/focus/focusThreadActions.ts');
    const narrowTopBar = source('../src/components/narrow/NarrowTopBar.vue');
    const narrowSwitcher = source('../src/components/narrow/NarrowSwitcherSheet.vue');

    expect(app).toContain('@export="exportThreadSummary($event)"');
    expect(app).toContain('@export-session="exportThreadSummary($event)"');
    expect(narrowTopBar).toContain('summaryExportAvailable?: boolean;');
    expect(narrowTopBar).toContain(":label=\"t('header.exportOptions')\"");
    expect(narrowTopBar).toContain('<Icon name="download" size="lg" />');
    expect(narrowTopBar).toContain('@click="exportSession(\'markdown\')"');
    expect(narrowTopBar).toContain("t('header.exportSession')");
    expect(narrowSwitcher).toContain('export: [request: SummaryExportRequest];');
    expect(narrowSwitcher).toContain("emit('export', { threadId: id, format });");
    expect(narrowSwitcher).toContain("t('sidebar.export')");
    expect(narrowSwitcher).toContain("return action !== 'export';");
    expect(actions).toContain("const SUMMARY_EXPORT_FILENAME = 'codex-conversation-summary.md';");
    expect(actions).toContain('(id) => client.exportThreadSummary(id)');
    expect(actions).toContain('client.summaryExporting.value || client.threadDataExporting.value');
    expect(actions).toContain("preparing: 'focus.summaryExportPreparing'");
    expect(actions).toContain('downloadBlob(blob, filename)');
    expect(actions).toContain('anchor.click();');
    expect(actions).toContain('URL.revokeObjectURL(url)');
  });

  it('keeps the Q&A export but removes the misleading loaded-window copy actions', () => {
    const header = source('../src/components/chat/ChatHeader.vue');
    const chatPane = source('../src/components/chat/ChatPane.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');

    expect(header).not.toContain('copyAll');
    expect(header).not.toContain('copyFinalSummary');
    expect(chatPane).not.toContain('copyConversation');
    expect(chatPane).not.toContain('copyFinalSummary');
    expect(pane).not.toContain('@copy-all');
    expect(pane).not.toContain('@copy-final-summary');
    expect(header).toContain('@click="exportSession(\'markdown\')"');
  });

  it('labels the export as Q&A and explains its exact scope', () => {
    const zhSidebar = source('../src/i18n/locales/zh/sidebar.ts');
    const enSidebar = source('../src/i18n/locales/en/sidebar.ts');
    const zhHeader = source('../src/i18n/locales/zh/header.ts');
    const enHeader = source('../src/i18n/locales/en/header.ts');
    const zhFocus = source('../src/i18n/locales/zh/focus.ts');
    const enFocus = source('../src/i18n/locales/en/focus.ts');

    expect(zhSidebar).toContain("export: '导出问答 Markdown'");
    expect(zhHeader).toContain("exportSession: '导出问答 Markdown'");
    expect(zhHeader).toContain("exportOptions: '导出选项'");
    expect(enSidebar).toContain("export: 'Export Q&A Markdown'");
    expect(enHeader).toContain("exportSession: 'Export Q&A Markdown'");
    expect(enHeader).toContain("exportOptions: 'Export options'");
    expect(zhFocus).toContain('仅包含用户问题和最终回答');
    expect(zhFocus).toContain('fcodex 中使用 /export');
    expect(enFocus).toContain('prompts and final replies only');
    expect(enFocus).toContain('Use /export in fcodex');
  });
});
