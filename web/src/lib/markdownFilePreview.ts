import type { MarkdownIt } from 'markstream-vue';
import { configureFocusMarkdown } from './markdownParser';

const configured = new WeakSet<object>();

/** File previews never fetch embedded resources. Parser tokens also cover
 * reference images, escaped paths and images nested in lists or tables. */
export function configureFilePreviewMarkdown(md: MarkdownIt): MarkdownIt {
  configureFocusMarkdown(md);
  md.set({ html: false });
  if (!configured.has(md)) {
    // Run after upstream HTML-repair rules, which can manufacture HTML tokens
    // even when raw HTML is disabled in the initial parse.
    md.core.ruler.push('focus_file_preview_images', (state) => {
      const rewrite = (tokens: typeof state.tokens): void => {
        for (let i = 0; i < tokens.length; i++) {
          const token = tokens[i]!;
          if (token.type === 'image') {
            const link = new state.Token('link_open', 'a', 1);
            link.attrSet('href', token.attrGet('src') ?? '');
            const label = new state.Token('text', '', 0);
            label.content = token.content || token.attrGet('src') || '';
            tokens.splice(i, 1, link, label, new state.Token('link_close', 'a', -1));
            i += 2;
          } else if (token.type === 'html_inline' || token.type === 'html_block') {
            // stream-markdown recognizes some HTML even with html:false.
            // Keep those tokens literal before any renderer can create nodes.
            token.type = 'text';
            token.tag = '';
            token.nesting = 0;
          } else if (token.children) rewrite(token.children);
        }
      };
      rewrite(state.tokens);
    });
    configured.add(md);
  }
  return md;
}
