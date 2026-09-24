import { getMarkdown } from 'markstream-vue';
import katex from 'katex';
import { configureFocusMarkdown } from '../lib/markdownParser';

/** Static, complete rendering: no chat virtualization, diff folding or workers. */
export function renderSummaryPrintMarkdown(source: string): { html: string; fallback: boolean } {
  const md = configureFocusMarkdown(getMarkdown('focus-summary-print'));
  md.set({ html: false, linkify: true });
  const escape = md.utils.escapeHtml;
  let fallback = false;
  const rules = md.renderer.rules;
  rules.fence = rules.code_block = (tokens, index) => {
    const token = tokens[index]!;
    const language = token.info?.trim().split(/\s+/)[0] ?? '';
    const diagram = language.toLowerCase() === 'mermaid' ? ' class="summary-mermaid"' : '';
    return `<pre${diagram}><code>${escape(token.content)}</code></pre>\n`;
  };
  for (const type of ['math_inline', 'math_block']) {
    rules[type] = (tokens, index) => {
      const token = tokens[index]! as typeof tokens[number] & { raw?: string };
      const block = type === 'math_block';
      const raw = token.raw ?? token.content;
      try {
        const math = katex.renderToString(token.content, {
          displayMode: block, throwOnError: true, trust: false, strict: 'ignore',
          maxExpand: 1000, maxSize: 20, output: 'htmlAndMathml',
        });
        return `<${block ? 'div' : 'span'} class="summary-math" data-source="${escape(raw)}">${math}</${block ? 'div' : 'span'}>`;
      } catch {
        fallback = true;
        return `<${block ? 'pre' : 'code'} class="summary-source">${escape(raw)}</${block ? 'pre' : 'code'}>`;
      }
    };
  }
  rules.image = (tokens, index) => {
    const token = tokens[index]!;
    const src = token.attrGet('src') ?? '';
    const alt = token.content;
    // Local filesystem paths and authenticated media URLs are not portable
    // image resources. Preserve their Markdown instead of making blind fetches.
    if (!/^https?:\/\//i.test(src) && !/^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(src)) {
      fallback = true;
      return `<span class="summary-source">${escape(`![${alt}](${src})`)}</span>`;
    }
    return `<img src="${escape(src)}" alt="${escape(alt)}" referrerpolicy="no-referrer" loading="eager">`;
  };
  const env = { __markstreamFinal: true };
  const tokens = md.parse(source, env);
  return { html: md.renderer.render(tokens, md.options, env), fallback };
}
