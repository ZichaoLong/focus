import { constants, gzipSync } from 'node:zlib';
import type { Plugin } from 'vite';

/** Emit deterministic siblings for aiohttp's static-file delivery. */
export function focusStaticCompressionPlugin(): Plugin {
  return {
    name: 'focus-static-compression',
    apply: 'build',
    enforce: 'post',
    generateBundle: {
      // Vite rewrites dynamic-import preload maps in generateBundle. A post
      // plugin alone still runs before that internal hook; gzip the final bytes.
      order: 'post',
      handler(_options, bundle) {
        for (const output of Object.values(bundle)) {
          if (!/\.(?:m?js|css|html)$/.test(output.fileName)) continue;
          const source = Buffer.from(output.type === 'chunk' ? output.code : output.source);
          if (source.length < 1024) continue;
          const compressed = gzipSync(source, { level: constants.Z_BEST_COMPRESSION });
          if (compressed.length >= source.length) continue;
          this.emitFile({ type: 'asset', fileName: `${output.fileName}.gz`, source: compressed });
        }
      },
    },
  };
}
