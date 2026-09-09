import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  composerEnterKeyHint,
  composerKeyRequestsSubmit,
  DEFAULT_COMPOSER_SEND_SHORTCUT,
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
    expect(composer).toContain(':enterkeyhint="enterKeyHint"');
    expect(composer).toContain('@click="handleSubmit()"');
    expect(dialog.match(/<option value="(?:enter|modifier-enter|button-only)">/gu)).toHaveLength(3);
  });
});
