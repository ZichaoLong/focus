import { getMarkdown } from 'stream-markdown-parser';
import katex from 'katex';
import { configureFocusMarkdown } from '../lib/markdownParser';

/** Static, complete rendering: no chat virtualization, diff folding or workers. */
export interface SummaryPrintRenderOptions {
  server?: boolean;
  formula?(tex: string, block: boolean): string;
  progress?(done: number, total: number): void;
  warning?(kind: 'formula' | 'image' | 'table', round: number): void;
}
export function renderSummaryPrintMarkdown(source: string, options: SummaryPrintRenderOptions = {}): { html: string; fallback: boolean } {
  const md = configureFocusMarkdown(getMarkdown('focus-summary-print'));
  md.set({ html: false, linkify: true });
  const escape = md.utils.escapeHtml;
  let fallback = false;
  let formulaCount = 0;
  let processed = 0;
  const rounds = new WeakMap<object, number>();
  const rules = md.renderer.rules;
  rules.fence = rules.code_block = (tokens, index) => {
    const token = tokens[index]!;
    const language = token.info?.trim().split(/\s+/)[0] ?? '';
    const diagram = language.toLowerCase() === 'mermaid' ? ' class="summary-mermaid"' : '';
    return `<pre${diagram}${options.server && diagram ? ' data-round="' + (rounds.get(token) ?? 0) + '"' : ''}><code>${escape(token.content)}</code></pre>\n`;
  };
  for (const type of ['math_inline', 'math_block']) {
    rules[type] = (tokens, index) => {
      const token = tokens[index]! as typeof tokens[number] & { raw?: string };
      const block = type === 'math_block';
      if (options.server) options.progress?.(++processed, formulaCount);
      const raw = token.raw ?? token.content;
      try {
        if (options.formula) return options.formula(token.content, block);
        const math = katex.renderToString(token.content, {
          displayMode: block, throwOnError: true, trust: false, strict: 'ignore',
          maxExpand: 1000, maxSize: 20, output: options.server ? 'html' : 'htmlAndMathml',
        });
        return `<${block ? 'div' : 'span'} class="summary-math" data-source="${escape(raw)}">${math}</${block ? 'div' : 'span'}>`;
      } catch {
        options.warning?.('formula', rounds.get(token) ?? 0);
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
    if (options.server && !/^data:image\/(?:png|jpeg);base64,/i.test(src)) {
      options.warning?.('image', rounds.get(token) ?? 0);
      return escape(alt ? alt + ' (' + src + ')' : src);
    }
    if (!/^https?:\/\//i.test(src) && !/^data:image\/(?:png|jpeg|gif|webp);base64,/i.test(src)) {
      fallback = true;
      return `<span class="summary-source">${escape(`![${alt}](${src})`)}</span>`;
    }
    return `<img src="${escape(src)}" alt="${escape(alt)}" referrerpolicy="no-referrer" loading="eager">`;
  };
  const env = { __markstreamFinal: true };
  const tokens = md.parse(source, env);
  if (options.server) {
    let round = 0;
    function indexTokens(items: typeof tokens): void {
      for (const [i, item] of items.entries()) {
        if (item.type === 'heading_open' && item.tag === 'h2') {
          const heading = /^(\d+)\.\s/.exec(items[i + 1]?.content ?? '');
          if (heading) round = Number(heading[1]);
        }
        rounds.set(item, round);
        if (item.type === 'table_open') item.attrSet('data-round', String(round));
        if (item.type === 'math_block' || item.type === 'math_inline') formulaCount++;
        if (item.children) indexTokens(item.children);
      }
    }
    indexTokens(tokens);
    options.progress?.(0, formulaCount);
  }
  return { html: md.renderer.render(tokens, md.options, env), fallback };
}
