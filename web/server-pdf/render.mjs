import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import init, { render } from 'takumi-pdf/no-init';
import { renderSummaryPrintMarkdown } from '../src/focus/summaryPrintMarkdown.ts';
import { summaryDocumentBody } from '../src/focus/summaryDocumentTitle.ts';
import { formulaImages } from './formulas.mjs';
import { printWithBrowser } from './browser.mjs';

const asset = (path) => fileURLToPath(new URL(path, import.meta.url));
const input = JSON.parse(readFileSync(0, 'utf8'));
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const progress = (phase, data = {}) => console.log(JSON.stringify({ phase, ...data }));
const warnings = new Map();
function warn(kind, round = 0, code = '') {
  const key = [kind, round, code].join(':');
  if (warnings.has(key)) warnings.get(key).count++;
  else if (warnings.size < 100) warnings.set(key, { kind, round, code, count: 1 });
  else warnings.set('more', { kind: 'more', count: (warnings.get('more')?.count || 0) + 1 });
}
const source = summaryDocumentBody(input.markdown);
const raw = () => source.split('\n').map(line => '<pre>' + (escape(line) || ' ') + '</pre>').join('');
const wrap = body => '<article class="summary-print-content"><h1>' + escape(input.title) + '</h1>' + body + '</article>';
function renderBody(formula) {
  try {
    return renderSummaryPrintMarkdown(source, { server: true, formula, warning: warn,
      progress(done, total) { if (total && (!done || done % 10 === 0 || done === total)) progress('formulas', { done, total }); },
    }).html;
  } catch { warn('source'); return raw(); }
}

const fontInfo = JSON.parse(readFileSync(asset('fonts.json'), 'utf8'));
const fonts = fontInfo.map(({ name, key, ranges, weight, style }) => ({
  name, key, weight, style, data: () => readFileSync(asset('fonts/' + key)),
  ...(ranges && { unicodeRange: ranges.split(',').map(spec => {
    const [a, b] = spec.slice(2).split('-').map(hex => parseInt(hex, 16)); return [a, b ?? a];
  }) }),
}));
const families = ['Focus Inter', 'Focus Sans', 'Focus Symbols', 'Focus Emoji'];
const css = [readFileSync(asset('katex.css'), 'utf8'), readFileSync(asset('paper.css'), 'utf8'),
  '.summary-print-content{max-width:none;margin:0;padding:0;font:14px/1.55 "Focus Inter","Focus Sans","Focus Symbols","Focus Emoji";color:#171717}' +
  'pre,code{font-family:"Focus Mono","Focus Sans","Focus Symbols",monospace} pre,td,th,p{overflow-wrap:anywhere} pre{white-space:pre-wrap} img,figure svg{max-width:100%;height:auto}'];

function browserHtml(body) {
  const points = [...new Set(input.title + source)].map(c => c.codePointAt(0));
  const rules = fonts.flatMap(font => {
    if (font.unicodeRange && !font.unicodeRange.some(([a,b]) => points.some(c => a <= c && c <= b))) return [];
    const data = font.data().toString('base64');
    return '@font-face{font-family:"' + font.name + '";src:url(data:font/' + (font.key.endsWith('.ttf') ? 'ttf' : 'woff2')
      + ';base64,' + data + ');font-weight:' + (font.weight || '100 900') + ';font-style:' + (font.style || 'normal') + ';'
      + (font.unicodeRange ? 'unicode-range:' + fontInfo.find(f => f.key === font.key).ranges + ';' : '') + '}';
  });
  return '<!doctype html><meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:; font-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' +
    '<title>' + escape(input.title) + '</title><style>' + rules.join('\n') + css.join('\n') +
    '@page{size:A4;margin:15mm}</style>' + wrap(body);
}

let bytes, engine = 'basic';
if (input.browser) {
  progress('browser');
  try {
    const printed = await printWithBrowser(input.browser, browserHtml(renderBody()), asset('mermaid.js'), input.profile);
    bytes = printed.bytes;
    for (const warning of printed.warnings) warn(warning.kind, warning.round);
    engine = 'browser';
  } catch { warnings.clear(); progress('browser_unavailable'); warn('browser'); }
}
if (!bytes) {
  if (input.browserFailed) warn('browser');
  const images = [];
  let body = renderBody(formulaImages(images));
  progress('layout');
  await init({ module_or_path: readFileSync(asset('render.wasm')) });
  const options = { size: 'a4', margin: 60, lang: input.lang, css, metadata: { title: input.title },
    fonts, fontFamilies: families };
  for (const diagram of body.matchAll(/<pre class="summary-mermaid" data-round="(\d+)">/g)) warn('diagram', Number(diagram[1]));
  function rows(table, round) {
    const all = [...table.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map(row => [...row[1].matchAll(/<t[dh](?:\s[^>]*)?>([\s\S]*?)<\/t[dh]>/g)].map(c => c[1]));
    if (!all.some(cells => cells.length > 8 || cells.some(cell => cell.length > 3000))) return table;
    warn('table', Number(round));
    if (all.length === 1) return '<p>' + all[0].join('<br>') + '</p>';
    return all.slice(1).map(cells => '<p>' + cells.map((cell,i) => (all[0][i] || String(i+1)) + ' — ' + cell).join('<br>') + '</p>').join('');
  }
  body = body.replace(/<table data-round="(\d+)">[\s\S]*?<\/table>/g, rows);
  body = body.replace(/src="data:image\/(png|jpeg);base64,([a-z0-9+/=]+)"/gi, (_all, format, data) => {
    const src = 'embedded-' + images.length + '.' + format;
    images.push({ src, data: Buffer.from(data, 'base64') }); return 'src="' + src + '"';
  });
  async function typeset(html, images) {
    for (let retry = 0; retry < 16; retry++) {
      try { return await render(html, { ...options, images }); }
      catch (error) {
        const missing = /No font the text can use draws .*?\(U\+([0-9A-F]+)\)/is.exec(String(error));
        if (!missing) throw error;
        const character = String.fromCodePoint(parseInt(missing[1],16));
        if (!html.includes(character)) throw error;
        let round = 0, found = false;
        if (input.title.includes(character)) { warn('glyph', 0, 'U+' + missing[1]); found = true; }
        for (const line of source.split('\n')) {
          const heading = /^## (\d+)\.\s/.exec(line);
          if (heading) round = Number(heading[1]);
          if (line.includes(character)) { warn('glyph', round, 'U+' + missing[1]); found = true; }
        }
        if (!found) warn('glyph', 0, 'U+' + missing[1]);
        html = html.replaceAll(character, '[U+' + missing[1] + ']');
      }
    }
    throw new Error('Font coverage exhausted');
  }
  try { bytes = await typeset(wrap(body), images); }
  catch {
    warn('source');
    try { bytes = await typeset(wrap(raw()), []); }
    catch {
      warn('unicode');
      const plain = wrap(raw()).replace(/[^\x00-\x7F]/gu, c => '[U+' + c.codePointAt(0).toString(16).toUpperCase() + ']');
      bytes = await render(plain, { ...options, images: [] });
    }
  }
}
if (bytes.length > 96 * 1024 * 1024) throw new Error('PDF output size limit');
writeFileSync(input.output, bytes, { mode: 0o600 });
progress('complete', { engine, warnings: [...warnings.values()] });
