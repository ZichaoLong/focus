import { renderToString } from '@vue/server-renderer';
import { createSSRApp, h } from 'vue';
import { createI18n } from 'vue-i18n';
import { getMarkdown, parseMarkdownToStructure } from 'markstream-vue';
import { describe, expect, it } from 'vitest';
import Markdown from '../src/components/chat/Markdown.vue';
import { configureFocusMarkdown } from '../src/lib/markdownParser';

let parserId = 0;
const parser = () => configureFocusMarkdown(getMarkdown(`focus-emphasis-${parserId++}`));
const render = (source: string) => parser().render(source, { __markstreamFinal: true });

describe('Focus Markdown emphasis', () => {
  it.each([
    ['**已有缓存可以继续使用。**例如，规则固定时。', '<strong>已有缓存可以继续使用。</strong>例如，规则固定时。'],
    ['所以，**通常需要重算。**某些实现会近似复用。', '所以，<strong>通常需要重算。</strong>某些实现会近似复用。'],
    ['这里**“重点”**后续', '这里<strong>“重点”</strong>后续'],
    ['**中文！**后续**另一句？**继续', '<strong>中文！</strong>后续<strong>另一句？</strong>继续'],
    ['𠀀**“扩展汉字。”**𠀁', '𠀀<strong>“扩展汉字。”</strong>𠀁'],
    ['これは**「強調。」**です', 'これは<strong>「強調。」</strong>です'],
    ['앞**“강조.”**뒤', '앞<strong>“강조.”</strong>뒤'],
    ['**循环状态是否压缩历史。**Mamba、DeltaNet', '<strong>循环状态是否压缩历史。</strong>Mamba、DeltaNet'],
    ['**NoPE。**RoPE', '<strong>NoPE。</strong>RoPE'],
    ['**结论。**2026', '<strong>结论。</strong>2026'],
    ['RoPE**（局部）**NoPE', 'RoPE<strong>（局部）</strong>NoPE'],
    ['2026**【重点】**3', '2026<strong>【重点】</strong>3'],
    ['before**“中文”**after', 'before<strong>“中文”</strong>after'],
    ['v2**“中文。”**v3', 'v2<strong>“中文。”</strong>v3'],
    ['Latin**「強調」**Latin', 'Latin<strong>「強調」</strong>Latin'],
    ["Mamba**'中文'**2", 'Mamba<strong>’中文’</strong>2'],
    ['**中文...**Next', '<strong>中文…</strong>Next'],
    ['RoPE**“𠀀”**2', 'RoPE<strong>“𠀀”</strong>2'],
  ])('renders CJK punctuation boundaries: %s', (source, expected) => {
    expect(render(source)).toBe(`<p>${expected}</p>\n`);
  });

  it('keeps nested inline markup and container boundaries', () => {
    const html = render('> **包含 *斜体*、`code` 和 [链接](https://example.com)。**后续\n\n- **列表。**内容\n\n| 表格 |\n| --- |\n| **单元格。**内容 |');
    expect(html).toContain('<strong>包含 <em>斜体</em>、<code>code</code> 和 <a href="https://example.com">链接</a>。</strong>后续');
    expect(html).toContain('<strong>列表。</strong>内容');
    expect(html).toContain('<strong>单元格。</strong>内容');
    expect(html).toContain('<blockquote>');
    expect(html).toContain('<table>');
  });

  it.each([
    '`**代码。**后续`',
    '```text\n**代码。**后续\n  保留缩进\n```',
    String.raw`\*\*转义。\*\*后续`,
    'English **sentence.**Next',
    'English**“sentence”**Next',
    "English**'sentence'**2",
    '** spaced。**Next',
    'before**“未闭合',
    '`**代码。**Mamba`',
    '```text\n**代码。**Mamba\n```',
    String.raw`\*\*转义。\*\*Mamba`,
    '[地址](https://example.com/**中文。**Mamba)',
    '** spaced ** and *emphasis* and ***both*** and __strong__',
    '未闭合**“内容',
    '[地址](https://example.com/**path**)',
  ])('preserves existing literal/standard Markdown behavior: %s', (source) => {
    const md = getMarkdown(`focus-emphasis-baseline-${parserId++}`);
    const expected = md.render(source, { __markstreamFinal: true });
    expect(configureFocusMarkdown(md).render(source, { __markstreamFinal: true })).toBe(expected);
  });

  it('leaves formula source intact while recognizing surrounding emphasis', () => {
    const tokens = parser().parse(String.raw`**公式 \(x^{**}\) 保持原样。**Mamba`, { __markstreamFinal: true });
    const children = tokens.find(token => token.type === 'inline')!.children!;
    expect(children.filter(token => token.type === 'strong_open')).toHaveLength(1);
    expect(children.find(token => token.type === 'math_inline')?.content).toBe('x^{**}');
  });

  it('keeps the CJK closing delimiter during streaming and final structure parsing', () => {
    const md = parser();
    for (const final of [false, true]) {
      for (const source of ['**结论。**', '**结论。**后', '**结论。**后续文字',
        '**结论。**M', '**结论。**Mamba', '**结论。**2', '**结论。**2026']) {
        const nodes = parseMarkdownToStructure(source, md, { final });
        expect(nodes[0]?.type).toBe('paragraph');
        const children = (nodes[0] as { children: unknown[] }).children;
        expect(children[0]).toMatchObject({
          type: 'strong', children: [expect.objectContaining({ type: 'text', content: '结论。' })],
        });
      }
    }
  });

  it('renders the actual chat component with emphasis, soft/hard breaks and paragraphs', async () => {
    const text = '**结论。**Mamba\n普通换行  \n硬换行\n\n另一段';
    const app = createSSRApp({ render: () => h(Markdown, { text }) });
    app.use(createI18n({ legacy: false, locale: 'en', messages: { en: {} } }));
    app.provide('resolveImage', undefined);
    const html = await renderToString(app);
    expect(html.match(/<strong\b/g)).toHaveLength(1);
    expect(html.match(/<p\b/g)).toHaveLength(2);
    expect(html).toContain('Mamba\n普通换行');
    expect(html).toMatch(/<br\b/);
    expect(html).not.toContain('**');
  });
});
