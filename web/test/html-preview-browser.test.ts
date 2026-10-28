import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { existsSync, mkdtempSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { meta, registration } from './focus-api-test-support';

const root = resolve('..');
const python = process.env.FOCUS_TEST_PYTHON ?? (existsSync(join(root, '.venv/bin/python')) ? join(root, '.venv/bin/python') : 'python3');
const shell = JSON.parse(execFileSync(python, ['-c', 'import json; from bot.web_runtime.html_preview import HTML_PREVIEW_DOCUMENT, HTML_PREVIEW_CSP; print(json.dumps({"html":HTML_PREVIEW_DOCUMENT,"csp":HTML_PREVIEW_CSP}))'], { cwd: root, encoding: 'utf8' })) as { html: string; csp: string };
const parentCsp = "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:";
const report = `<!doctype html><html><head><meta charset="utf-8"><style>body{font:20px sans-serif;margin:16px}svg{width:80%;max-height:180px}dialog{background:white}</style></head><body>
<h1>Embedded report</h1><svg viewBox="0 0 200 80"><circle cx="40" cy="40" r="30" fill="teal"/><path d="M70 40L170 40" stroke="navy"/></svg>
<p id="position">1</p><button id="next">Next step</button><button id="notes">Notes</button><button id="fullscreen">Report full screen</button>
<dialog id="notes-dialog"><a id="ref" href="../../notes/source%20%E4%B8%AD%E6%96%87.md#2-章节" target="_blank">Read source</a><button id="close">Close notes</button></dialog>
<script>let step=1;document.getElementById('next').onclick=()=>{document.getElementById('position').textContent=String(++step);history.replaceState(null,'','#'+step+'.1')};
document.getElementById('notes').onclick=()=>document.getElementById('notes-dialog').showModal();document.getElementById('close').onclick=()=>document.getElementById('notes-dialog').close();
document.getElementById('fullscreen').onclick=()=>document.documentElement.requestFullscreen();
window.reportReady=true;</script></body></html>`;
let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-html-browser-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error', optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] }, server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local address');
  url = `http://127.0.0.1:${address.port}/test/fixtures/html-preview.html`;
  browser = await chromium.launch({ headless: true, ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}) });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

async function setup(page: Page, source = report, shellStatus = 200) {
  page.setDefaultTimeout(10_000);
  const calls: { path: string; query: Record<string, string> }[] = [];
  await page.route('**/test/fixtures/html-preview.html', async route => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), 'Content-Security-Policy': parentCsp } });
  });
  await page.route('**/api/**', async route => {
    const u = new URL(route.request().url()); calls.push({ path: u.pathname, query: Object.fromEntries(u.searchParams) });
    if (u.pathname === '/api/client/register') { await route.fulfill({ json: registration() }); return; }
    if (u.pathname === '/api/meta') { await route.fulfill({ json: meta }); return; }
    if (u.pathname === '/api/files/html-preview') {
      await route.fulfill({ status: shellStatus, contentType: shellStatus === 200 ? 'text/html' : 'application/json', headers: { 'Content-Security-Policy': shellStatus === 200 ? shell.csp : parentCsp }, body: shellStatus === 200 ? shell.html : '{}' }); return;
    }
    const path = u.searchParams.get('path')!;
    const resolved = resolve(u.searchParams.get('cwd') || '/', path);
    const body = path.endsWith('.md') ? '# Source\n\n' + 'Paragraph.\n\n'.repeat(50) + '## 2. 章节\n\nTarget section.' : source;
    if (u.pathname === '/api/files/info') {
      await route.fulfill({ json: { path: resolved, name: resolved.split('/').at(-1), size: Buffer.byteLength(body) } });
    } else if (u.pathname === '/api/files/download') await route.fulfill({ contentType: 'application/octet-stream', body });
    else await route.fulfill({ status: 404, json: { error: { code: 'unavailable', message: u.pathname } } });
  });
  await page.goto(url);
  await page.getByRole('button', { name: 'Open report', exact: true }).click();
  await page.getByRole('button', { name: 'Preview', exact: true }).click();
  const frame = page.frameLocator('iframe[title="Interactive HTML preview"]');
  return { calls, frame, replaceSource: (value: string) => { source = value; } };
}

it('runs exact source in isolation, switches views, supports fullscreen, and admits only clicked local references', async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    const { calls, frame } = await setup(page);
    await frame.locator('#next').click();
    expect(await frame.locator('#position').textContent()).toBe('2');
    const isolation = await frame.locator('body').evaluate(() => {
      const result: string[] = [];
      for (const read of [() => parent.document.title, () => document.cookie, () => localStorage.length]) {
        try { read(); result.push('accessible'); } catch { result.push('blocked'); }
      }
      return { result, hash: location.hash };
    });
    expect(isolation).toEqual({ result: ['blocked', 'blocked', 'blocked'], hash: '#2.1' });
    await frame.locator('#fullscreen').click();
    await expect.poll(() => frame.locator('body').evaluate(() => !!document.fullscreenElement)).toBe(true);
    await frame.locator('body').evaluate(() => document.exitFullscreen());
    await page.getByRole('button', { name: 'Full screen', exact: true }).click();
    await expect.poll(() => page.evaluate(() => document.fullscreenElement?.className)).toContain('file-preview');
    await page.getByRole('button', { name: 'Exit full screen', exact: true }).click();
    await page.getByRole('button', { name: 'Full screen', exact: true }).click();
    await page.getByRole('button', { name: /^(Save as…|Download)$/ }).click();
    await expect.poll(() => page.evaluate(() => document.fullscreenElement === null)).toBe(true);
    await page.getByRole('button', { name: 'Cancel', exact: true }).click();
    expect(await frame.locator('#position').textContent()).toBe('2');
    await page.getByRole('button', { name: 'Source / text', exact: true }).click();
    expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(report);
    await page.getByRole('button', { name: 'Rendered view', exact: true }).click();
    await frame.locator('#notes').click();
    await expect.poll(() => frame.locator('#notes-dialog').evaluate((el: HTMLDialogElement) => el.open)).toBe(true);
    const before = calls.length;
    await frame.locator('#ref').evaluate((link: HTMLAnchorElement) => {
      link.click();
      parent.postMessage({ type: 'link', href: '/forged' }, '*');
    });
    await page.waitForTimeout(100);
    expect(calls).toHaveLength(before);
    await expect.poll(() => frame.locator('#notes-dialog').evaluate((el: HTMLDialogElement) => el.open)).toBe(true);
    await frame.locator('#ref').click();
    await page.getByText('/work/notes/source 中文.md', { exact: true }).waitFor();
    expect(calls.filter(call => call.path.endsWith('/info')).at(-1)?.query).toEqual({ path: '../../notes/source 中文.md', cwd: '/work/presentations/deck/' });
    await page.getByRole('button', { name: 'Preview', exact: true }).click();
    const heading = page.getByRole('heading', { name: '2. 章节', exact: true });
    await heading.waitFor();
    await expect.poll(() => page.locator('.file-preview-markdown').evaluate(el => el.scrollTop)).toBeGreaterThan(0);
    expect(calls.filter(call => call.path.endsWith('/download') && call.query.path?.endsWith('.html'))).toHaveLength(1);
    expect(errors).toEqual([]);
  } catch (error) {
    await page.screenshot({ path: join(cacheDir, 'failure.png') });
    throw new Error(`${String(error)}\nErrors: ${JSON.stringify(errors)}\nHeadings: ${JSON.stringify(await page.locator('h1,h2,h3').allTextContents())}\nPage: ${(await page.locator('body').innerText()).slice(0, 2500)}`);
  } finally { await page.close(); }
}, 45_000);

it('blocks external resources with a visible explanation and still offers source and close', async () => {
  const page = await browser.newPage();
  let external = 0;
  await page.route('https://example.test/**', route => { external++; return route.abort(); });
  try {
    const { frame } = await setup(page, report.replace('</body>', '<img src="https://example.test/image.png"><script src="https://example.test/library.js"></script></body>'));
    await frame.locator('#next').click();
    await page.getByText(/Some resources were blocked/).waitFor();
    expect(external).toBe(0);
    await page.getByRole('button', { name: 'Close preview', exact: true }).click();
    expect(await page.locator('iframe').count()).toBe(0);
  } finally { await page.close(); }
}, 30_000);

it('retains source when the authenticated sandbox cannot load', async () => {
  const page = await browser.newPage();
  try {
    await setup(page, report, 401);
    await page.getByText(/Could not start the HTML preview/).waitFor({ timeout: 15_000 });
    await page.getByRole('button', { name: 'Source / text', exact: true }).click();
    expect(await page.getByRole('textbox', { name: 'Source / text' }).inputValue()).toBe(report);
  } finally { await page.close(); }
}, 30_000);

it('refreshes explicitly and destroys the old frame before a pending read, including close during refresh', async () => {
  const page = await browser.newPage();
  let release = () => {};
  try {
    const { frame, calls, replaceSource } = await setup(page);
    await frame.getByText('Embedded report', { exact: true }).waitFor();
    replaceSource(report.replace('Embedded report', 'Updated report'));
    await page.getByRole('button', { name: 'Refresh content', exact: true }).click();
    await frame.getByText('Updated report', { exact: true }).waitFor();
    expect(calls.filter(call => call.path.endsWith('/download'))).toHaveLength(2);
    const gate = new Promise<void>(resolve => { release = resolve; });
    let started = false;
    await page.route('**/api/files/download?*', async route => {
      started = true; await gate;
      await route.fulfill({ contentType: 'application/octet-stream', body: report }).catch(() => {});
    });
    await page.getByRole('button', { name: 'Refresh content', exact: true }).click();
    await expect.poll(() => started).toBe(true);
    expect(await page.locator('iframe').count()).toBe(0);
    await page.getByRole('button', { name: 'Close preview', exact: true }).click();
    release();
    await page.waitForTimeout(100);
    expect(await page.locator('.file-preview, iframe').count()).toBe(0);
    expect(await page.getByRole('button', { name: 'Open report', exact: true }).isVisible()).toBe(true);
  } finally { release(); await page.close(); }
}, 30_000);
