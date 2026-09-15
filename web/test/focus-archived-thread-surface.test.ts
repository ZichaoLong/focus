import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';


function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}


describe('Focus archived-thread settings surface', () => {
  it('shows the full selectable thread id and reflows against the dialog container', () => {
    const dialog = source('../src/focus/FocusSettingsDialog.vue');

    expect(dialog).toContain('<code class="archived-thread-id">{{ thread.id }}</code>');
    expect(dialog).toContain('.archived-panel { container-type: inline-size; }');
    expect(dialog).toContain('@container (max-width: 480px)');
    expect(dialog).toMatch(/\.archived-thread-id \{[\s\S]*?overflow-wrap: anywhere;[\s\S]*?white-space: normal;[\s\S]*?user-select: text;/u);
    expect(dialog).toMatch(/@container \(max-width: 480px\) \{[\s\S]*?\.archived-row \{[\s\S]*?flex-direction: column;/u);
  });

  it('keeps exact-id typing as the only permanent-delete confirmation aid', () => {
    const dialog = source('../src/focus/FocusSettingsDialog.vue');

    expect(dialog).toContain('deleteConfirmation.value.trim() !== deleteTarget.value');
    expect(dialog).toContain(':disabled="deleteConfirmation.trim() !== thread.id"');
    expect(dialog).not.toContain('copyTextToClipboard');
  });
});
