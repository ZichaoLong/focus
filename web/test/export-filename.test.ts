import { describe, expect, it } from 'vitest';
import { normalizeExportFilename, suggestExportFilename } from '../src/focus/exportFilename';

describe('portable export filenames', () => {
  it('preserves readable Unicode and supplies exactly one matching extension', () => {
    expect(normalizeExportFilename('  会话复盘 📝  ', 'markdown')).toBe('会话复盘 📝.md');
    expect(normalizeExportFilename('notes.MD.md', 'markdown')).toBe('notes.md');
    expect(normalizeExportFilename('notes.txt', 'markdown')).toBe('notes.txt.md');
    expect(normalizeExportFilename('记录.JSONL', 'jsonl')).toBe('记录.jsonl');
    expect(suggestExportFilename('会话', 'print')).toBe('会话.pdf');
  });

  it('removes path syntax, controls, directional overrides and trailing dots', () => {
    expect(normalizeExportFilename('../a\\b:c*?"<>|\u0000\u202e . ', 'markdown')).toBe('-a-b-c--------.md');
    expect(normalizeExportFilename('e\u0301', 'markdown')).toBe('é.md');
  });

  it.each(['CON', 'nul.txt', 'LPT1', 'COM²'])('avoids the Windows device name %s', (name) => {
    expect(normalizeExportFilename(name, 'jsonl')).toBe(`_${name}.jsonl`);
  });

  it.each(['', '   ', '..', '.md', '.md.MD'])('requires a nonempty base name: %s', (name) => {
    expect(normalizeExportFilename(name, 'markdown')).toBe('');
    expect(suggestExportFilename(name, 'markdown')).toBe('codex-conversation-summary.md');
  });

  it('uses stable format-specific fallbacks without a title', () => {
    expect(suggestExportFilename('', 'jsonl')).toBe('codex-thread-data.jsonl');
    expect(suggestExportFilename('', 'print')).toBe('codex-conversation-summary.pdf');
  });

  it.each(['a'.repeat(400), '中文📝'.repeat(100), `${'a'.repeat(194)}.md.extra`])('bounds long names without splitting Unicode or losing the extension', (title) => {
    const name = normalizeExportFilename(title, 'markdown');
    expect(new TextEncoder().encode(name).length).toBeLessThanOrEqual(200);
    expect(name).toMatch(/\.md$/);
    expect(name).not.toContain('\ufffd');
    expect(normalizeExportFilename(name, 'markdown')).toBe(name);
  });
});
