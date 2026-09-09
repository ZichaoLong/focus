import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  composerEnterKeyHint,
  composerKeyRequestsSubmit,
  DEFAULT_COMPOSER_SEND_SHORTCUT,
  insertComposerNewline,
  type ComposerSendShortcut,
} from '../src/components/chat/composerSendShortcut';
import { createFocusComposerSendShortcutPreference } from '../src/focus/focusComposerSendShortcut';
import { STORAGE_KEYS } from '../src/lib/storage';

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, String(value)); },
  };
}

function enterKey(overrides: Partial<KeyboardEvent> = {}): KeyboardEvent {
  return {
    key: 'Enter',
    altKey: false,
    ctrlKey: false,
    metaKey: false,
    shiftKey: false,
    ...overrides,
  } as KeyboardEvent;
}

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

function textareaEditTarget(value: string, start: number | null, end: number | null) {
  return {
    value,
    selectionStart: start,
    selectionEnd: end,
    setRangeText(replacement: string, rangeStart: number, rangeEnd: number, mode?: SelectionMode) {
      this.value = this.value.slice(0, rangeStart) + replacement + this.value.slice(rangeEnd);
      if (mode === 'end') {
        this.selectionStart = rangeStart + replacement.length;
        this.selectionEnd = this.selectionStart;
      }
    },
  };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('Focus Composer send shortcut', () => {
  it('recognizes only the exact configured keyboard submit chord', () => {
    expect(composerKeyRequestsSubmit(enterKey(), 'enter')).toBe(true);
    expect(composerKeyRequestsSubmit(enterKey({ ctrlKey: true }), 'enter')).toBe(false);
    expect(composerKeyRequestsSubmit(enterKey({ metaKey: true }), 'enter')).toBe(false);

    expect(composerKeyRequestsSubmit(enterKey({ ctrlKey: true }), 'modifier-enter')).toBe(true);
    expect(composerKeyRequestsSubmit(enterKey({ metaKey: true }), 'modifier-enter')).toBe(true);
    expect(composerKeyRequestsSubmit(
      enterKey({ ctrlKey: true, metaKey: true }),
      'modifier-enter',
    )).toBe(false);
    expect(composerKeyRequestsSubmit(enterKey(), 'modifier-enter')).toBe(false);

    const shortcuts: ComposerSendShortcut[] = ['enter', 'modifier-enter', 'button-only'];
    for (const shortcut of shortcuts) {
      expect(composerKeyRequestsSubmit(enterKey({ shiftKey: true }), shortcut)).toBe(false);
      expect(composerKeyRequestsSubmit(enterKey({ altKey: true }), shortcut)).toBe(false);
      expect(composerKeyRequestsSubmit(enterKey({ key: 'Tab' }), shortcut)).toBe(false);
    }
    expect(composerKeyRequestsSubmit(enterKey(), 'button-only')).toBe(false);
    expect(composerKeyRequestsSubmit(
      enterKey({ ctrlKey: true }),
      'button-only',
    )).toBe(false);
  });

  it('uses a send hint only when an unmodified Enter submits', () => {
    expect(composerEnterKeyHint('enter')).toBe('send');
    expect(composerEnterKeyHint('modifier-enter')).toBe('enter');
    expect(composerEnterKeyHint('button-only')).toBe('enter');
  });

  it('explicitly inserts modified unmatched Enter chords at the current selection', () => {
    const selected = textareaEditTarget('alpha beta', 5, 6);
    expect(insertComposerNewline(selected)).toBe('alpha\nbeta');
    expect(selected.selectionStart).toBe(6);
    expect(selected.selectionEnd).toBe(6);

    const noSelection = textareaEditTarget('draft', null, null);
    expect(insertComposerNewline(noSelection)).toBe('draft\n');
    expect(noSelection.selectionStart).toBe(6);
    expect(noSelection.selectionEnd).toBe(6);

    const explicitlyInsertedChords: Array<[ComposerSendShortcut, Partial<KeyboardEvent>]> = [
      ['enter', { altKey: true }],
      ['enter', { ctrlKey: true }],
      ['enter', { metaKey: true }],
      ['modifier-enter', { ctrlKey: true, shiftKey: true }],
      ['modifier-enter', { altKey: true }],
      ['button-only', { ctrlKey: true }],
      ['button-only', { metaKey: true }],
    ];
    for (const [shortcut, overrides] of explicitlyInsertedChords) {
      const event = enterKey(overrides);
      expect(composerKeyRequestsSubmit(event, shortcut)).toBe(false);
      expect(insertComposerNewline(textareaEditTarget('x', 1, 1))).toBe('x\n');
    }
  });

  it('prefers the browser insertText path that participates in native undo', () => {
    const target = textareaEditTarget('undo me', 4, 5);
    const execCommand = vi.fn((commandId: string, _showUi: boolean, value: string) => {
      expect(commandId).toBe('insertText');
      target.setRangeText(value, target.selectionStart ?? 0, target.selectionEnd ?? 0, 'end');
      return true;
    });
    Object.assign(target, { ownerDocument: { execCommand } });

    expect(insertComposerNewline(target)).toBe('undo\nme');
    expect(execCommand).toHaveBeenCalledWith('insertText', false, '\n');
  });

  it('strictly restores and persists one browser-local preference', () => {
    expect(DEFAULT_COMPOSER_SEND_SHORTCUT).toBe('enter');
    expect(createFocusComposerSendShortcutPreference().shortcut.value).toBe('enter');

    localStorage.setItem(STORAGE_KEYS.composerSendShortcut, 'unexpected');
    expect(createFocusComposerSendShortcutPreference().shortcut.value).toBe('enter');

    localStorage.setItem(STORAGE_KEYS.composerSendShortcut, 'button-only');
    const preference = createFocusComposerSendShortcutPreference();
    expect(preference.shortcut.value).toBe('button-only');
    expect(preference.setShortcut('unexpected')).toBe(false);
    expect(preference.shortcut.value).toBe('button-only');
    expect(preference.setShortcut('modifier-enter')).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.composerSendShortcut)).toBe('modifier-enter');
    expect(preference.setShortcut('modifier-enter')).toBe(false);
    expect(preference.setShortcut('enter')).toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.composerSendShortcut)).toBeNull();
  });

  it('wires the preference through both Composer sites and the settings dialog', () => {
    const app = source('../src/focus/FocusApp.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');
    const dock = source('../src/components/chat/ChatDock.vue');
    const composer = source('../src/components/chat/Composer.vue');
    const dialog = source('../src/focus/FocusSettingsDialog.vue');

    expect(app).toContain('createFocusComposerSendShortcutPreference()');
    expect(app.match(
      /:composer-send-shortcut="composerSendShortcutPreference\.shortcut\.value"/gu,
    )).toHaveLength(2);
    expect(app).toContain(
      '@set-composer-send-shortcut="composerSendShortcutPreference.setShortcut($event)"',
    );
    expect(pane.match(/:send-shortcut="composerSendShortcut"/gu)).toHaveLength(2);
    expect(dock).toContain(':send-shortcut="sendShortcut"');
    expect(composer).toContain('composerKeyRequestsSubmit(e, props.sendShortcut)');
    expect(composer).toContain('if (!e.altKey && !e.ctrlKey && !e.metaKey) return;');
    expect(composer).toContain('text.value = insertComposerNewline(target)');
    expect(composer).toContain('if (!inputEventHandled) handleInput();');
    expect(composer).toContain(':enterkeyhint="enterKeyHint"');
    expect(composer).toContain('@click="handleSubmit()"');
    expect(dialog.match(/<option value="(?:enter|modifier-enter|button-only)">/gu)).toHaveLength(3);
  });
});
