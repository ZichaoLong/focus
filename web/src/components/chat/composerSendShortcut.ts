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

interface ComposerTextareaEditTarget {
  value: string;
  selectionStart: number | null;
  selectionEnd: number | null;
  readonly ownerDocument?: {
    execCommand?: (commandId: string, showUi: boolean, value: string) => boolean;
  };
  setRangeText(
    replacement: string,
    start: number,
    end: number,
    selectionMode?: SelectionMode,
  ): void;
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

/**
 * Insert the newline promised for every unmatched Enter chord.
 *
 * Browsers do not consistently give modified Enter chords a native textarea
 * edit (notably Alt+Enter and Ctrl/Command+Enter), so the Composer cannot
 * delegate those chords to the user agent. The long-supported `insertText`
 * command keeps the edit in browser undo history where available. The
 * selection-safe `setRangeText` fallback still guarantees the newline on a
 * browser that omits or rejects that legacy command.
 */
export function insertComposerNewline(target: ComposerTextareaEditTarget): string {
  const execCommand = target.ownerDocument?.execCommand;
  if (typeof execCommand === 'function') {
    const before = target.value;
    try {
      const handled = execCommand.call(target.ownerDocument, 'insertText', false, '\n');
      if (handled || target.value !== before) return target.value;
    } catch {
      // Fall through to the deterministic selection edit below.
    }
  }

  const start = target.selectionStart ?? target.value.length;
  const end = target.selectionEnd ?? start;
  target.setRangeText('\n', Math.min(start, end), Math.max(start, end), 'end');
  return target.value;
}

export function composerEnterKeyHint(shortcut: ComposerSendShortcut): 'enter' | 'send' {
  return shortcut === 'enter' ? 'send' : 'enter';
}
