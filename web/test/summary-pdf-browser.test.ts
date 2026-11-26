import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { getDocument, OPS } from 'pdfjs-dist/legacy/build/pdf.mjs';

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

it('saves the edited, complete preview as searchable paginated PDF without invoking print', async () => {
  const context = await browser.newContext({ locale: 'en-US' });
  try {
    const parent = await context.newPage();
    await parent.goto(origin + '/focus-connect.txt');
    const popup = context.waitForEvent('page');
    const markdown = '# Codex conversation summary\n\n中文正文 **粗体**\n\nInline \\(\\frac{a}{b}\\) follows.\n\n'
      + '```mermaid\ngraph TD\n A[Input] --> B[Output]\n```\n\n'
      + '```ts\n' + Array.from({ length: 130 }, (_, i) => `code-line-${i};`).join('\n') + '\n```\n\n'
      + '| 中文表头 | Value |\n| --- | --- |\n' + Array.from({ length: 100 }, (_, i) => `| row-${i} | 中文 |`).join('\n') + '\n\nEnd of selection.';
    await parent.evaluate(markdown => {
      const token = 'print-pdf-integration';
      window.addEventListener('message', ({ data, source, origin }) => {
        if (origin === location.origin && data?.ready && data.token === token) (source as Window).postMessage({
          channel: 'focus-summary-print', token, markdown, documentTitle: 'Old title', suggestedFilename: 'selected.pdf',
        }, origin);
      });
      window.open('/?print=summary#' + token);
    }, markdown);
    const page = await popup;
    const requests: string[] = [];
    page.on('request', request => requests.push(request.url()));
    await page.locator('.summary-print[data-status="ready"]').waitFor({ timeout: 45_000 });
    await page.locator('#summary-document-title').fill('新的标题');
    await page.evaluate(() => {
      window.print = () => { document.body.dataset.printed = 'yes'; };
      Object.defineProperty(window, 'showSaveFilePicker', { configurable: true, value: () => Promise.reject(new DOMException('Cancelled', 'AbortError')) });
    });
    const save = page.locator('button.save-pdf');
    await save.click();
    await expect.poll(() => save.isEnabled()).toBe(true);
    expect(requests.some(url => /takumi_pdf_wasm|noto-sans-sc.*woff2|summaryPdf\.worker/.test(url))).toBe(false);
    await page.evaluate(() => { Object.defineProperty(window, 'showSaveFilePicker', { value: undefined }); });
    const result = page.waitForEvent('download', { timeout: 45_000 });
    await save.click();
    const download = await result;
    expect(download.suggestedFilename()).toBe('selected.pdf');
    const task = getDocument({ data: new Uint8Array(readFileSync((await download.path())!)), useSystemFonts: false });
    try {
      const pdf = await task.promise;
      expect(pdf.numPages).toBeGreaterThan(3);
      const pages: string[] = [];
      let pictures = 0;
      for (let i = 1; i <= pdf.numPages; i++) {
        const page = await pdf.getPage(i);
        pages.push((await page.getTextContent()).items.map(item => 'str' in item ? item.str : '').join(''));
        pictures += (await page.getOperatorList()).fnArray.filter(op => op === OPS.paintImageXObject || op === OPS.paintInlineImageXObject).length;
      }
      const text = pages.join('\n');
      for (const part of ['新的标题', '中文正文', '粗体', 'code-line-0;', 'code-line-129;', 'row-99', 'End of selection.']) expect(text).toContain(part);
      expect(text).not.toContain('Old title');
      expect(pages.filter(text => text.includes('中文表头')).length).toBeGreaterThan(1);
      expect(pictures).toBeGreaterThanOrEqual(2);
    } finally { await task.destroy(); }
    expect(await page.locator('.summary-pdf-status').innerText()).toContain('download');
    // Uncovered glyphs must not prevent saving the rest of a document.
    await page.locator('#summary-document-title').fill('Missing glyph \u{10FFFD}');
    const fallbackDownload = page.waitForEvent('download');
    await save.click();
    expect((await fallbackDownload).suggestedFilename()).toBe('selected.pdf');
    expect(await page.locator('.summary-pdf-status').innerText()).toContain('placeholders');
    expect(await page.locator('body').getAttribute('data-printed')).toBe(null);
    await page.locator('button.system-print').click();
    expect(await page.locator('body').getAttribute('data-printed')).toBe('yes');
  } finally { await context.close(); }
}, 100_000);
