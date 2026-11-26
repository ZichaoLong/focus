import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { build, type Plugin } from 'vite';
import { expect, it } from 'vitest';
import { focusStaticCompressionPlugin } from '../scripts/focus-static-compression';

it('builds reproducible gzip siblings without changing asset URLs or original bytes', async () => {
  const root = mkdtempSync(join(tmpdir(), 'focus-static-compression-'));
  const fixtures = (): Plugin => ({
    name: 'compression-fixtures',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'assets/tiny.js', source: 'console.log(1)' });
      this.emitFile({ type: 'asset', fileName: 'assets/pdf.worker.mjs', source: '/* PDF worker */\n'.repeat(200) });
      this.emitFile({ type: 'asset', fileName: 'assets/typesetter.wasm', source: new Uint8Array(2048) });
      this.emitFile({ type: 'asset', fileName: 'assets/font.woff2', source: new Uint8Array(2048) });
    },
  });
  try {
    writeFileSync(join(root, 'index.html'), `<html><body>${'<p>Focus</p>'.repeat(200)}<script type="module" src="/main.js"></script></body></html>`);
    writeFileSync(join(root, 'main.js'), `import './style.css'; window.loadFeature = () => import('./lazy.js'); document.body.dataset.content = ${JSON.stringify('Focus slow-network startup. '.repeat(200))};`);
    writeFileSync(join(root, 'style.css'), Array.from({ length: 120 }, (_, i) => `.row-${i} { color: #123456; padding: ${i}px; }`).join('\n'));
    writeFileSync(join(root, 'lazy.js'), "import './lazy.css'; export const feature = 'Ready';");
    writeFileSync(join(root, 'lazy.css'), '.lazy { color: blue; }');
    const compile = async (compressed: boolean) => {
      const result = await build({ configFile: false, root, logLevel: 'silent',
        plugins: [fixtures(), ...(compressed ? [focusStaticCompressionPlugin()] : [])],
        build: { write: false, sourcemap: true } });
      if (Array.isArray(result) || !('output' in result)) throw new Error('Expected one build output');
      return new Map(result.output.map(output => [output.fileName,
        Buffer.from(output.type === 'chunk' ? output.code : output.source)]));
    };
    const original = await compile(false), compressed = await compile(true), repeated = await compile(true);
    expect(repeated).toEqual(compressed);
    for (const [name, source] of original) expect(compressed.get(name)).toEqual(source);
    const siblings = [...compressed.keys()].filter(name => name.endsWith('.gz'));
    expect(siblings).toContain('index.html.gz');
    expect(siblings.some(name => name.endsWith('.js.gz'))).toBe(true);
    expect(siblings.some(name => name.endsWith('.css.gz'))).toBe(true);
    expect(siblings).toContain('assets/pdf.worker.mjs.gz');
    expect(siblings).toContain('assets/typesetter.wasm.gz');
    expect(siblings.some(name => name.endsWith('.map.gz') || name.endsWith('.woff2.gz'))).toBe(false);
    expect(compressed.has('assets/tiny.js.gz')).toBe(false);
    for (const name of siblings) {
      const bytes = compressed.get(name)!, source = original.get(name.slice(0, -3))!;
      expect(gunzipSync(bytes)).toEqual(source);
      expect(bytes.length).toBeLessThan(source.length);
      expect(bytes.readUInt32LE(4)).toBe(0); // No build timestamp in gzip metadata.
    }
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 20_000);
