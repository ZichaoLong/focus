import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';
import { PDFJS_ASSET_DIRECTORIES, PDFJS_DECODER_FILES } from './pdfjs-assets.mjs';

/** Same local URLs in development and in the installable static bundle. */
export function focusPdfAssetsPlugin(): Plugin {
  const root = new URL('../node_modules/pdfjs-dist/', import.meta.url);
  const version = JSON.parse(readFileSync(new URL('package.json', root), 'utf8')).version as string;
  const prefix = `/pdfjs/${version}/`;
  const files = new Map<string, URL>();
  for (const directory of PDFJS_ASSET_DIRECTORIES) {
    for (const name of readdirSync(new URL(`${directory}/`, root)).sort()) {
      files.set(`${directory}/${name}`, new URL(`${directory}/${name}`, root));
    }
  }
  for (const name of PDFJS_DECODER_FILES) files.set(`wasm/${name}`, new URL(`wasm/${name}`, root));
  return {
    name: 'focus-pdf-assets',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const path = request.url?.split('?')[0] ?? '';
        const file = path.startsWith(prefix) ? files.get(path.slice(prefix.length)) : undefined;
        if (!file) { next(); return; }
        response.setHeader('Content-Type', file.pathname.endsWith('.js') ? 'text/javascript' : 'application/octet-stream');
        response.end(readFileSync(file));
      });
    },
    generateBundle() {
      for (const [name, file] of files) {
        this.emitFile({ type: 'asset', fileName: `${prefix.slice(1)}${name}`, source: readFileSync(fileURLToPath(file)) });
      }
    },
  };
}
