import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { build } from 'vite';
import { expect, it } from 'vitest';
import { focusPdfAssetsPlugin } from '../scripts/focus-pdf-assets';
import { PDFJS_ASSET_LICENSES } from '../scripts/pdfjs-assets.mjs';

it('ships version-matched local PDF resources and their license evidence, without unused Wasm or native packages', async () => {
  const root = mkdtempSync(join(tmpdir(), 'focus-pdf-assets-'));
  try {
    writeFileSync(join(root, 'main.js'), 'export const fixture = 1;');
    const result = await build({ configFile: false, root, logLevel: 'silent', plugins: [focusPdfAssetsPlugin()],
      build: { write: false, rollupOptions: { input: join(root, 'main.js') } } });
    if (Array.isArray(result) || !('output' in result)) throw new Error('Expected one build output');
    const files = new Map(result.output.filter(o => o.type === 'asset').map(o => [o.fileName, Buffer.from(o.source)]));
    const packageRoot = resolve('node_modules/pdfjs-dist');
    const version = JSON.parse(readFileSync(join(packageRoot, 'package.json'), 'utf8')).version;
    for (const path of ['cmaps/UniGB-UCS2-H.bcmap', 'standard_fonts/LiberationSans-Regular.ttf',
      'wasm/openjpeg_nowasm_fallback.js', 'wasm/jbig2_nowasm_fallback.js', ...PDFJS_ASSET_LICENSES]) {
      expect(files.get(`pdfjs/${version}/${path}`)).toEqual(readFileSync(join(packageRoot, path)));
    }
    expect([...files.keys()].some(path => /\.wasm$|quickjs|napi|canvas|\.map$/.test(path))).toBe(false);
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 20_000);
