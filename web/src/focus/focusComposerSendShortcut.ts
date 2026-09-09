import { readonly, ref, type Ref } from 'vue';
import {
  DEFAULT_COMPOSER_SEND_SHORTCUT,
  isComposerSendShortcut,
  type ComposerSendShortcut,
} from '../components/chat/composerSendShortcut';
import {
  safeGetString,
  safeRemove,
  safeSetString,
  STORAGE_KEYS,
} from '../lib/storage';

export interface FocusComposerSendShortcutPreference {
  readonly shortcut: Readonly<Ref<ComposerSendShortcut>>;
  setShortcut(value: unknown): boolean;
}

/** Own one browser's local Composer keyboard-submit preference. */
export function createFocusComposerSendShortcutPreference(): FocusComposerSendShortcutPreference {
  const stored = safeGetString(STORAGE_KEYS.composerSendShortcut);
  const shortcut = ref<ComposerSendShortcut>(
    isComposerSendShortcut(stored) ? stored : DEFAULT_COMPOSER_SEND_SHORTCUT,
  );

  function setShortcut(value: unknown): boolean {
    if (!isComposerSendShortcut(value) || shortcut.value === value) return false;
    shortcut.value = value;
    if (value === DEFAULT_COMPOSER_SEND_SHORTCUT) {
      safeRemove(STORAGE_KEYS.composerSendShortcut);
    } else {
      safeSetString(STORAGE_KEYS.composerSendShortcut, value);
    }
    return true;
  }

  return {
    shortcut: readonly(shortcut),
    setShortcut,
  };
}
