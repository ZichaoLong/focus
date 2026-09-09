import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

describe('Focus managed-instance inventory surface', () => {
  it('shows an explicit unknown loaded state in wide and narrow layouts', () => {
    const wideRow = source('../src/components/SessionRow.vue');
    const narrowSwitcher = source('../src/components/narrow/NarrowSwitcherSheet.vue');
    const en = source('../src/i18n/locales/en/focus.ts');
    const zh = source('../src/i18n/locales/zh/focus.ts');

    expect(wideRow).toContain("runtimeState === 'unknown'");
    expect(wideRow).toContain("t('focus.loadedStateUnknown')");
    expect(narrowSwitcher).toContain("runtimeState === 'unknown'");
    expect(narrowSwitcher).toContain("t('focus.loadedStateUnknown')");
    expect(en).toContain("loadedStateUnknown: 'Loaded state unknown'");
    expect(zh).toContain("loadedStateUnknown: '加载状态未知'");
  });
});
