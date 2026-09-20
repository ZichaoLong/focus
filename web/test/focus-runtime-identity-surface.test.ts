import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import enFocus from '../src/i18n/locales/en/focus';
import zhFocus from '../src/i18n/locales/zh/focus';


function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}


describe('Focus runtime identity settings surface', () => {
  it('shows installed Focus and current app-server identities in About', () => {
    const dialog = source('../src/focus/FocusSettingsDialog.vue');
    const app = source('../src/focus/FocusApp.vue');

    expect(dialog).toContain("'preferences' | 'archived' | 'about' | 'danger'");
    expect(dialog).toContain("value: 'about', label: t('focus.about')");
    expect(dialog).not.toContain("value: 'update', label: t('focus.update')");
    expect(dialog).toContain('runtimeIdentity.installed_build.channel');
    expect(dialog).toContain('runtimeIdentity.installed_build.build_id');
    expect(dialog).toContain('runtimeIdentity.installed_build.source_revision');
    expect(dialog).toContain('runtimeIdentity.codex_app_server.user_agent');
    expect(dialog).toContain("section === 'about'");
    expect(dialog).toContain("t('focus.updateTitle')");
    expect(app).toContain(':runtime-identity="client.meta.value?.runtime_identity ?? null"');
  });

  it('keeps complete diagnostic identifiers wrapped and manually selectable', () => {
    const dialog = source('../src/focus/FocusSettingsDialog.vue');

    expect(dialog).toMatch(/\.runtime-identity-value \{[\s\S]*?overflow-wrap: anywhere;[\s\S]*?white-space: normal;[\s\S]*?user-select: text;/u);
    expect(dialog).toMatch(/\.settings-sections :deep\(\.ui-seg__item\) \{[\s\S]*?min-width: 0;[\s\S]*?flex: 1;[\s\S]*?white-space: normal;/u);
    expect(dialog).toMatch(/\.about-panel \{[\s\S]*?overflow-y: auto;[\s\S]*?scrollbar-gutter: stable;/u);
  });

  it('keeps the About copy complete and symmetric', () => {
    const keys = [
      'about',
      'aboutDescription',
      'focusVersion',
      'focusInstalledBuild',
      'focusSourceRevision',
      'focusInstallIdentityUnavailable',
      'codexHandshakeIdentity',
      'codexIdentityUnavailable',
    ] as const;
    for (const key of keys) {
      expect(enFocus[key]).toBeTruthy();
      expect(zhFocus[key]).toBeTruthy();
    }
  });
});
