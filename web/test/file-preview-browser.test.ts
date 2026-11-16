import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { meta, registration } from './focus-api-test-support';

const csp = "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:";
const data = (name: string) => readFileSync(resolve('test/fixtures/file-preview-data', name));
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-file-preview-'));
let server: ViteDevServer, browser: Browser, url: string;
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n', 'mermaid'] }, server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/test/fixtures/file-preview.html`;
  browser = await chromium.launch({ headless: true, ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

async function fixture(name: string, body: string | Buffer, run: (page: Page, calls: string[]) => Promise<void>, width = 1280) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [], calls: string[] = [], pdfResources: string[] = [], consoleErrors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (['error', 'warning'].includes(message.type())) consoleErrors.push(message.text()); });
  page.on('request', request => { if (/pdfjs-dist|filePreviewPdf|\/pdfjs\//.test(request.url())) pdfResources.push(request.url()); });
  await page.route('https://example.test/**', route => { calls.push(route.request().url()); return route.abort(); });
  await page.route('**/test/fixtures/file-preview.html?*', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), 'Content-Security-Policy': csp } });
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname; calls.push(path);
    if (path === '/api/meta') await route.fulfill({ json: meta });
    else if (path === '/api/client/register') await route.fulfill({ json: registration() });
    else if (path === '/api/files/info') await route.fulfill({ json: { path: `/work/${name}`, name, size: Buffer.byteLength(body) } });
    else if (path === '/api/files/download') await route.fulfill({ contentType: 'application/octet-stream', body });
    else await route.fulfill({ status: 404, json: {} });
  });
  try {
    await page.goto(`${url}?file=${encodeURIComponent(name)}`);
    await page.getByRole('button', { name: 'Open file', exact: true }).click();
    await page.getByRole('button', { name: 'Preview', exact: true }).waitFor();
    expect(calls.filter(path => path === '/api/files/download')).toHaveLength(0);
    expect(pdfResources).toHaveLength(0);
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await run(page, calls);
    expect(errors).toEqual([]);
    if (!name.endsWith('.pdf')) expect(pdfResources).toHaveLength(0);
    expect(calls.some(path => path.startsWith('https://example.test/'))).toBe(false);
  } catch (error) {
    const rich = await page.locator('.file-preview-markdown').first().innerHTML({ timeout: 500 }).catch(() => '');
    throw new Error(`${String(error)}\nBrowser errors: ${JSON.stringify(errors)}\nConsole: ${JSON.stringify(consoleErrors)}\nCalls: ${JSON.stringify(calls)}\nPage: ${(await page.locator('body').innerText()).slice(-2500)}\nRich view: ${rich.slice(-7000)}`);
  } finally { await page.close(); }
}

it.each(['gif', 'bmp', 'ico', 'avif'])('decodes and displays a real %s without altering it', async extension => {
  await fixture(`sample.${extension}`, data(`sample.${extension}`), async page => {
    await expect.poll(() => page.locator('.image-canvas img').evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBe(16);
    expect(await page.getByRole('button', { name: 'Source / text', exact: true }).count()).toBe(0);
  });
}, 30_000);

it('keeps SVG script and external images inert while preserving exact source and zoom', async () => {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="160"><rect width="320" height="160" fill="teal"/><script>window.svgExecuted=true;fetch("https://example.test/script")</script><image href="https://example.test/image.png" width="20" height="20"/></svg>';
  await fixture('diagram.svg', svg, async (page, calls) => {
    await expect.poll(() => page.locator('.image-canvas img').evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBe(320);
    expect(await page.evaluate(() => Reflect.get(window, 'svgExecuted'))).toBeUndefined();
    await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await page.getByRole('button', { name: 'Source / text', exact: true }).click();
    expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(svg);
    await page.getByRole('button', { name: 'Rendered view', exact: true }).click();
    await page.locator('.image-canvas img').waitFor();
    expect(calls.filter(path => path === '/api/files/download')).toHaveLength(1);
  }, 390);
}, 30_000);

it.each(['csv', 'tsv'])('pages the complete %s as literal cells and retains its source', async extension => {
  const delimiter = extension === 'csv' ? ',' : '\t';
  const source = ['id' + delimiter + 'value', '001' + delimiter + '"line 1\nline ""2"""',
    ...Array.from({ length: 55 }, (_, i) => `${i + 2}${delimiter}=1+1`)].join('\r\n');
  await fixture(`data.${extension}`, source, async (page, calls) => {
    await page.getByRole('cell', { name: '001', exact: true }).waitFor();
    expect(await page.getByRole('cell', { name: 'line 1\nline "2"', exact: true }).textContent()).toBe('line 1\nline "2"');
    expect(await page.locator('tbody tr').count()).toBe(50);
    await page.getByRole('button', { name: 'Next page', exact: true }).click();
    await page.getByRole('cell', { name: '56', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Source / text', exact: true }).click();
    // textarea normalizes CRLF for display; the reader/copy action retains it.
    expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(source.replaceAll('\r\n', '\n'));
    expect(calls.filter(path => path === '/api/files/download')).toHaveLength(1);
  }, 390);
}, 30_000);

it('expands JSON without rounding large numbers, losing duplicate keys or creating HTML', async () => {
  const source = '{"n":9007199254740993,"n":1e300,"s":"<img src=evil>","nested":[1,true,null]}';
  await fixture('data.json', source, async page => {
    await page.getByText('9007199254740993', { exact: true }).waitFor();
    expect(await page.locator('.json-key').filter({ hasText: '"n"' }).count()).toBe(2);
    await page.getByRole('button', { name: /"nested"/ }).click();
    await page.locator('.file-preview-json').getByText('true', { exact: true }).waitFor();
    expect(await page.locator('.file-preview-json img').count()).toBe(0);
    await page.getByRole('button', { name: 'Source / text', exact: true }).click();
    expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(source);
  });
}, 30_000);

it('highlights literal code with a source toggle and follows theme changes', async () => {
  const source = 'const answer: number = 42;\n// ```\n// <img src="https://example.test/code">';
  await fixture('app.ts', source, async page => {
    await page.locator('.file-preview-code pre span[style*="color"]').first().waitFor();
    expect(await page.locator('.file-preview-code img').count()).toBe(0);
    const light = await page.locator('.file-preview-code').evaluate(el => getComputedStyle(el).backgroundColor);
    await page.evaluate(() => { document.documentElement.dataset.colorScheme = 'dark'; });
    await expect.poll(() => page.locator('.file-preview-code').evaluate(el => getComputedStyle(el).backgroundColor)).not.toBe(light);
    await page.getByRole('button', { name: 'Source / text', exact: true }).click();
    expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(source);
  });
}, 45_000);

it('keeps rotated PDF text over the page and bounds very large pages at high zoom', async () => {
  await fixture('rotated.pdf', data('rotated.pdf'), async page => {
    await page.locator('.pdf-text-layer').getByText('PDF preview page 1', { exact: true }).waitFor();
    const layout = await page.locator('.pdf-sheet').evaluate(el => {
      const sheet = el.getBoundingClientRect(), text = el.querySelector('.pdf-text-layer span')!.getBoundingClientRect();
      return { wide: sheet.width > sheet.height, contained: text.left >= sheet.left && text.right <= sheet.right + 1 && text.top >= sheet.top && text.bottom <= sheet.bottom + 1 };
    });
    expect(layout).toEqual({ wide: true, contained: true });
  });
  await fixture('large-page.pdf', data('large-page.pdf'), async page => {
    await page.locator('.pdf-sheet:visible').waitFor();
    await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await expect.poll(() => page.locator('.pdf-sheet canvas').evaluate((el: HTMLCanvasElement) => el.width)).toBeGreaterThan(1000);
    const size = await page.locator('.pdf-sheet canvas').evaluate((el: HTMLCanvasElement) => ({ width: el.width, height: el.height }));
    expect(size.width * size.height).toBeLessThanOrEqual(12_000_000);
    expect(Math.max(size.width, size.height)).toBeLessThanOrEqual(8192);
  });
}, 45_000);

it('renders a standalone Mermaid diagram through the existing strict renderer', async () => {
  const source = 'flowchart LR\n  A[Start] --> B[Finish]';
  await fixture('diagram.mmd', source, async page => {
    await page.locator('.mermaid-preview-area svg').waitFor();
    expect(await page.locator('.md-mermaid').innerText()).toContain('Start');
    await page.getByRole('button', { name: 'Source / text', exact: true }).click();
    expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(source);
  });
}, 45_000);

it.each([1280, 390])('renders PDF pixels and selectable text with local assets, paging, zoom and teardown at %s px', async width => {
  await fixture('sample.pdf', data('sample.pdf'), async (page, calls) => {
    await page.locator('.pdf-text-layer').getByText('PDF preview page 1', { exact: true }).waitFor();
    const pixel = await page.locator('.pdf-sheet canvas').evaluate((el: HTMLCanvasElement) => [...el.getContext('2d')!.getImageData(el.width / 2, el.height * 0.7, 1, 1).data]);
    expect(pixel[2]).toBeGreaterThan(150); expect(pixel[0]).toBeLessThan(60);
    const before = await page.locator('.pdf-sheet canvas').evaluate((el: HTMLCanvasElement) => el.width);
    await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
    await expect.poll(() => page.locator('.pdf-sheet canvas').evaluate((el: HTMLCanvasElement) => el.width)).toBeGreaterThan(before);
    await page.getByRole('button', { name: 'Next page', exact: true }).click();
    await page.locator('.pdf-text-layer').getByText('PDF preview page 2', { exact: true }).waitFor();
    expect(await page.getByRole('spinbutton', { name: 'PDF page', exact: true }).inputValue()).toBe('2');
    await page.getByRole('button', { name: /^(Save as…|Download)$/ }).click();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect(await page.getByRole('spinbutton', { name: 'PDF page', exact: true }).inputValue()).toBe('2');
    expect(calls.filter(path => path === '/api/files/download')).toHaveLength(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole('button', { name: 'Refresh content', exact: true }).click();
    await page.locator('.pdf-text-layer').getByText('PDF preview page 1', { exact: true }).waitFor();
    expect(calls.filter(path => path === '/api/files/download')).toHaveLength(2);
    await page.getByRole('button', { name: 'Close preview', exact: true }).click();
    await expect.poll(() => page.workers().length).toBe(0);
  }, width);
}, 45_000);

it('uses the packaged JPEG 2000 JavaScript decoder under the unchanged CSP', async () => {
  await fixture('jpeg2000.pdf', data('jpeg2000.pdf'), async page => {
    await page.locator('.pdf-sheet:visible').waitFor();
    const pixel = await page.locator('.pdf-sheet canvas').evaluate((el: HTMLCanvasElement) => [...el.getContext('2d')!.getImageData(el.width / 2, el.height / 2, 1, 1).data]);
    expect(pixel[0]).toBeGreaterThan(230); expect(pixel[1]).toBeLessThan(25);
  });
}, 45_000);

it('opens encrypted PDFs only after a correct password and can close a pending password request', async () => {
  await fixture('encrypted.pdf', data('encrypted.pdf'), async page => {
    const password = page.getByLabel('PDF password', { exact: true });
    await password.fill('wrong');
    await page.getByRole('button', { name: 'Open PDF', exact: true }).click();
    await page.getByText('Incorrect password. Try again.', { exact: true }).waitFor();
    await password.fill('preview-password');
    await page.getByRole('button', { name: 'Open PDF', exact: true }).click();
    await page.locator('.pdf-text-layer').getByText('PDF preview page 1', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Refresh content', exact: true }).click();
    await password.waitFor();
    await page.getByRole('button', { name: 'Close preview', exact: true }).click();
    await expect.poll(() => page.workers().length).toBe(0);
  });
}, 45_000);

it.each([
  ['bad.json', '{"unfinished":', /invalid JSON/],
  ['bad.csv', '"unfinished', /invalid quoting/],
  ['bad.svg', '<svg>broken', /could not be displayed/],
  ['bad.pdf', 'This is not a PDF', /Could not display this PDF/],
])('reports invalid %s while keeping source or download available', async (name, source, message) => {
  await fixture(name as string, source as string, async page => {
    await page.getByText(message as RegExp).waitFor();
    expect(await page.getByRole('button', { name: /^(Save as…|Download)$/ }).count()).toBe(1);
    if (!(name as string).endsWith('.pdf')) expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(source);
  });
}, 30_000);
