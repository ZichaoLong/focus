import { createSSRApp, defineComponent, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createI18n } from 'vue-i18n';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Markdown from '../src/components/chat/Markdown.vue';
import filePreview from '../src/i18n/locales/en/filePreview';

const copySources = vi.hoisted(() => [] as string[]);
// Observe the clipboard component's input, while using the real parser and
// formula/fallback renderers. Browser verification exercises the actual clicks.
vi.mock('../src/components/chat/MarkdownCopyButton.vue', () => ({
  default: defineComponent({
    props: { source: { type: String, required: true }, label: String },
    setup(props) {
      copySources.push(props.source);
      return () => h('button', { 'aria-label': props.label });
    },
  }),
}));

async function render(source: string, streaming = false): Promise<string> {
  const app = createSSRApp({ render: () => h(Markdown, { text: source, streaming }) });
  app.use(createI18n({ legacy: false, locale: 'en', messages: { en: { filePreview } } }));
  app.provide('resolveImage', undefined);
  return renderToString(app);
}

beforeEach(() => { copySources.length = 0; });

describe('Markdown source copy controls', () => {
  it('keeps code and text copy controls when the highlighter uses its fallback', async () => {
    const html = await render('```python\n  hello()\n```\n\n```text\nplain text\n```');
    expect(html.match(/aria-label="Copy code"/gu)).toHaveLength(2);
    expect(copySources).toEqual(['  hello()\n', 'plain text\n']);
  });

  it('copies raw LaTeX even when math rendering falls back to source', async () => {
    const inline = String.raw`x + \t y`;
    const block = '\n' + String.raw`\unsupportedcommand{x} + \frac{a}{b}` + '\n';
    const html = await render(`inline \\(${inline}\\)\n\n$$${block}$$`);

    expect(html).toContain('data-markstream-mode="fallback"');
    expect(html.match(/aria-label="Copy LaTeX"/gu)).toHaveLength(2);
    expect(copySources).toEqual([inline, block]);
  });

  it('offers formula copy inside emphasis, lists, quotes, and table cells', async () => {
    const html = await render([
      String.raw`**bold \(a\)**`,
      '',
      String.raw`- list \(b\)`,
      '',
      String.raw`> \[c\]`,
      '',
      '| formula |',
      '| --- |',
      String.raw`| \(d\) |`,
    ].join('\n'));

    expect(html.match(/aria-label="Copy LaTeX"/gu)).toHaveLength(4);
    expect(copySources).toEqual(['a', 'b', 'c', 'd']);
  });

  it('does not add formula buttons to literal, escaped, or unclosed syntax', async () => {
    const html = await render([
      '$x$ and prose $$x$$ and $5',
      String.raw`\\(escaped\\)`,
      String.raw`inline \[block\] text`,
      String.raw`\(unfinished`,
      '',
      '$$unclosed',
      '',
      '`\\(code\\)`',
    ].join('\n'));

    expect(html).not.toContain('aria-label="Copy LaTeX"');
    expect(copySources).toEqual([]);
  });

  it('waits for closed delimiters while streaming', async () => {
    await render(String.raw`before \(x + y`, true);
    await render('$$\nx + y', true);
    expect(copySources).toEqual([]);
    await render(String.raw`before \(x + y\)`, true);
    await render('$$\nx + y\n$$', true);
    expect(copySources).toEqual(['x + y', '\nx + y\n']);
  });

  it('keeps a copy header on code and text in the heavy-message pre renderer', async () => {
    const code = '  original code\n'.repeat(2001);
    const text = 'line one\n  line two';
    const html = await render(`\`\`\`python\n${code}\`\`\`\n\n\`\`\`text\n${text}\n\`\`\``);

    expect(html.match(/aria-label="Copy code"/gu)).toHaveLength(2);
    expect(copySources).toEqual([code, `${text}\n`]);
    expect(html).toContain('code-pre-fallback');
  });
});
