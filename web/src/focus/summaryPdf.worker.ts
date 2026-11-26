import init, { render, type FontLoader, type RenderOptions } from 'takumi-pdf/no-init';
import wasmUrl from 'takumi-pdf/takumi_pdf_wasm_bg.wasm?url';
import interRanges from '@fontsource-variable/inter/unicode.json';
import sansRanges from '@fontsource-variable/noto-sans-sc/unicode.json';
import emojiRanges from '@fontsource-variable/noto-emoji/unicode.json';
import monoRanges from '@fontsource-variable/jetbrains-mono/unicode.json';
import paperCss from './summaryPrintContent.css?raw';

// Only the subsets used by this particular document are fetched by the renderer.
const fontUrls = import.meta.glob<string>(
  '/node_modules/@fontsource-variable/{inter,noto-sans-sc,noto-emoji,jetbrains-mono}/files/*-wght-normal.woff2',
  { eager: true, query: '?url', import: 'default' },
);
function faces(pkg: string, name: string, ranges: Record<string, string>): FontLoader[] {
  return Object.entries(ranges).map(([subset, spec]) => {
    const part = subset.replace(/[\[\]]/g, '');
    const key = `${pkg}-${part}-wght-normal.woff2`;
    const url = fontUrls[`/node_modules/@fontsource-variable/${pkg}/files/${key}`];
    return {
      name, key, unicodeRange: spec.split(',').map(range => {
        const [start, end] = range.slice(2).split('-').map(hex => parseInt(hex, 16));
        return [start!, end ?? start!] as [number, number];
      }),
      data: async () => {
        if (!url) throw new Error('Missing PDF font asset');
        const response = await fetch(url);
        if (!response.ok) throw new Error('PDF font load failed');
        return response.arrayBuffer();
      },
    };
  });
}

export interface PdfSource {
  html: string;
  title: string;
  lang: string;
  images: { src: string; data: Uint8Array<ArrayBuffer> }[];
}

// The preview's paper rules apply to the same semantic article. Fix the paper dimensions
// independently of the screen and use the embedded families for portable, searchable text.
const pdfCss = `
.summary-print-content { padding: 0; margin: 0; max-width: none; color: #171717; font-family: 'Focus Inter', 'Focus Sans', 'Focus Emoji'; font-size: 14px; line-height: 1.55; }
.summary-print-content strong, .summary-print-content th { font-weight: 700; }
.summary-print-content :is(h1,h2,h3,h4,h5,h6) { font-weight: 600; }
.summary-print-content code, .summary-print-content pre { font-family: 'Focus Mono', 'Focus Sans', 'Focus Emoji'; }
.summary-print-content pre { font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; }
.summary-print-content table { font-size: 12px; }
.summary-print-content img { max-width: 100%; max-height: 940px; object-fit: contain; }
`;

self.onmessage = async ({ data }: MessageEvent<PdfSource>) => {
  try {
    await init({ module_or_path: wasmUrl });
    const options = {
      size: 'a4', margin: 60, css: [paperCss, pdfCss], lang: data.lang,
      metadata: { title: data.title }, images: data.images,
      fonts: [...faces('inter', 'Focus Inter', interRanges), ...faces('noto-sans-sc', 'Focus Sans', sansRanges), ...faces('noto-emoji', 'Focus Emoji', emojiRanges),
        ...faces('jetbrains-mono', 'Focus Mono', monoRanges)],
      fontFamilies: ['Focus Inter', 'Focus Sans', 'Focus Emoji'],
    } satisfies RenderOptions;
    let bytes: Uint8Array<ArrayBuffer>;
    let missingGlyphs = false;
    try { bytes = await render(data.html, options); }
    catch (error) {
      if (!(error instanceof Error) || !error.message.startsWith('No font the text can use draws')) throw error;
      missingGlyphs = true;
      bytes = await render(data.html, { ...options, uncoveredText: 'placeholder' });
    }
    self.postMessage({ bytes: bytes.buffer, missingGlyphs }, { transfer: [bytes.buffer] });
  } catch { self.postMessage(null); }
};
