import { createSSRApp, h } from 'vue';
import { renderToString } from '@vue/server-renderer';
import { createI18n } from 'vue-i18n';
import { describe, expect, it } from 'vitest';
import { getMarkdown } from 'markstream-vue';
import Markdown from '../src/components/chat/Markdown.vue';
import { configureFilePreviewMarkdown } from '../src/lib/markdownFilePreview';

let parserId = 0;
const parse = (text: string) => configureFilePreviewMarkdown(getMarkdown(`preview-${++parserId}`)).render(text);

describe('file Markdown embedded-resource policy', () => {
  it('turns ordinary, reference and nested images into explicit links', () => {
    const rendered = parse('![photo](images/photo.png)\n\n![web][remote]\n\n[remote]: https://example.test/photo.jpg\n\n- ![in list](./list.png)');
    expect(rendered).not.toContain('<img');
    expect(rendered).toContain('href="images/photo.png"');
    expect(rendered).toContain('href="https://example.test/photo.jpg"');
    expect(rendered).toContain('href="./list.png"');
  });

  it('displays raw HTML as source and preserves literal code examples', () => {
    const rendered = parse('<img src="/secret.png">\n\n<video src="movie.mp4"></video>\n\n`![example](a.png)`\n\n```html\n<img src="code.png">\n```');
    expect(rendered).not.toMatch(/<(img|video|iframe)\b/);
    expect(rendered).toContain('&lt;img');
    expect(rendered).toContain('![example](a.png)');
    const tokens = configureFilePreviewMarkdown(getMarkdown(`preview-code-${++parserId}`))
      .parse('```html\n<img src="code.png">\n```', {});
    expect(tokens.find(token => token.type === 'fence')?.content).toBe('<img src="code.png">\n');
  });

  it('preserves math/table grammar and does not change the ordinary Markdown parser', () => {
    const rendered = parse('| Formula |\n| --- |\n| \\(a \\vert b\\) |');
    expect(rendered).toContain('<table');
    const parser = configureFilePreviewMarkdown(getMarkdown(`preview-math-${++parserId}`));
    const tokens = parser.parse('| Formula |\n| --- |\n| \\(a \\vert b\\) |', {});
    expect(tokens.flatMap(token => token.children ?? []).find(token => token.type === 'math_inline')?.content).toBe('a \\vert b');
    expect(getMarkdown('normal-file-preview-neighbor').render('![web](https://example.test/a.png)')).toContain('<img');
  });

  it('enforces the no-fetch policy in the actual Markdown component before DOM insertion', async () => {
    const app = createSSRApp({ render: () => h(Markdown, {
      text: '![web](https://example.test/a.png)\n\n![local][pic]\n\n[pic]: ./picture.png\n\n<img src="/raw.png">',
      deferImages: true,
    }) });
    app.use(createI18n({ legacy: false, locale: 'en', messages: { en: {} } }));
    app.provide('resolveImage', undefined);
    const rendered = await renderToString(app);
    expect(rendered).not.toContain('<img');
    expect(rendered).toContain('href="https://example.test/a.png"');
    expect(rendered).toContain('href="./picture.png"');
  });
});
