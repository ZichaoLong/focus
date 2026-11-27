import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';

import { spawnSync } from 'node:child_process';
import { summaryPdfAssets } from '../scripts/build-summary-pdf.mjs';

let server: ViteDevServer, browser: Browser, origin: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-summary-pdf-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', server: { host: '127.0.0.1', port: 0 },
    optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n', 'katex', 'markstream-vue', 'mermaid'] } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  origin = `http://127.0.0.1:${address.port}`;
  browser = await chromium.launch({ headless: true, executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

it('offers a server download after a silent print receipt and reconnects without changing the selection', async () => {
  const context = await browser.newContext({ locale: 'en-US' });
  try {
    const parent = await context.newPage();
    await parent.goto(origin + '/focus-connect.txt');
    const popup = context.waitForEvent('page');
    await parent.evaluate(() => {
      const token = 'print-handoff';
      window.addEventListener('message', ({ data, source, origin }) => {
        if (origin === location.origin && data?.ready && data.token === token) (source as Window).postMessage({
          channel: 'focus-summary-print', token, markdown: 'Original selection', documentTitle: 'Old title',
          suggestedFilename: 'selected.pdf', pdfPreview: { id: 'a'.repeat(32), csrf: 'test-receipt' },
        }, origin);
      });
      window.open('/?print=summary#' + token);
    });
    const page = await popup;
    await page.locator('.summary-print[data-status="ready"]').waitFor();
    expect(await page.locator('.summary-print-actions h1').innerText()).toBe('Print preview');
    expect(await page.locator('.system-print').innerText()).toBe('Print');
    const save = page.locator('button.save-pdf');
    expect(await save.count()).toBe(0);
    const ids: string[] = [];
    let poll = 0;
    await page.route('**/pdf-previews/**', async route => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      ids.push(path.split('/jobs/')[1]!.split('/')[0]!);
      if (req.method() === 'POST') {
        expect(req.postDataJSON()).toEqual({ title: '新的标题', lang: 'en' });
        expect(req.headers()['x-focus-web-csrf']).toBe('test-receipt');
        if (ids.length === 1) return route.abort('failed');
        return route.fulfill({ json: { phase: 'queued', done: 0, total: 0, warnings: [] } });
      }
      if (path.endsWith('/file')) return route.fulfill({ contentType: 'application/pdf', body: '%PDF-authorized' });
      return route.fulfill({ json: ++poll === 1 ? { phase: 'formulas', done: 3, total: 8, warnings: [] } : {
        phase: 'ready', done: 0, total: 0, engine: 'basic', warnings: [{ kind: 'glyph', round: 2, code: 'U+10FFFD' }],
      } });
    });
    await page.evaluate(() => {
      window.print = () => {};
      Object.defineProperty(window, 'showSaveFilePicker', { configurable: true,
        value: () => Promise.reject(new DOMException('Cancelled', 'AbortError')) });
    });
    await page.locator('#summary-document-title').fill('新的标题');
    await page.locator('.system-print').click();
    await save.waitFor();
    expect(await page.locator('.summary-print-offer').innerText()).toContain('may not support system printing');
    expect(await save.innerText()).toBe('Try downloading the PDF');
    await page.evaluate(() => dispatchEvent(new Event('afterprint')));
    await page.getByText('Need a server copy?', { exact: false }).waitFor();
    expect(await save.innerText()).toBe('Download PDF');
    await save.click();
    await expect.poll(() => save.isEnabled()).toBe(true);
    expect(ids).toHaveLength(0);
    await page.evaluate(() => { Object.defineProperty(window, 'showSaveFilePicker', { value: undefined }); });
    const result = page.waitForEvent('download');
    await save.click();
    await page.getByText('Typesetting formulas (3/8)', { exact: false }).waitFor();
    const file = await result;
    expect(file.suggestedFilename()).toBe('selected.pdf');
    expect(readFileSync((await file.path())!, 'utf8')).toBe('%PDF-authorized');
    expect(ids.length).toBe(5);
    expect(new Set(ids).size).toBe(1);
    expect(await page.locator('.summary-pdf-status').innerText()).toContain('browser for download');
    expect(await page.locator('.summary-pdf-warnings').innerText()).toContain('U+10FFFD');
    // A real panel returning (including Cancel) keeps the print action available.
    await page.evaluate(() => { window.print = () => dispatchEvent(new Event('afterprint')); });
    await page.locator('.system-print').click();
    await save.waitFor();
    expect(await page.locator('.summary-print-offer').innerText()).toContain('Need a server copy');
    expect(await save.innerText()).toBe('Download PDF');
    expect(await page.locator('#summary-document-title').inputValue()).toBe('新的标题');
  } finally { await context.close(); }
}, 60_000);

it('prints complete multi-page PDFs with and without a usable server browser', async () => {
  const folder = join(cacheDir, 'server');
  await summaryPdfAssets((name: string, data: Uint8Array | string) => {
    const path = join(folder, name);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, data);
  });
  // CI Chromium uses Playwright’s isolated unsigned test binary. Production retains the OS sandbox.
  const binary = process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE || chromium.executablePath();
  const testBrowser = join(cacheDir, 'test-browser');
  writeFileSync(testBrowser, '#!/bin/sh\nexec "$PDF_TEST_BROWSER" --no-sandbox "$@"\n', { mode: 0o700 });
  const markdown = '# Codex conversation summary\n\n## 3. Selected turn\n\n### Assistant\n\n中文正文 10⁻³\n\n'
    + 'radical-start\n\n\\[\n\\sqrt{a}\n\\]\n\nradical-end\n\n\\[\na\n\\]\n\nliteral-end\n\n'
    + 'Inline \\(x^{10}\\) and \\(\\frac{z+1}{q+2}\\).\n\n'
    + '```mermaid\ngraph TD\n A[Input] --> B[Output]\n```\n\n'
    + '```ts\n' + Array.from({ length: 130 }, (_, i) => 'code-line-' + i).join('\n') + '\n```\n\n'
    + '| 中文表头 | Value |\n| --- | --- |\n' + Array.from({ length: 100 }, (_, i) => '| row-' + i + ' | 中文 |').join('\n')
    + '\n\n![remote](https://example.invalid/private)\n\nEnd of selection.';
  const stalled = join(cacheDir, 'stalled-browser');
  writeFileSync(stalled, '#!/bin/sh\nexec sleep 60\n', { mode: 0o700 });
  for (const mode of ['none', 'browser', 'broken', 'timeout']) {
    const output = join(cacheDir, mode + '.pdf');
    const proc = spawnSync(process.execPath, [join(folder, 'render.mjs')], {
      env: { PATH: process.env.PATH, HOME: cacheDir, PDF_TEST_BROWSER: binary },
      input: JSON.stringify({ markdown, title: '新的标题', lang: 'zh-CN', output,
        profile: join(cacheDir, 'profile-' + mode), browser: mode === 'none' ? '' : mode === 'browser' ? testBrowser : mode === 'timeout' ? stalled : join(folder, 'removed') }),
      encoding: 'utf8', timeout: 60_000,
    });
    expect(proc.status, proc.stderr.slice(-1000)).toBe(0);
    const events = proc.stdout.trim().split('\n').filter(s => s.startsWith('{"phase":')).map(line => JSON.parse(line));
    const result = events.at(-1);
    expect(result.engine).toBe(mode === 'browser' ? 'browser' : 'basic');
    expect(result.warnings).toContainEqual(expect.objectContaining({ kind: 'image', round: 3 }));
    expect(result.warnings.some((w: { kind: string }) => w.kind === 'formula')).toBe(false);
    if (mode !== 'browser') expect(result.warnings).toContainEqual(expect.objectContaining({ kind: 'diagram', round: 3 }));
    if (mode === 'broken' || mode === 'timeout') expect(result.warnings).toContainEqual(expect.objectContaining({ kind: 'browser' }));
    expect(events).toContainEqual({ phase: 'formulas', done: 4, total: 4 });
    const task = getDocument({ data: new Uint8Array(readFileSync(output)), useSystemFonts: false });
    try {
      const pdf = await task.promise;
      const text: string[] = [];
      expect(pdf.numPages).toBeGreaterThan(3);
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        const words = (await page.getTextContent()).items.filter(item => 'str' in item);
        text.push(words.map(item => item.str).join(''));
        if (i === 1) {
          const viewport = page.getViewport({ scale: 2 });
          const surface = pdf.canvasFactory.create(Math.ceil(viewport.width), Math.ceil(viewport.height));
          await page.render({ canvas: surface.canvas, viewport }).promise;
          const bitmap = surface.context.getImageData(0, 0, surface.canvas.width, surface.canvas.height);
          function formulaWidth(start: string, end: string) {
            const baseline = (s: string) => viewport.convertToViewportPoint(0, words.find(w => w.str === s)!.transform[5])[1]!;
            let left = bitmap.width, right = 0;
            for (let y = Math.ceil(baseline(start)); y < baseline(end); y++) {
              for (let x = Math.floor(bitmap.width / 4); x < bitmap.width * .75; x++) {
                if (bitmap.data[(y * bitmap.width + x) * 4]! < 140) { left = Math.min(left, x); right = Math.max(right, x); }
              }
            }
            return right - left;
          }
          const literal = formulaWidth('radical-end', 'literal-end');
          expect(literal).toBeGreaterThan(3);
          expect(formulaWidth('radical-start', 'radical-end'), mode + ' radical ink / literal width ' + literal).toBeGreaterThan(literal * 1.45);
          pdf.canvasFactory.destroy(surface);
        }
      }
      const whole = text.join('\n');
      for (const part of ['新的标题', '中文正文', '10⁻³', 'code-line-0', 'code-line-129', 'row-99', 'End of selection.']) expect(whole).toContain(part);
    } finally { await task.destroy(); }
  }
  const output = join(cacheDir, 'warnings.pdf');
  const wide = (s: string) => '| ' + Array.from({ length: 10 }, (_, i) => s + i).join(' | ') + ' |';
  const problematic = '## 7. Selection\n\nMissing \u{10fffd} and \\(\\notacommand{a}\\)\n\n'
    + wide('Field') + '\n|' + ' --- |'.repeat(10) + '\n' + wide('Data') + '\n\nLast paragraph';
  const warningRun = spawnSync(process.execPath, [join(folder, 'render.mjs')], {
    env: { PATH: '', HOME: cacheDir }, encoding: 'utf8', timeout: 40_000,
    input: JSON.stringify({ markdown: problematic, title: 'Known limitations', lang: 'en', output, browser: '' }),
  });
  expect(warningRun.status, warningRun.stderr).toBe(0);
  const warnings = JSON.parse(warningRun.stdout.trim().split('\n').at(-1)!).warnings;
  for (const expected of [{ kind: 'table', round: 7 }, { kind: 'formula', round: 7 }, { kind: 'glyph', round: 7, code: 'U+10FFFD' }]) {
    expect(warnings).toContainEqual(expect.objectContaining(expected));
  }
  const warningPdf = getDocument({ data: new Uint8Array(readFileSync(output)) });
  try {
    const first = await (await warningPdf.promise).getPage(1);
    const text = (await first.getTextContent()).items.map(w => 'str' in w ? w.str : '').join('');
    for (const value of ['Data9', 'Field9', 'Last paragraph', 'U+10FFFD', 'notacommand']) expect(text).toContain(value);
  } finally { await warningPdf.destroy(); }
}, 150_000);
