import type { MarkdownIt } from 'markstream-vue';
import { configureFocusMarkdownMath } from './markdownMath';

const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
const PUNCTUATION = /\p{P}/u;
const LETTER_OR_NUMBER = /[\p{L}\p{N}]/u;
// Punctuation in CJK, vertical-form and full/halfwidth Unicode blocks.
const CJK_PUNCTUATION = /[\u3000-\u303f\ufe10-\ufe1f\ufe30-\ufe4f\uff00-\uff65]/u;

interface InlineState {
  src: string;
  pos: number;
  posMax: number;
  tokens: unknown[];
  delimiters: Array<{
    marker: number;
    length: number;
    token: number;
    end: number;
    open: boolean;
    close: boolean;
  }>;
  scanDelims(start: number, canSplitWord: boolean): {
    length: number;
    can_open: boolean;
    can_close: boolean;
  };
  push(type: string, tag: string, nesting: number): { content: string };
}

function characterBeside(state: InlineState, position: number, direction: -1 | 1): string {
  // Two UTF-16 units include an adjacent supplementary-plane Han character.
  return direction === -1
    ? [...state.src.slice(Math.max(0, position - 2), position)].at(-1) ?? ''
    : [...state.src.slice(position, Math.min(position + 2, state.posMax))][0] ?? '';
}

function hasCjkPunctuationContext(state: InlineState, position: number, direction: -1 | 1): boolean {
  let character = characterBeside(state, position, direction);
  // Shared quotes and ASCII punctuation need adjacent CJK text on the inside.
  // Stop at a star run so another ** cannot lend its CJK context.
  while (PUNCTUATION.test(character) && character !== '*') {
    if (CJK_PUNCTUATION.test(character)) return true;
    position += direction * character.length;
    character = characterBeside(state, position, direction);
  }
  return CJK.test(character);
}

function cjkStrongDelimiter(state: InlineState, silent: boolean): boolean {
  if (silent || state.src[state.pos] !== '*') return false;
  const scanned = state.scanDelims(state.pos, true);
  if (scanned.length !== 2) return false;

  const before = characterBeside(state, state.pos, -1);
  const after = characterBeside(state, state.pos + 2, 1);
  const open = scanned.can_open || (PUNCTUATION.test(after)
    && (CJK.test(before) || (LETTER_OR_NUMBER.test(before)
      && hasCjkPunctuationContext(state, state.pos + 2, 1))));
  const close = scanned.can_close || (PUNCTUATION.test(before)
    && (CJK.test(after) || (LETTER_OR_NUMBER.test(after)
      && hasCjkPunctuationContext(state, state.pos, -1))));
  if (open === scanned.can_open && close === scanned.can_close) return false;

  // Only relax the boundary of ** next to CJK prose. The parser still owns
  // delimiter pairing, nesting, escapes, code and math; never rewrite source.
  for (let index = 0; index < 2; index += 1) {
    state.push('text', '', 0).content = '*';
    state.delimiters.push({
      marker: 42, length: 2, token: state.tokens.length - 1, end: -1, open, close,
    });
  }
  state.pos += 2;
  return true;
}

const configuredParsers = new WeakSet<object>();

/** Shared chat/print grammar; see the Focus Web Markdown rendering contract. */
export function configureFocusMarkdown(md: MarkdownIt): MarkdownIt {
  configureFocusMarkdownMath(md);
  if (!configuredParsers.has(md)) {
    md.inline.ruler.before('emphasis', 'focus_cjk_strong', cjkStrongDelimiter);
    configuredParsers.add(md);
  }
  return md;
}
