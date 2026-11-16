export const CODE_PREVIEW_CHARS = 30_000;
export const MERMAID_PREVIEW_BYTES = 32 * 1024;

const languages: Record<string, string> = {
  js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'jsx', ts: 'typescript', tsx: 'tsx',
  py: 'python', pyi: 'python', sh: 'shellscript', bash: 'shellscript', zsh: 'shellscript', fish: 'fish',
  c: 'c', h: 'c', cc: 'cpp', cpp: 'cpp', hpp: 'cpp', cs: 'csharp', go: 'go', rs: 'rust', java: 'java',
  kt: 'kotlin', swift: 'swift', rb: 'ruby', php: 'php', pl: 'perl', r: 'r', sql: 'sql',
  vue: 'vue', svelte: 'svelte', css: 'css', scss: 'scss', less: 'less', xml: 'xml',
  yaml: 'yaml', yml: 'yaml', toml: 'toml', ini: 'ini', cfg: 'ini', conf: 'ini',
  properties: 'properties', env: 'dotenv', tex: 'latex', bib: 'bibtex', rst: 'rst',
  diff: 'diff', patch: 'diff', editorconfig: 'ini',
};
const names: Record<string, string> = { dockerfile: 'dockerfile', makefile: 'make', justfile: 'just' };

export function filePreviewLanguage(name: string): string | undefined {
  const lower = name.toLowerCase();
  const extension = lower.split('.').at(-1) ?? '';
  return Object.hasOwn(names, lower) ? names[lower] : Object.hasOwn(languages, extension) ? languages[extension] : undefined;
}

/** Prevent file contents from closing the synthetic fence and becoming live Markdown. */
export function previewCodeFence(text: string, language: string): string {
  let length = 3;
  for (const run of text.matchAll(/`+/g)) length = Math.max(length, run[0].length + 1);
  const fence = '`'.repeat(length);
  return `${fence}${language}\n${text}\n${fence}`;
}
