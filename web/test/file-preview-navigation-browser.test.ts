import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';
import { meta, registration } from './focus-api-test-support';

const csp = "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:";
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-preview-navigation-'));
let server: ViteDevServer, browser: Browser, url: string;
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n', 'mermaid'] }, server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing address');
  url = `http://127.0.0.1:${address.port}/test/fixtures/file-preview.html?file=docs/catalog.md`;
  browser = await chromium.launch({ headless: true, ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

async function setup(page: Page) {
  page.setDefaultTimeout(15_000);
  const errors: string[] = [], reads: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const files = new Map<string, string | Buffer>([
    ['/work/docs/catalog.md', '# Catalog\n\n' + Array.from({ length: 65 }, (_, i) => `Paragraph ${i}. Read this directory on desktop and phone.\n\n`).join('')
      + '[Open chapter](nested/chapter.md#target)\n\n[Open PDF](sample.pdf)\n\n[Missing file](missing.md)\n\n[Unsupported file](archive.zip)\n\nEND CATALOG'],
    ['/work/docs/nested/chapter.md', '# Chapter\n\n' + 'Chapter paragraph.\n\n'.repeat(55) + '## Target\n\n'
      + 'Before image.\n\n'.repeat(20) + '[Open image](../sample.gif)\n\n' + 'After target.\n\n'.repeat(20)],
    ['/work/docs/sample.gif', readFileSync(resolve('test/fixtures/file-preview-data/sample.gif'))],
    ['/work/docs/sample.pdf', readFileSync(resolve('test/fixtures/file-preview-data/sample.pdf'))],
    ['/work/docs/archive.zip', 'not previewable'],
  ]);
  await page.route('**/test/fixtures/file-preview.html?*', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), 'Content-Security-Policy': csp } });
  });
  await page.route('**/api/**', async route => {
    const u = new URL(route.request().url());
    if (u.pathname === '/api/meta') { await route.fulfill({ json: meta }); return; }
    if (u.pathname === '/api/client/register') { await route.fulfill({ json: registration() }); return; }
    const path = resolve(u.searchParams.get('cwd') || '/', u.searchParams.get('path') || '');
    const body = files.get(path);
    if (body === undefined) { await route.fulfill({ status: 404, json: { error: { code: 'file_not_found', message: 'missing' } } }); return; }
    if (u.pathname === '/api/files/info') await route.fulfill({ json: { path, name: basename(path), size: Buffer.byteLength(body) } });
    else if (u.pathname === '/api/files/download') { reads.push(path); await route.fulfill({ contentType: 'application/octet-stream', body }); }
    else await route.fulfill({ status: 404, json: {} });
  });
  await page.goto(url);
  await page.getByRole('button', { name: 'Open file', exact: true }).click();
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  await page.getByText('END CATALOG', { exact: true }).waitFor();
  await page.evaluate(async () => { await document.fonts.ready; await new Promise<void>(resolve => requestAnimationFrame(() => resolve())); });
  return { errors, reads, files };
}
const back = (page: Page) => page.getByRole('button', { name: 'Back to previous file', exact: true });
// The renderer gives links a destination-based aria-label; match their visible caption.
const link = (page: Page, label: string) => page.getByRole('link').filter({ hasText: label });

it.each([1280, 1920])('maximizes the preview trail while preserving reading state and normal file forms at width %i', async width => {
  const height = width === 1280 ? 900 : 1080;
  const page = await browser.newPage({ viewport: { width, height } });
  try {
    const { errors, reads } = await setup(page);
    const dialog = page.getByRole('dialog');
    await dialog.evaluate(async el => { await Promise.all(el.getAnimations().map(animation => animation.finished)); });
    const initial = await dialog.boundingBox();
    expect(initial!.width).toBeGreaterThan(1000);
    expect(initial!.width).toBeLessThan(width);
    expect(initial!.height).toBeGreaterThan(680);
    const scroller = page.locator('.file-preview-markdown');
    await scroller.evaluate(el => { el.scrollTop = 600; });
    const content = await scroller.elementHandle();
    await page.getByRole('button', { name: 'Maximize preview', exact: true }).click();
    await expect.poll(async () => (await dialog.boundingBox())!.width).toBe(width);
    expect((await dialog.boundingBox())!.height).toBe(height);
    expect(await content!.evaluate(el => el.isConnected && el.scrollTop === 600)).toBe(true);
    expect(await page.locator('.file-preview-prose').evaluate(el => el.clientWidth)).toBeLessThanOrEqual(760);
    expect(await page.evaluate(() => document.fullscreenElement)).toBeNull();
    expect(reads).toHaveLength(1);
    await page.getByRole('button', { name: 'Restore preview size', exact: true }).click();
    await expect.poll(async () => (await dialog.boundingBox())!.width).toBe(initial!.width);
    expect(await content!.evaluate(el => el.isConnected && el.scrollTop === 600)).toBe(true);
    await page.getByRole('button', { name: 'Maximize preview', exact: true }).click();

    // A download form stays compact; its X returns to the same maximized preview.
    await page.getByRole('button', { name: /^(Save as…|Download)$/ }).click();
    expect((await dialog.boundingBox())!.width).toBeLessThan(500);
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('button', { name: 'Restore preview size', exact: true }).waitFor();
    expect(await content!.evaluate(el => el.isConnected && el.scrollTop === 600)).toBe(true);
    expect(reads).toHaveLength(1);

    await link(page, 'Open chapter').click();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.getByRole('heading', { name: 'Catalog', exact: true }).waitFor();
    expect((await dialog.boundingBox())!.width).toBe(width);
    await link(page, 'Open chapter').click();
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await page.getByRole('heading', { name: 'Chapter', exact: true }).waitFor();
    expect((await dialog.boundingBox())!.width).toBe(width);
    await back(page).click();
    await page.getByRole('heading', { name: 'Catalog', exact: true }).waitFor();
    expect((await dialog.boundingBox())!.width).toBe(width);

    // Narrow layouts fill the page automatically, without a redundant maximize control.
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(async () => (await dialog.boundingBox())!.width).toBe(390);
    await page.getByRole('button', { name: 'Restore preview size', exact: true }).waitFor({ state: 'detached' });
    await page.setViewportSize({ width, height });
    await page.getByRole('button', { name: 'Restore preview size', exact: true }).waitFor();

    // An information form opened from a link still closes the entire trail with X.
    await link(page, 'Open chapter').click();
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    expect(await dialog.count()).toBe(0);
    await page.getByRole('button', { name: 'Open file', exact: true }).click();
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await page.getByRole('heading', { name: 'Catalog', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Maximize preview', exact: true }).waitFor();
    expect((await dialog.boundingBox())!.width).toBeLessThan(width);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 45_000);

it.each([1280, 390])('returns through nested files to the same directory reading position at width %i', async width => {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  try {
    const { errors, reads, files } = await setup(page);
    expect(await back(page).count()).toBe(0);
    const initialHistory = await page.evaluate(() => history.length);
    await link(page, 'Open chapter').scrollIntoViewIfNeeded();
    const top = await page.locator('.file-preview-markdown').evaluate(el => el.scrollTop);
    expect(top).toBeGreaterThan(1000);
    await link(page, 'Open chapter').click();
    expect(reads).toEqual(['/work/docs/catalog.md']);
    await page.getByRole('button', { name: 'Cancel', exact: true }).waitFor();
    expect(await page.getByRole('button', { name: 'Cancel', exact: true }).isVisible()).toBe(true);
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await page.getByRole('heading', { name: 'Target', exact: true }).waitFor();
    await link(page, 'Open image').scrollIntoViewIfNeeded();
    const chapterTop = await page.locator('.file-preview-markdown').evaluate(el => el.scrollTop);
    await link(page, 'Open image').click();
    expect(await page.locator('.file-preview-markdown').count()).toBe(0);
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await expect.poll(() => page.locator('.image-canvas img').evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBe(16);
    await back(page).click();
    await page.getByRole('heading', { name: 'Chapter', exact: true }).waitFor();
    await expect.poll(() => page.locator('.file-preview-markdown').evaluate(el => el.scrollTop)).toBeCloseTo(chapterTop, 0);
    expect(await page.locator('.file-download-form').count()).toBe(0);
    files.set('/work/docs/catalog.md', String(files.get('/work/docs/catalog.md')).replace('END CATALOG', 'NEW CATALOG'));
    await back(page).click();
    await page.getByText('NEW CATALOG', { exact: true }).waitFor();
    await expect.poll(() => page.locator('.file-preview-markdown').evaluate(el => el.scrollTop)).toBeCloseTo(top, 0);
    expect(await back(page).count()).toBe(0);
    expect(reads.filter(path => path.endsWith('catalog.md'))).toHaveLength(2);
    expect(await page.evaluate(() => history.length)).toBe(initialHistory);
    // Scroll restoration must yield as soon as the reader resumes scrolling.
    await page.locator('.file-preview-markdown').hover();
    await page.mouse.wheel(0, -600);
    await expect.poll(() => page.locator('.file-preview-markdown').evaluate(el => el.scrollTop)).toBeLessThan(top - 100);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 45_000);

it.each(['Missing file', 'Unsupported file'])('cancels %s information and returns without fetching its body', async label => {
  const page = await browser.newPage();
  try {
    const { errors, reads } = await setup(page);
    await link(page, label).click();
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.getByRole('heading', { name: 'Catalog', exact: true }).waitFor();
    expect(reads).toEqual(['/work/docs/catalog.md', '/work/docs/catalog.md']);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 30_000);

it('releases a PDF worker on Back and closes the full trail with X before opening a new root', async () => {
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  try {
    const { errors } = await setup(page);
    await link(page, 'Open PDF').click();
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await page.locator('.pdf-text-layer span').first().waitFor();
    await expect.poll(() => page.workers().length).toBeGreaterThan(0);
    await back(page).click();
    await page.getByRole('heading', { name: 'Catalog', exact: true }).waitFor();
    await expect.poll(() => page.workers().length).toBe(0);
    await link(page, 'Open chapter').click();
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await page.getByRole('heading', { name: 'Chapter', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Close preview', exact: true }).click();
    expect(await page.locator('.ui-dialog').count()).toBe(0);
    await expect.poll(() => page.getByRole('button', { name: 'Open file', exact: true }).evaluate(el => el === document.activeElement)).toBe(true);
    await page.getByRole('button', { name: 'Open file', exact: true }).click();
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    await page.getByRole('heading', { name: 'Catalog', exact: true }).waitFor();
    expect(await back(page).count()).toBe(0);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}, 45_000);
