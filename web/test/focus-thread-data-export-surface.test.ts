import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';


function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}


describe('Focus current-thread data export surface', () => {
  it('offers a fixed-name JSONL download from active-thread chrome in both layouts', () => {
    const app = source('../src/focus/FocusApp.vue');
    const actions = source('../src/focus/focusThreadActions.ts');
    const header = source('../src/components/chat/ChatHeader.vue');
    const narrowTopBar = source('../src/components/narrow/NarrowTopBar.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');

    expect(actions).toContain("const THREAD_DATA_EXPORT_FILENAME = 'codex-thread-data.jsonl';");
    expect(app).toContain('const threadDataExportAvailable = computed(() => (');
    expect(app).toContain("client.activeThread.value?.history_mode === 'paginated'");
    expect(app).toContain('@export-thread-data="exportThreadData($event)"');
    expect(actions).toContain('(id) => client.exportThreadData(id)');
    expect(actions).toContain('downloadBlob(blob, filename)');
    expect(header).toContain('@click="exportThreadData"');
    expect(header).toContain("t('header.exportThreadData')");
    expect(narrowTopBar).toContain('threadDataExportAvailable?: boolean;');
    expect(narrowTopBar).toContain('@click="exportThreadData"');
    expect(narrowTopBar).toContain("t('header.exportThreadData')");
    expect(pane).toContain("emit('exportThreadData', id)");

    const sidebar = source('../src/components/SessionRow.vue');
    expect(sidebar).not.toContain('exportThreadData');
  });

  it('labels the data scope without claiming subagent recursion', () => {
    const zhHeader = source('../src/i18n/locales/zh/header.ts');
    const enHeader = source('../src/i18n/locales/en/header.ts');
    const zhFocus = source('../src/i18n/locales/zh/focus.ts');
    const enFocus = source('../src/i18n/locales/en/focus.ts');

    expect(zhHeader).toContain("exportThreadData: '导出当前线程数据'");
    expect(enHeader).toContain("exportThreadData: 'Export current thread data'");
    expect(zhFocus).toContain('包含 app-server 保存的工具调用与结果');
    expect(zhFocus).toContain('不递归包含子代理线程');
    expect(enFocus).toContain('including tool calls and results stored by app-server');
    expect(enFocus).toContain('Subagent threads are not included recursively');
  });
});
