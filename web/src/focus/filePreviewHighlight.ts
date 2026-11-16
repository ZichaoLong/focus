/** Lazy, bounded source highlighting using native RegExp, compatible with the app CSP. */
import { createHighlighterCore, type HighlighterCore } from 'shiki/core';
import { createJavaScriptRegexEngine } from 'shiki/engine/javascript';

const languages = {
  'bibtex': () => import('shiki/langs/bibtex.mjs'),
  'c': () => import('shiki/langs/c.mjs'),
  'cpp': () => import('shiki/langs/cpp.mjs'),
  'csharp': () => import('shiki/langs/csharp.mjs'),
  'css': () => import('shiki/langs/css.mjs'),
  'diff': () => import('shiki/langs/diff.mjs'),
  'dockerfile': () => import('shiki/langs/dockerfile.mjs'),
  'dotenv': () => import('shiki/langs/dotenv.mjs'),
  'fish': () => import('shiki/langs/fish.mjs'),
  'go': () => import('shiki/langs/go.mjs'),
  'ini': () => import('shiki/langs/ini.mjs'),
  'java': () => import('shiki/langs/java.mjs'),
  'javascript': () => import('shiki/langs/javascript.mjs'),
  'jsx': () => import('shiki/langs/jsx.mjs'),
  'just': () => import('shiki/langs/just.mjs'),
  'kotlin': () => import('shiki/langs/kotlin.mjs'),
  'latex': () => import('shiki/langs/latex.mjs'),
  'less': () => import('shiki/langs/less.mjs'),
  'make': () => import('shiki/langs/make.mjs'),
  'perl': () => import('shiki/langs/perl.mjs'),
  'php': () => import('shiki/langs/php.mjs'),
  'properties': () => import('shiki/langs/properties.mjs'),
  'python': () => import('shiki/langs/python.mjs'),
  'r': () => import('shiki/langs/r.mjs'),
  'rst': () => import('shiki/langs/rst.mjs'),
  'ruby': () => import('shiki/langs/ruby.mjs'),
  'rust': () => import('shiki/langs/rust.mjs'),
  'scss': () => import('shiki/langs/scss.mjs'),
  'shellscript': () => import('shiki/langs/shellscript.mjs'),
  'sql': () => import('shiki/langs/sql.mjs'),
  'svelte': () => import('shiki/langs/svelte.mjs'),
  'swift': () => import('shiki/langs/swift.mjs'),
  'toml': () => import('shiki/langs/toml.mjs'),
  'tsx': () => import('shiki/langs/tsx.mjs'),
  'typescript': () => import('shiki/langs/typescript.mjs'),
  'vue': () => import('shiki/langs/vue.mjs'),
  'xml': () => import('shiki/langs/xml.mjs'),
  'yaml': () => import('shiki/langs/yaml.mjs'),
};
let highlighter: Promise<HighlighterCore> | null = null;

export async function highlightPreviewCode(text: string, language: string, dark: boolean) {
  const loader = languages[language as keyof typeof languages];
  if (!Object.hasOwn(languages, language) || !loader) throw new Error('Unsupported language');
  highlighter ??= createHighlighterCore({
    themes: [import('shiki/themes/vitesse-dark.mjs'), import('shiki/themes/vitesse-light.mjs')],
    langs: [], engine: createJavaScriptRegexEngine(),
  });
  const instance = await highlighter;
  if (!instance.getLoadedLanguages().includes(language)) {
    const grammar = await loader();
    await instance.loadLanguage(grammar.default);
  }
  return instance.codeToTokens(text, { lang: language, theme: dark ? 'vitesse-dark' : 'vitesse-light' });
}
