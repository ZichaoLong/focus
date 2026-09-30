import {
  getMarkdown,
  normalizeStandaloneBackslashT,
  setDefaultMathOptions,
  type MarkdownIt,
} from 'markstream-vue';

const INLINE_OPEN = '\\(';
const INLINE_CLOSE = '\\)';
const BRACKET_OPEN = '\\[';
const BRACKET_CLOSE = '\\]';
const DOLLAR_BLOCK = '$$';
const BLOCK_RULE_ALT = ['paragraph', 'reference', 'blockquote', 'list'];
const LITERAL_TOKEN = 'focus_math_literal';
const LITERAL_CORE_RULE = 'focus_math_literal_restore';
// The parser's normalize core rule replaces source NULs with U+FFFD before
// block rules run. This length-preserving marker cannot collide with source.
const TABLE_MATH_PIPE = '\0';

interface InlineRuleState {
  src: string;
  pos: number;
  posMax: number;
  push(type: string, tag: string, nesting: number): MathRuleToken;
}

interface BlockRuleState {
  src: string;
  bMarks: number[];
  eMarks: number[];
  tShift: number[];
  sCount: number[];
  blkIndent: number;
  line: number;
  push(type: string, tag: string, nesting: number): MathRuleToken;
}

interface TableRuleState extends BlockRuleState {
  parentType: string;
  tokens: MathRuleToken[];
}

interface MathRuleToken {
  type?: string;
  content: string;
  markup: string;
  raw?: string;
  loading?: boolean;
  block?: boolean;
  map?: [number, number];
}

interface CoreRuleState {
  tokens?: Array<{
    type: string;
    children?: MathRuleToken[] | null;
  }>;
}

interface BlockDelimiter {
  open: typeof BRACKET_OPEN | typeof DOLLAR_BLOCK;
  close: typeof BRACKET_CLOSE | typeof DOLLAR_BLOCK;
}

// Markstream reads this global option while constructing its MarkdownIt
// instance. Configure it at module evaluation, before Markdown.vue mounts a
// renderer, then replace the dependency's still-too-broad rules below.
setDefaultMathOptions({ strictDelimiters: true });

function isEscaped(text: string, index: number): boolean {
  let backslashes = 0;
  for (let cursor = index - 1; cursor >= 0 && text[cursor] === '\\'; cursor -= 1) {
    backslashes += 1;
  }
  return backslashes % 2 === 1;
}

function findUnescapedDelimiter(
  text: string,
  delimiter: string,
  start: number,
  end = text.length,
): number {
  let cursor = text.indexOf(delimiter, start);
  while (cursor >= 0 && cursor + delimiter.length <= end) {
    const adjacentDollar = delimiter === DOLLAR_BLOCK
      && (text[cursor - 1] === '$' || text[cursor + delimiter.length] === '$');
    if (!adjacentDollar && !isEscaped(text, cursor)) return cursor;
    cursor = text.indexOf(delimiter, cursor + 1);
  }
  return -1;
}

function pushLiteralDelimiter(state: InlineRuleState, length: number, silent: boolean): boolean {
  const raw = state.src.slice(state.pos, state.pos + length);
  if (!silent) {
    // markdown-it-ts' text_join core rule converts text_special to text and
    // merges it into its neighbours. Markstream then decodes Markdown escapes
    // from the parent inline source a second time, which would drop the
    // backslash from an unsupported or unclosed Focus delimiter. Keep a
    // private barrier token through text_join; the core rule below restores
    // text_special only after merging is finished.
    const token = state.push(LITERAL_TOKEN, '', 0);
    token.content = raw;
    token.markup = raw;
  }
  state.pos += length;
  return true;
}

function inlineMathEnd(src: string, pos: number, end = src.length): number {
  if (!src.startsWith(INLINE_OPEN, pos) || isEscaped(src, pos)) return -1;
  const newline = src.indexOf('\n', pos + INLINE_OPEN.length);
  const lineEnd = newline < 0 ? end : Math.min(newline, end);
  const close = findUnescapedDelimiter(src, INLINE_CLOSE, pos + INLINE_OPEN.length, lineEnd);
  if (close < 0) return -1;
  const content = src.slice(pos + INLINE_OPEN.length, close);
  // Code spans take precedence; empty delimiters remain visible source.
  return content.trim() && !content.includes('`') ? close + INLINE_CLOSE.length : -1;
}

function focusInlineMathRule(state: InlineRuleState, silent: boolean): boolean {
  const { src, pos } = state;
  if (src[pos] === '$') {
    let end = pos + 1;
    while (src[end] === '$') end += 1;
    return pushLiteralDelimiter(state, end - pos, silent);
  }
  const marker = src.slice(pos, pos + 2);
  if (
    marker !== INLINE_OPEN
    && marker !== INLINE_CLOSE
    && marker !== BRACKET_OPEN
    && marker !== BRACKET_CLOSE
  ) return false;
  if (isEscaped(src, pos)) return false;

  // Bracket math is block-only. Owning its literal fallback here prevents
  // CommonMark's escape rule from silently dropping the backslashes in prose
  // or in an unclosed block candidate. The same applies to stray closers.
  if (marker !== INLINE_OPEN) return pushLiteralDelimiter(state, marker.length, silent);

  const end = inlineMathEnd(src, pos, state.posMax);
  if (end < 0) return pushLiteralDelimiter(state, INLINE_OPEN.length, silent);
  const content = src.slice(pos + INLINE_OPEN.length, end - INLINE_CLOSE.length);
  if (!silent) {
    const token = state.push('math_inline', 'math', 0);
    token.content = normalizeStandaloneBackslashT(content);
    token.markup = `${INLINE_OPEN}${INLINE_CLOSE}`;
    token.raw = src.slice(pos, end);
    token.loading = false;
  }
  state.pos = end;
  return true;
}

function protectTableMathPipes(line: string): string {
  if (!line.includes(INLINE_OPEN) || !line.includes('|')) return line;
  const pieces: string[] = [];
  let copied = 0;
  for (let pos = 0; pos < line.length;) {
    if (line[pos] === '`') {
      const open = pos;
      while (line[pos] === '`') pos += 1;
      const length = pos - open;
      // A matching backtick run owns all of its contents. An unmatched run is
      // ordinary text and must not suppress a later, valid formula.
      const runs = /`+/g;
      runs.lastIndex = pos;
      let match: RegExpExecArray | null;
      while ((match = runs.exec(line))) {
        if (match[0].length === length) {
          pos = runs.lastIndex;
          break;
        }
      }
    } else if (line[pos] === '\\') {
      const end = inlineMathEnd(line, pos);
      if (end >= 0) {
        pieces.push(line.slice(copied, pos), line.slice(pos, end).replaceAll('|', TABLE_MATH_PIPE));
        copied = end;
        pos = end;
      } else {
        // Escapes, including escaped openers and backticks, retain precedence.
        pos += 2;
      }
    } else {
      pos += 1;
    }
  }
  return pieces.length ? pieces.join('') + line.slice(copied) : line;
}

function configureMathTables(md: MarkdownIt): void {
  // Capture the enabled table rule through the public ruler API, without
  // depending on a bundled function name or a private rule array. Preserve
  // disabled tables and the stock rule's container/termination/alignment logic.
  const enabledRules = md.block.ruler.getRules('');
  md.block.ruler.disable('table');
  const otherRules = new Set(md.block.ruler.getRules(''));
  const table = enabledRules.find(rule => !otherRules.has(rule));
  if (!table) return;
  md.block.ruler.enable('table');
  md.block.ruler.at('table', (state: TableRuleState, start: number, end: number, silent: boolean) => {
    if (start + 1 >= end || !/^[:| \t-]+$/.test(logicalBlockLine(state, start + 1))
      || !state.src.includes(INLINE_OPEN)) {
      return table(state, start, end, silent);
    }
    const source = state.src;
    const firstToken = state.tokens.length;
    const parent = state.parentType;
    const pieces: string[] = [];
    let copied = 0;
    function protectLine(line: number): string {
      const from = state.bMarks[line]! + state.tShift[line]!;
      const to = state.eMarks[line]!;
      const original = source.slice(from, to);
      const protectedLine = protectTableMathPipes(original);
      if (protectedLine !== original) {
        pieces.push(source.slice(copied, from), protectedLine);
        copied = to;
      }
      return protectedLine;
    }
    try {
      // A table still needs an actual column separator in its header. Cached
      // line flags can otherwise mistake a protected math pipe for one.
      if (!protectLine(start).includes('|')) return false;
      state.src = pieces.join('') + source.slice(copied);
      if (!table(state, start, end, true)) return false;
      if (silent) return true;

      state.parentType = 'table';
      const terminators = md.block.ruler.getRules('blockquote');
      for (let line = start + 2; line < end; line += 1) {
        if ((state.sCount[line] ?? 0) < state.blkIndent
          || (state.sCount[line] ?? 0) - state.blkIndent >= 4
          || !logicalBlockLine(state, line).trim()
          || terminators.some(rule => rule(state, line, end, true))) break;
        protectLine(line);
      }
      state.parentType = parent;
      state.src = pieces.join('') + source.slice(copied);
      return table(state, start, end, false);
    } finally {
      state.src = source;
      state.parentType = parent;
      // Restore before the inline pass so parsing, fallback and copy all see
      // the original LaTeX, including escaped pipes such as \| and \left\|.
      for (let index = firstToken; index < state.tokens.length; index += 1) {
        const token = state.tokens[index]!;
        if (token.type === 'inline') token.content = token.content.replaceAll(TABLE_MATH_PIPE, '|');
      }
    }
  });
}

function logicalBlockLine(state: BlockRuleState, line: number): string {
  const start = state.bMarks[line]! + state.tShift[line]!;
  return state.src.slice(start, state.eMarks[line]);
}

function remainsInBlockContainer(state: BlockRuleState, line: number, content: string): boolean {
  // Empty lines may remain inside a loose list without carrying its indent.
  // A non-empty lazy continuation below blkIndent, however, belongs outside
  // the current blockquote/list container and cannot close or extend math.
  return !content.trim() || (state.sCount[line] ?? 0) >= state.blkIndent;
}

function blockDelimiter(line: string): BlockDelimiter | null {
  if (line.startsWith('$$$')) return null;
  if (line.startsWith(DOLLAR_BLOCK)) {
    return { open: DOLLAR_BLOCK, close: DOLLAR_BLOCK };
  }
  if (line.startsWith(BRACKET_OPEN)) {
    return { open: BRACKET_OPEN, close: BRACKET_CLOSE };
  }
  return null;
}

function focusMathBlockRule(
  state: BlockRuleState,
  startLine: number,
  endLine: number,
  silent: boolean,
): boolean {
  if ((state.sCount[startLine] ?? 0) - state.blkIndent >= 4) return false;
  const firstLine = logicalBlockLine(state, startLine);
  const delimiter = blockDelimiter(firstLine);
  if (!delimiter) return false;
  // A delimiter-looking line still terminates an existing paragraph or lazy
  // blockquote continuation, even when the full candidate later proves empty,
  // unclosed, or outside its container. This matches Markdown block-rule
  // silent semantics without admitting an invalid math token.
  if (silent) return true;

  const contentLines: string[] = [];
  for (let line = startLine; line < endLine; line += 1) {
    const current = line === startLine ? firstLine.slice(delimiter.open.length) : logicalBlockLine(state, line);
    if (line > startLine && !remainsInBlockContainer(state, line, current)) return false;
    const close = findUnescapedDelimiter(current, delimiter.close, 0);
    if (close >= 0) {
      if (current.slice(close + delimiter.close.length).trim()) return false;
      contentLines.push(current.slice(0, close));
      const content = contentLines.join('\n');
      if (!content.trim()) return false;
      const token = state.push('math_block', 'math', 0);
      token.content = normalizeStandaloneBackslashT(content);
      token.markup = delimiter.open === DOLLAR_BLOCK ? DOLLAR_BLOCK : `${BRACKET_OPEN}${BRACKET_CLOSE}`;
      token.raw = `${delimiter.open}${content}${delimiter.close}`;
      token.map = [startLine, line + 1];
      token.block = true;
      token.loading = false;
      state.line = line + 1;
      return true;
    }
    contentLines.push(current);
  }
  return false;
}

function restoreFocusLiteralTokens(state: CoreRuleState): void {
  for (const blockToken of state.tokens ?? []) {
    if (blockToken.type !== 'inline') continue;
    for (const token of blockToken.children ?? []) {
      if (token.type === LITERAL_TOKEN) token.type = 'text_special';
    }
  }
}

const configuredParsers = new WeakSet<object>();

/** Install Focus's exact math grammar over markstream's heuristic rules. */
export function configureFocusMarkdownMath(md: MarkdownIt): MarkdownIt {
  if (configuredParsers.has(md)) return md;
  md.inline.ruler.at('math', focusInlineMathRule);
  md.block.ruler.at('explicit_math_block', focusMathBlockRule, { alt: BLOCK_RULE_ALT });
  md.block.ruler.at('math_block', focusMathBlockRule, { alt: BLOCK_RULE_ALT });
  configureMathTables(md);
  md.core.ruler.after('text_join', LITERAL_CORE_RULE, restoreFocusLiteralTokens);
  configuredParsers.add(md);
  return md;
}

interface DetectionToken {
  type?: string;
  children?: DetectionToken[] | null;
}

let detectionParser: MarkdownIt | null = null;

function focusMathDetectionParser(): MarkdownIt {
  if (!detectionParser) {
    detectionParser = configureFocusMarkdownMath(getMarkdown('focus-math-syntax-detector'));
  }
  return detectionParser;
}

function tokensContainMath(tokens: DetectionToken[]): boolean {
  return tokens.some((token) => (
    token.type === 'math_inline'
    || token.type === 'math_block'
    || tokensContainMath(token.children ?? [])
  ));
}

/** Detect only closed syntax accepted by configureFocusMarkdownMath. */
export function containsFocusMarkdownMath(source: string): boolean {
  const text = String(source ?? '');
  if (!text.includes(INLINE_OPEN) && !text.includes(BRACKET_OPEN) && !text.includes(DOLLAR_BLOCK)) {
    return false;
  }
  try {
    const parsed = focusMathDetectionParser().parse(text, { __markstreamFinal: true });
    return tokensContainMath(parsed as DetectionToken[]);
  } catch {
    // Detection never owns rendering. If its parser fails, leave the optional
    // runtime disabled so the independent renderer can retain source fallback.
    return false;
  }
}
