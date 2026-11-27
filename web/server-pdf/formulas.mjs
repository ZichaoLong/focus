import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
import 'mathjax-full/js/input/tex/ams/AmsConfiguration.js';
import 'mathjax-full/js/input/tex/boldsymbol/BoldsymbolConfiguration.js';
import 'mathjax-full/js/input/tex/newcommand/NewcommandConfiguration.js';

// All mathematical glyphs and rules travel as paths in a complete SVG image.
// The PDF engine can embed it without interpreting browser-specific KaTeX CSS.
export function formulaImages(images) {
  const adaptor = liteAdaptor();
  RegisterHTMLHandler(adaptor);
  const document = mathjax.document('', {
    InputJax: new TeX({ packages: ['base', 'ams', 'boldsymbol', 'newcommand'], maxMacros: 1000,
      formatError: (_jax, error) => { throw error; } }),
    OutputJax: new SVG({ fontCache: 'none' }),
  });
  const cache = new Map();
  let size = 0;
  return (tex, block) => {
    const key = (block ? 'block:' : 'inline:') + tex;
    if (cache.has(key)) return cache.get(key);
    const root = adaptor.firstChild(document.convert(tex, { display: block }));
    const [, y, w, h] = adaptor.getAttribute(root, 'viewBox').split(/\s+/).map(Number);
    if (!(w > 0 && h > 0) || size >= 48 * 1024 * 1024) throw new Error('Formula image limit');
    const scale = Math.min(0.016, 640 / w, 880 / h);
    const width = w * scale, height = h * scale;
    adaptor.setAttribute(root, 'width', String(width));
    adaptor.setAttribute(root, 'height', String(height));
    const svg = adaptor.outerHTML(root);
    if (svg.includes('<text') || svg.length > 2 * 1024 * 1024) throw new Error('Formula needs external glyphs');
    const src = 'formula-' + images.length + '.svg';
    const data = Buffer.from(svg);
    images.push({ src, data });
    size += data.length;
    const img = '<img src="' + src + '" width="' + width + '" height="' + height
      + '" style="vertical-align:' + (-(y + h) * scale) + 'px">';
    const html = block ? '<p style="text-align:center">' + img + '</p>' : img;
    cache.set(key, html);
    return html;
  };
}
