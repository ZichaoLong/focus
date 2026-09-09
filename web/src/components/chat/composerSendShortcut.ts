export const COMPOSER_SEND_SHORTCUTS = [
  'enter',
  'modifier-enter',
  'button-only',
] as const;

export type ComposerSendShortcut = typeof COMPOSER_SEND_SHORTCUTS[number];

export const DEFAULT_COMPOSER_SEND_SHORTCUT: ComposerSendShortcut = 'enter';

interface ComposerKeyEvent {
  readonly key: string;
  readonly altKey: boolean;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly shiftKey: boolean;
}

export function isComposerSendShortcut(value: unknown): value is ComposerSendShortcut {
  return typeof value === 'string'
    && COMPOSER_SEND_SHORTCUTS.some((shortcut) => shortcut === value);
}

/** Whether this exact key chord is the browser-local keyboard submit gesture. */
export function composerKeyRequestsSubmit(
  event: ComposerKeyEvent,
  shortcut: ComposerSendShortcut,
): boolean {
  if (event.key !== 'Enter' || event.altKey || event.shiftKey) return false;
  if (shortcut === 'button-only') return false;
  if (shortcut === 'enter') return !event.ctrlKey && !event.metaKey;
  return event.ctrlKey !== event.metaKey;
}

export function composerEnterKeyHint(shortcut: ComposerSendShortcut): 'enter' | 'send' {
  return shortcut === 'enter' ? 'send' : 'enter';
}
