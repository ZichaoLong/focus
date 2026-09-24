import type { MarkdownIt } from 'markstream-vue';
import { configureFocusMarkdownMath } from './markdownMath';

const CJK = /[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u;
const PUNCTUATION = /\p{P}/u;

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

function cjkStrongDelimiter(state: InlineState, silent: boolean): boolean {
  if (silent || state.src[state.pos] !== '*') return false;
  const scanned = state.scanDelims(state.pos, true);
  if (scanned.length !== 2) return false;

  // Two UTF-16 units include an adjacent supplementary-plane Han character.
  const before = [...state.src.slice(Math.max(0, state.pos - 2), state.pos)].at(-1) ?? '';
  const after = [...state.src.slice(state.pos + 2, Math.min(state.pos + 4, state.posMax))][0] ?? '';
  const open = scanned.can_open || (CJK.test(before) && PUNCTUATION.test(after));
  const close = scanned.can_close || (PUNCTUATION.test(before) && CJK.test(after));
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
