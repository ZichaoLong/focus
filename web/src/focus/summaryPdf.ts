import type { PdfSource } from './summaryPdf.worker';

const mathFonts = import.meta.glob<string>('/node_modules/katex/dist/fonts/*.woff2', {
  eager: true, query: '?url', import: 'default',
});

// An SVG snapshot needs its own font faces. Embed the actual KaTeX faces used by
// this formula without scanning external stylesheets or changing the document base.
async function mathFontCss(node: HTMLElement, cache: Map<string, Promise<string>>, signal: AbortSignal) {
  const families = new Set<string>();
  for (const el of [node, ...node.querySelectorAll('*')]) {
    const family = getComputedStyle(el).fontFamily.match(/KaTeX_\w+/)?.[0];
    if (family) families.add(family);
  }
  const css: Promise<string>[] = [];
  for (const [path, url] of Object.entries(mathFonts)) {
    const [, family, face] = /\/(KaTeX_\w+)-(\w+)\.woff2$/.exec(path) ?? [];
    if (!family || !face || !families.has(family)) continue;
    let rule = cache.get(path);
    if (!rule) {
      rule = (async () => {
        let src = url;
        if (!src.startsWith('data:')) {
          const response = await fetch(url, { signal });
          if (!response.ok) throw new Error('Formula font unavailable');
          const blob = await response.blob();
          src = await new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result));
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
          });
        }
        return `@font-face{font-family:${family};font-weight:${face.includes('Bold') ? 700 : 400};font-style:${face.includes('Italic') ? 'italic' : 'normal'};src:url("${src}") format('woff2')}`;
      })();
      cache.set(path, rule);
    }
    css.push(rule);
  }
  return (await Promise.all(css)).join('\n');
}

/** Preserve the prepared preview's pictures, including browser-laid-out math and diagrams. */
async function pdfSource(article: HTMLElement, title: string, lang: string, signal: AbortSignal) {
  const inert = document.implementation.createHTMLDocument('');
  const copy = inert.importNode(article, true);
  const images: PdfSource['images'] = [];
  const fontCss = new Map<string, Promise<string>>();
  let fallback = false;
  const selector = 'img, .summary-math, .summary-diagram';
  const originals = [...article.querySelectorAll<HTMLElement>(selector)];
  const copies = [...copy.querySelectorAll<HTMLElement>(selector)];
  for (const [index, original] of originals.entries()) {
    signal.throwIfAborted();
    const target = copies[index]!;
    if (!copy.contains(target)) continue;
    const picture = original instanceof HTMLImageElement;
    const math = original.classList.contains('summary-math');
    const source = picture ? `![${original.alt}](${original.getAttribute('src') ?? ''})` : original.dataset.source ?? '';
    try {
      let blob: Blob | null;
      const img = inert.createElement('img');
      img.alt = picture ? original.alt : source;
      if (picture) {
        const ratio = Math.min(1, 2400 / Math.max(original.naturalWidth, original.naturalHeight));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(original.naturalWidth * ratio));
        canvas.height = Math.max(1, Math.round(original.naturalHeight * ratio));
        const context = canvas.getContext('2d');
        if (!context || !original.naturalWidth) throw new Error('Image unavailable');
        context.drawImage(original, 0, 0, canvas.width, canvas.height);
        blob = await new Promise(resolve => canvas.toBlob(resolve));
        img.setAttribute('width', String(Math.min(original.naturalWidth, 674)));
      } else {
        const node = math ? original.querySelector<HTMLElement>('.katex-html')! : original;
        const rect = node.getBoundingClientRect();
        if (!rect.width || !rect.height) throw new Error('Empty figure');
        const { toBlob } = await import('html-to-image');
        blob = await toBlob(node, {
          width: Math.ceil(rect.width), height: Math.ceil(rect.height),
          pixelRatio: Math.min(2, 2400 / Math.max(rect.width, rect.height)),
          style: { display: 'inline-block', margin: '0' },
          fontEmbedCSS: math ? await mathFontCss(node, fontCss, signal) : '',
        });
        if (math) img.style.width = `${rect.width / parseFloat(getComputedStyle(original).fontSize)}em`;
        else img.setAttribute('width', String(Math.min(Math.ceil(rect.width), 674)));
      }
      if (!blob?.size) throw new Error('Empty image');
      const src = `figure-${images.length}.png`;
      images.push({ src, data: new Uint8Array(await blob.arrayBuffer()) });
      img.setAttribute('src', src);
      if (!picture && original.tagName !== 'SPAN') target.replaceChildren(img);
      else target.replaceWith(img);
    } catch {
      const replacement = inert.createElement(picture || original.tagName === 'SPAN' ? 'span' : 'pre');
      replacement.textContent = source;
      target.replaceWith(replacement);
      fallback = true;
    }
  }
  // Generated preview markup is the only input. Its source annotations are not PDF metadata.
  copy.querySelectorAll('[data-source]').forEach(node => node.removeAttribute('data-source'));
  return { source: { html: copy.outerHTML, title, lang, images }, fallback };
}

export async function createSummaryPdf(article: HTMLElement, title: string, lang: string, signal: AbortSignal) {
  const { source, fallback } = await pdfSource(article, title, lang, signal);
  signal.throwIfAborted();
  const worker = new Worker(new URL('./summaryPdf.worker.ts', import.meta.url), { type: 'module' });
  let abort: () => void;
  try {
    const result = await new Promise<{ bytes: ArrayBuffer; missingGlyphs: boolean }>((resolve, reject) => {
      abort = () => reject(signal.reason);
      signal.addEventListener('abort', abort, { once: true });
      worker.onerror = () => reject(new Error('PDF worker failed'));
      worker.onmessageerror = () => reject(new Error('Invalid PDF worker response'));
      worker.onmessage = ({ data }) => {
        if (data?.bytes instanceof ArrayBuffer && data.bytes.byteLength) resolve(data); else reject(new Error('PDF layout failed'));
      };
      worker.postMessage(source, source.images.map(image => image.data.buffer));
    });
    return { blob: new Blob([result.bytes], { type: 'application/pdf' }), fallback, missingGlyphs: result.missingGlyphs };
  } finally {
    signal.removeEventListener('abort', abort!);
    worker.terminate();
  }
}
