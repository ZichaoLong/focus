import { renderToString } from '@vue/server-renderer';
import { createSSRApp, h } from 'vue';
import { createI18n } from 'vue-i18n';
import { describe, expect, it } from 'vitest';
import {
  getMarkdown,
  parseMarkdownToStructure,
  type MarkdownIt,
} from 'markstream-vue';
import Markdown from '../src/components/chat/Markdown.vue';
import {
  configureFocusMarkdownMath,
  containsFocusMarkdownMath,
} from '../src/lib/markdownMath';

interface TokenShape {
  type: string;
  content?: string;
  markup?: string;
  raw?: string;
  children?: TokenShape[] | null;
}

let parserId = 0;

function parser(): MarkdownIt {
  parserId += 1;
  return configureFocusMarkdownMath(getMarkdown(`focus-math-contract-${parserId}`));
}

function tokens(source: string): TokenShape[] {
  return parser().parse(source, { __markstreamFinal: true }) as TokenShape[];
}

function flatten(sourceTokens: TokenShape[]): TokenShape[] {
  return sourceTokens.flatMap((token) => [token, ...flatten(token.children ?? [])]);
}

function mathTokens(source: string): TokenShape[] {
  return flatten(tokens(source)).filter(
    (token) => token.type === 'math_inline' || token.type === 'math_block',
  );
}

function renderedText(source: string): string {
  const nodes = parseMarkdownToStructure(source, parser(), {
    final: true,
    streamParse: false,
  }) as TokenShape[];
  return flatten(nodes)
    .filter((node) => node.type === 'text')
    .map((node) => node.content ?? '')
    .join('');
}

function markdownApp(source: string) {
  const app = createSSRApp({
    render: () => h(Markdown, { text: source }),
  });
  app.use(createI18n({
    legacy: false,
    locale: 'en',
    messages: { en: {} },
  }));
  app.provide('resolveImage', undefined);
  return app;
}

describe('Focus Markdown math contract', () => {
  it('accepts only backslash-delimited inline math', () => {
    expect(mathTokens(String.raw`before \(x + y\) after`)).toMatchObject([{
      type: 'math_inline',
      content: 'x + y',
      markup: String.raw`\(\)`,
      raw: String.raw`\(x + y\)`,
    }]);
  });

  it('accepts single-line and multiline bracket and dollar blocks', () => {
    const cases = [
      String.raw`\[x + y\]`,
      [String.raw`\[`, 'x + y', String.raw`\]`].join('\n'),
      '$$x + y$$',
      ['$$', 'x + y', '$$'].join('\n'),
    ];
    for (const source of cases) {
      const parsed = mathTokens(source);
      expect(parsed).toHaveLength(1);
      expect(parsed[0]).toMatchObject({ type: 'math_block', raw: source });
    }
  });

  it('keeps every single-dollar form and prose-position double dollars literal', () => {
    const source = '$PATH ${HOME} $5 $x$ before $$x + y$$ after and a trailing $';
    expect(mathTokens(source)).toEqual([]);
    expect(renderedText(source)).toBe(source);
    expect(renderedText('$')).toBe('$');
  });

  it('keeps code, escaped delimiters, and unclosed delimiters literal', () => {
    expect(mathTokens(`code: ${'`'}${String.raw`\(x\)`}${'`'}`)).toEqual([]);
    expect(mathTokens(['```txt', '$$x$$', '```'].join('\n'))).toEqual([]);
    expect(mathTokens(String.raw`\\(x\\)`)).toEqual([]);
    expect(renderedText(String.raw`\\(x\\)`)).toBe(String.raw`\(x\)`);
    expect(renderedText(String.raw`\(unclosed`)).toBe(String.raw`\(unclosed`);
    expect(renderedText(String.raw`before \[x\] after`)).toBe(String.raw`before \[x\] after`);
    expect(renderedText(String.raw`\[unclosed`)).toBe(String.raw`\[unclosed`);
    expect(renderedText(String.raw`stray \) and \]`)).toBe(String.raw`stray \) and \]`);

    const code = parseMarkdownToStructure(
      String.raw`\(x ` + '`code`' + String.raw` y\)`,
      parser(),
      { final: true, streamParse: false },
    ) as TokenShape[];
    expect(flatten(code).filter((node) => node.type === 'text').map((node) => node.content)).toEqual([
      String.raw`\(x `,
      String.raw` y\)`,
    ]);
  });

  it('keeps nested block math while rejecting indented code', () => {
    expect(mathTokens('    $$indented$$')).toEqual([]);
    expect(mathTokens('> $$quoted$$')).toHaveLength(1);
    expect(mathTokens('- $$listed$$')).toHaveLength(1);
    expect(mathTokens(['> $$', '> quoted', 'outside', '$$'].join('\n'))).toEqual([]);
    expect(mathTokens(['- $$', '  listed', 'outside', '$$'].join('\n'))).toEqual([]);

    const quoteBoundary = parseMarkdownToStructure(
      ['> $$', '> quoted', 'outside', '$$'].join('\n'),
      parser(),
      { final: true, streamParse: false },
    ) as TokenShape[];
    expect(quoteBoundary.map((node) => node.type)).toEqual(['blockquote', 'paragraph']);
    expect(quoteBoundary[1]?.raw).toBe('$$');
  });

  it('uses the same exact grammar for lazy runtime detection', () => {
    expect(containsFocusMarkdownMath(String.raw`\(x\)`)).toBe(true);
    expect(containsFocusMarkdownMath(String.raw`\[x\]`)).toBe(true);
    expect(containsFocusMarkdownMath(['$$', 'x', '$$'].join('\n'))).toBe(true);
    expect(containsFocusMarkdownMath('$x$ before $$x$$ after')).toBe(false);
    expect(containsFocusMarkdownMath(String.raw`\\(x\\)`)).toBe(false);
    expect(containsFocusMarkdownMath(String.raw`\(unclosed`)).toBe(false);
    expect(containsFocusMarkdownMath(['```ts', String.raw`\(x\)`, '```'].join('\n'))).toBe(false);
    expect(containsFocusMarkdownMath('    $$indented$$')).toBe(false);
    expect(containsFocusMarkdownMath('> $$quoted$$')).toBe(true);
    expect(containsFocusMarkdownMath('- $$listed$$')).toBe(true);
    expect(containsFocusMarkdownMath(['> $$', '> quoted', 'outside', '$$'].join('\n'))).toBe(false);
    expect(containsFocusMarkdownMath(['- $$', '  listed', 'outside', '$$'].join('\n'))).toBe(false);
    expect(containsFocusMarkdownMath(['`open', String.raw`\(x\)`, 'close`'].join('\n'))).toBe(false);
  });

  it('keeps detector admission identical to parser admission for candidate syntax', () => {
    const cases = [
      String.raw`\(x\)`,
      String.raw`\(unclosed`,
      String.raw`\\(escaped\\)`,
      String.raw`before \[x\] after`,
      String.raw`\[x\]`,
      '$$x$$',
      'before $$x$$ after',
      '> $$quoted$$',
      '- $$listed$$',
      ['> $$', '> quoted', 'outside', '$$'].join('\n'),
      ['- $$', '  listed', 'outside', '$$'].join('\n'),
      '    $$indented$$',
      ['```sh', String.raw`\(x\)`, '```'].join('\n'),
      ['`open', String.raw`\(x\)`, 'close`'].join('\n'),
    ];
    for (const source of cases) {
      expect(containsFocusMarkdownMath(source), source).toBe(mathTokens(source).length > 0);
    }
  });

  it('preserves cardinality formulas and following cells in table headers and rows', () => {
    const source = [
      String.raw`| 层级 | 约束 \(|A|\) | 说明 |`,
      '| :--- | :---: | ---: |',
      String.raw`| Graph | \(|A|\le K_j\) | 容量上界 \(K_j=8\) |`,
      String.raw`| SettleGraph | \(|A|=\min(K_j,|C|)\) | 各阶段分别采用 8、4、2 |`,
    ].join('\n');
    const parsed = tokens(source);
    expect(parsed.filter(token => token.type === 'inline').map(token => token.content)).toEqual([
      '层级', String.raw`约束 \(|A|\)`, '说明',
      'Graph', String.raw`\(|A|\le K_j\)`, String.raw`容量上界 \(K_j=8\)`,
      'SettleGraph', String.raw`\(|A|=\min(K_j,|C|)\)`, '各阶段分别采用 8、4、2',
    ]);
    expect(mathTokens(source).map(token => token.content)).toEqual([
      '|A|', String.raw`|A|\le K_j`, 'K_j=8', String.raw`|A|=\min(K_j,|C|)`,
    ]);
    const [table] = parseMarkdownToStructure(source, parser(), { final: true, streamParse: false });
    expect(table).toMatchObject({
      type: 'table',
      header: { cells: [{ align: 'left' }, { align: 'center' }, { align: 'right' }] },
      rows: [
        { cells: [{ raw: 'Graph' }, { raw: String.raw`\(|A|\le K_j\)` }, { raw: String.raw`容量上界 \(K_j=8\)` }] },
        { cells: [{ raw: 'SettleGraph' }, { raw: String.raw`\(|A|=\min(K_j,|C|)\)` }, { raw: '各阶段分别采用 8、4、2' }] },
      ],
    });
    expect(containsFocusMarkdownMath(source)).toBe(true);
  });

  it('retains exact math escapes, whitespace, and multiple formulas beside ordinary escaped pipes', () => {
    const source = [
      'Formula | Notes',
      '--- | ---',
      String.raw`before \( \left\|x\right\| + \t y \) and \(a|b\) | literal a\|b`,
    ].join('\n');
    const parsed = tokens(source);
    expect(mathTokens(source)).toMatchObject([
      { raw: String.raw`\( \left\|x\right\| + \t y \)`, content: String.raw` \left\|x\right\| + \t y ` },
      { raw: String.raw`\(a|b\)`, content: 'a|b' },
    ]);
    expect(parsed.filter(token => token.type === 'inline').at(-1)?.content).toBe('literal a|b');
  });

  it('handles nested tables and stops at normal block boundaries', () => {
    const table = ['| Formula | Notes |', '| --- | --- |', String.raw`| \(|A|\) | kept |`];
    for (const source of [
      table.map(line => `> ${line}`).join('\n'),
      table.map((line, index) => `${index ? '  ' : '- '}${line}`).join('\n'),
      [...table, '# Heading', String.raw`\(x|y\) outside`].join('\n'),
      [...table, '```text', String.raw`\(code|text\)`, '```'].join('\n'),
    ]) {
      expect(tokens(source).filter(token => token.type === 'table_open')).toHaveLength(1);
      expect(mathTokens(source)[0]?.raw).toBe(String.raw`\(|A|\)`);
      expect(tokens(source).filter(token => token.type === 'inline').map(token => token.content)).toContain('kept');
    }
    expect(mathTokens(table.map(line => `    ${line}`).join('\n'))).toEqual([]);
    expect(mathTokens(['```text', ...table, '```'].join('\n'))).toEqual([]);
    expect(tokens(String.raw`\(|A|\)` + '\n---').some(token => token.type === 'table_open')).toBe(false);
  });

  it('keeps literal/unsupported table syntax and code-span precedence unchanged', () => {
    for (const value of [
      String.raw`\\(|escaped|\\)`,
      String.raw`\(|unclosed|`,
      String.raw`\[|block|\]`,
      '$|dollar|$',
      '$$|block|$$',
      '`' + String.raw`\(|code|\)` + '`',
      '``' + String.raw`\(|code` + '`with`' + String.raw`backticks|\)` + '``',
      String.raw`\(x ` + '`code|text`' + String.raw` y\)`,
    ]) {
      const source = ['| First | Second | Third |', '| --- | --- | --- |', `| ${value} | kept | last |`].join('\n');
      const md = parser();
      const standardTable = getMarkdown(`focus-table-baseline-${parserId++}`);
      const expected = standardTable.parse(source).filter(token => token.type === 'inline').map(token => token.content);
      expect(md.parse(source).filter(token => token.type === 'inline').map(token => token.content), value).toEqual(expected);
      expect(mathTokens(source), value).toEqual([]);
    }
    const source = ['| Formula | Notes |', '| --- | --- |', '`unclosed ' + String.raw`\(|A|\) | kept`].join('\n');
    expect(mathTokens(source)).toMatchObject([{ raw: String.raw`\(|A|\)` }]);
  });

  it('recognizes table math only once a streaming formula closes, including on parser reuse', () => {
    const md = parser();
    const prefix = '| Formula | Notes |\n| --- | --- |\n';
    for (const final of [false, true]) {
      const open = parseMarkdownToStructure(prefix + String.raw`| \(|A|`, md, { final });
      expect(JSON.stringify(open)).not.toContain('"type":"math_inline"');
      const complete = parseMarkdownToStructure(prefix + String.raw`| \(|A|\) | kept |`, md, { final });
      expect(complete[0]).toMatchObject({
        type: 'table', rows: [{ cells: [
          { children: [{ type: 'math_inline', raw: String.raw`\(|A|\)`, content: '|A|' }] },
          { raw: 'kept' },
        ] }],
      });
      expect(containsFocusMarkdownMath(prefix + String.raw`| \(|A|`)).toBe(false);
    }
    expect(md.parse(prefix + '| plain | kept |').filter(token => token.type === 'inline').map(token => token.content)).toEqual([
      'Formula', 'Notes', 'plain', 'kept',
    ]);
  });

  it('preserves parser normalization and table disablement without leaking table protection', () => {
    const source = '| Formula | Notes |\n| --- | --- |\n' + String.raw`| \(|A|\) | ` + '\0 private \ue000 |';
    const md = parser();
    expect(md.parse(source).filter(token => token.type === 'inline').at(-1)?.content).toBe('\ufffd private \ue000');
    expect(mathTokens(source)).toMatchObject([{ raw: String.raw`\(|A|\)` }]);
    configureFocusMarkdownMath(md);
    md.disable('table');
    expect(md.parse(source).some(token => token.type === 'table_open')).toBe(false);

    const disabled = getMarkdown(`focus-no-tables-${parserId++}`).disable('table');
    configureFocusMarkdownMath(disabled);
    expect(disabled.parse(source).some(token => token.type === 'table_open')).toBe(false);
  });

  it('wires the exact grammar into the real renderer and preserves source fallback', async () => {
    const literal = await renderToString(markdownApp('$PATH $x$ before $$x$$ after'));
    expect(literal).not.toContain('data-markstream-math');
    expect(literal).toContain('$PATH $x$ before $$x$$ after');

    const inline = await renderToString(markdownApp(String.raw`\(x + y\)`));
    expect(inline).toContain('data-markstream-math="inline"');
    expect(inline).toContain(String.raw`\(x + y\)`);

    const block = await renderToString(markdownApp('$$x + y$$'));
    expect(block).toContain('data-markstream-math="block"');
    expect(block).toContain('$$x + y$$');

    const unsupported = await renderToString(markdownApp(String.raw`\(unclosed and \[inline\]`));
    expect(unsupported).not.toContain('data-markstream-math');
    expect(unsupported).toContain(String.raw`\(unclosed and \[inline\]`);
  });
});
