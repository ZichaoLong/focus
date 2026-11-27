import { build } from 'esbuild';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// Emit a self-contained worker for the Python-managed JS runtime. No CDN or
// development node_modules tree participates in printing an installed document.
export async function summaryPdfAssets(emit) {
  const root = new URL('../', import.meta.url);
  const file = (path) => readFileSync(new URL(path, root));
  const result = await build({
    entryPoints: [fileURLToPath(new URL('server-pdf/render.mjs', root))],
    bundle: true, write: false, platform: 'node', target: 'node22', format: 'esm',
    banner: { js: 'import { createRequire } from "node:module"; const require = createRequire(import.meta.url);' },
    minify: true, legalComments: 'inline',
  });
  emit('render.mjs', result.outputFiles[0].contents);
  emit('render.wasm', file('node_modules/takumi-pdf/pkg/takumi_pdf_wasm_bg.wasm'));
  emit('paper.css', file('src/focus/summaryPrintContent.css'));
  emit('katex.css', file('node_modules/katex/dist/katex.css').toString().replace(/@font-face\s*\{[^}]*\}/g, ''));
  emit('mermaid.js', file('node_modules/mermaid/dist/mermaid.min.js'));
  const fonts = [];
  for (const [pkg, name] of [['inter','Focus Inter'], ['noto-sans-sc','Focus Sans'], ['noto-emoji','Focus Emoji'], ['jetbrains-mono','Focus Mono']]) {
    const base = 'node_modules/@fontsource-variable/' + pkg;
    for (const [subset, ranges] of Object.entries(JSON.parse(file(base + '/unicode.json')))) {
      const key = pkg + '-' + subset.replace(/[\[\]]/g,'') + '-wght-normal.woff2';
      emit('fonts/' + key, file(base + '/files/' + key));
      fonts.push({ name, key, ranges });
    }
  }
  for (const key of readdirSync(new URL('node_modules/katex/dist/fonts/', root)).sort().filter(name => name.endsWith('.woff2'))) {
    const [, name, face] = /^(KaTeX_\w+)-(\w+)\.woff2$/.exec(key);
    emit('fonts/' + key, file('node_modules/katex/dist/fonts/' + key));
    fonts.push({ name, key, weight: face.includes('Bold') ? 700 : 400, style: face.includes('Italic') ? 'italic' : 'normal' });
  }
  emit('fonts/DejaVuSans.ttf', file('server-pdf/DejaVuSans.ttf'));
  emit('fonts/DejaVu-LICENSE.txt', file('server-pdf/DejaVu-LICENSE.txt'));
  fonts.push({ name: 'Focus Symbols', key: 'DejaVuSans.ttf' });
  emit('fonts.json', JSON.stringify(fonts));
}

export function summaryPdfRendererPlugin() {
  return { name: 'focus-server-summary-pdf', apply: 'build', async generateBundle() {
    await summaryPdfAssets((name, source) => this.emitFile({ type: 'asset', fileName: 'server-pdf/' + name, source }));
  } };
}
