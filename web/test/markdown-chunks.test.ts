import { describe, expect, it } from 'vitest';
import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createI18n } from 'vue-i18n';
import { markdownChunks } from '../src/lib/markdownChunks';
import Markdown from '../src/components/chat/Markdown.vue';

function flatten(nodes: unknown[]): Record<string, unknown>[] {
  return nodes.flatMap(value => {
    if (!value || typeof value !== 'object') return [];
    const node = value as Record<string, unknown>;
    return [node, ...Object.values(node).flatMap(child => Array.isArray(child) ? flatten(child)
      : child && typeof child === 'object' ? flatten([child]) : [])];
  });
}
const padding = Array.from({ length: 60 }, (_, i) => `段落 ${i} ${'内容 '.repeat(80)}`).join('\n\n');

describe('progressive reply Markdown', () => {
  it('keeps document references, nested lists, table math and complete fences across groups', () => {
    const table = String.raw`| A | B |
| --- | --- |
| \(\lvert x\rvert\) | **重点。**随后 |`;
    const source = `[early][ref]\n\n${padding}\n\n${table}\n\n- parent\n  - child\n\n\`\`\`js\n${'code\n'.repeat(3000)}\`\`\`\n\n[ref]: https://example.com/end`;
    const chunks = markdownChunks(source);
    expect(chunks.length).toBeGreaterThan(2);
    const all = flatten(chunks.flatMap(chunk => chunk.nodes));
    expect(all.find(node => node.type === 'link')?.href).toBe('https://example.com/end');
    expect(all.filter(node => node.type === 'table')).toHaveLength(1);
    expect(all.find(node => node.type === 'math_inline')?.content).toContain('lvert');
    const code = all.filter(node => node.type === 'code_block');
    expect(code).toHaveLength(1); expect(code[0]?.code).toBe('code\n'.repeat(3000));
    expect(all.filter(node => node.type === 'list')).toHaveLength(2);
    expect(chunks.flatMap(chunk => chunk.nodes).filter(node => node.type === 'paragraph')).toHaveLength(61);
  });

  it.each([false, true])('preserves every original diff line without applying/omitting it (long=%s)', async (long) => {
    const diff = Array.from({ length: 100 }, (_, i) => `${i % 2 ? '+' : '-'}LINE ${i}`).join('\n');
    const source = `\`\`\`diff\n${diff}\n\`\`\``;
    expect(markdownChunks(source)[0]?.nodes[0]).toMatchObject({ type: 'code_block', language: 'diff', code: `${diff}\n`, diff: false });
    const app = createSSRApp({ render: () => h(Markdown, { text: long ? `${padding}\n\n${padding}\n\n${source}` : source, progressive: true }) });
    app.use(createI18n({ legacy: false, locale: 'en', messages: { en: {} } }));
    app.provide('resolveImage', undefined);
    const html = await renderToString(app);
    const text = html.replace(/<[^>]+>/g, '');
    expect(text).toContain('-LINE 50'); expect(text).toContain('+LINE 99');
    expect(html).not.toContain('linesOmitted');
  });
});
