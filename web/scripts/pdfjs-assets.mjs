// Only assets used by the browser preview with useWasm:false. Keep the matching
// upstream license evidence in both the static delivery and the notice set.
export const PDFJS_ASSET_DIRECTORIES = ['cmaps', 'standard_fonts'];
export const PDFJS_DECODER_FILES = [
  'jbig2_nowasm_fallback.js', 'openjpeg_nowasm_fallback.js',
  'LICENSE_JBIG2', 'LICENSE_OPENJPEG', 'LICENSE_PDFJS_JBIG2', 'LICENSE_PDFJS_OPENJPEG',
];
export const PDFJS_ASSET_LICENSES = [
  'cmaps/LICENSE', 'standard_fonts/LICENSE_FOXIT', 'standard_fonts/LICENSE_LIBERATION',
  ...PDFJS_DECODER_FILES.filter(name => name.startsWith('LICENSE')).map(name => `wasm/${name}`),
];
