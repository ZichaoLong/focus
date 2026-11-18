import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-composer-scroll-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error',
    optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing local browser-test address');
  url = `http://127.0.0.1:${address.port}/test/fixtures/composer-scroll.html`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}),
  });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

async function fixture(width: number, history: boolean, run: (page: Page) => Promise<void>) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  page.setDefaultTimeout(10_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(`${url}?${history ? 'history&' : ''}${width < 640 ? 'narrow' : ''}`);
    await page.locator('textarea.ph').waitFor();
    // Lazy Markdown initially displays a differently sized source placeholder.
    // Begin composer interactions only after the fixture's real body and fonts
    // are ready, so that replacement cannot race the reading-position setup.
    await page.locator('.md').getByText('History paragraph 48.', { exact: true }).waitFor();
    await page.evaluate(() => document.fonts.ready);
    await settleLayout(page);
    await page.waitForFunction(() => {
      const pane = document.querySelector('.panes')!;
      return pane.scrollHeight > pane.clientHeight + 1000
        && pane.scrollHeight - pane.clientHeight - pane.scrollTop < 1;
    });
    await run(page);
    expect(errors).toEqual([]);
  } catch (error) {
    throw new Error(`${String(error)}\nScroll metrics: ${JSON.stringify(await metrics(page))}\nBrowser errors: ${JSON.stringify(errors)}`);
  } finally { await page.close(); }
}

async function settleLayout(page: Page) {
  // Observe the completed render and ResizeObserver/scroll follow-up frames.
  await page.evaluate(() => new Promise<void>(resolve => {
    let frames = 4;
    const tick = () => { if (--frames) requestAnimationFrame(tick); else resolve(); };
    requestAnimationFrame(tick);
  }));
}

async function metrics(page: Page) {
  return page.evaluate(() => {
    const pane = document.querySelector<HTMLElement>('.panes')!;
    const input = document.querySelector<HTMLTextAreaElement>('textarea.ph')!;
    const first = [...pane.querySelectorAll<HTMLElement>('.md p')]
      .find(element => element.getBoundingClientRect().bottom > pane.getBoundingClientRect().top);
    return { top: pane.scrollTop, bottom: pane.scrollHeight - pane.clientHeight - pane.scrollTop,
      inputHeight: input.clientHeight, inputOverflow: input.scrollHeight - input.clientHeight,
      anchor: first?.textContent, offset: first ? first.getBoundingClientRect().top - pane.getBoundingClientRect().top : null,
      following: pane.classList.contains('is-following') };
  });
}

async function browseUp(page: Page, distance: number) {
  const before = await metrics(page);
  await page.locator('.panes').hover();
  await page.mouse.wheel(0, -distance);
  await page.waitForFunction(top => document.querySelector('.panes')!.scrollTop < top - 1, before.top);
  await settleLayout(page);
}

const draft = (lines: number) => Array.from({ length: lines }, (_, index) => `Draft line ${index + 1}`).join('\n');

describe('composer sizing in the conversation scroll owner', () => {
  it('keeps arrow keys on the native editing path, even with a legacy recall cache', async () => {
    await fixture(1280, false, async page => {
      await page.evaluate(() => localStorage.setItem('kimi-web.input-history',
        JSON.stringify({ 'composer-scroll': ['previous prompt'] })));
      const input = page.locator('textarea.ph');
      for (const expanded of [false, true]) {
        await input.fill(draft(8));
        if (expanded) await page.locator('.expand-btn').click();
        await input.focus();
        await input.press('Control+Home');
        await input.press('ArrowUp');
        expect(await input.inputValue()).toBe(draft(8));
        expect(await input.evaluate((element: HTMLTextAreaElement) => element.selectionStart)).toBe(0);
        await input.press('ArrowDown');
        expect(await input.inputValue()).toBe(draft(8));
        expect(await input.evaluate((element: HTMLTextAreaElement) => element.selectionStart)).toBeGreaterThan(0);
        await input.fill('');
        await input.press('ArrowUp');
        expect(await input.inputValue()).toBe('');
      }
    });
  }, 30_000);

  it.each([1, 8, 20])('preserves history while typing in a %s-line draft', async lines => {
    await fixture(1280, true, async page => {
      const input = page.locator('textarea.ph');
      await input.fill(draft(lines));
      await settleLayout(page);
      await browseUp(page, 100);
      await input.focus();
      await input.press('Control+End');
      const before = await metrics(page);
      expect(before.following).toBe(false);
      expect(before.anchor).toMatch(/^History paragraph/);
      for (const action of [() => page.keyboard.type('x'), () => input.press('Shift+Enter'), () => input.press('Backspace')]) {
        await action();
        await settleLayout(page);
        const after = await metrics(page);
        expect(after.top).toBeCloseTo(before.top, 0);
        expect(after.anchor).toBe(before.anchor);
        expect(after.offset).toBe(before.offset);
        expect(after.following).toBe(false);
      }
    });
  }, 30_000);

  it('still shrinks after deletion and keeps an older reading position', async () => {
    await fixture(1280, true, async page => {
      const input = page.locator('textarea.ph');
      await input.fill(draft(20));
      await settleLayout(page);
      await browseUp(page, 500);
      const before = await metrics(page);
      await input.fill('Short draft');
      await settleLayout(page);
      const after = await metrics(page);
      expect(after.inputHeight).toBeLessThan(before.inputHeight);
      expect(after.inputOverflow).toBe(0);
      expect(after.top).toBeCloseTo(before.top, 0);
      expect(after.following).toBe(false);
    });
  }, 30_000);

  it.each([1280, 390])('follows the latest message as the input grows and changes mode at width %s', async width => {
    await fixture(width, false, async page => {
      const input = page.locator('textarea.ph');
      const resting = await metrics(page);
      await input.fill(draft(30));
      await settleLayout(page);
      const grown = await metrics(page);
      expect(grown.inputHeight).toBeGreaterThanOrEqual(resting.inputHeight);
      expect(grown.inputOverflow).toBeGreaterThan(0);
      expect(grown.following).toBe(true);
      expect(grown.bottom).toBeLessThan(1);
      await page.locator('.expand-btn').click();
      await settleLayout(page);
      const expanded = await metrics(page);
      expect(expanded.inputHeight).toBeGreaterThan(grown.inputHeight);
      expect(expanded.bottom).toBeLessThan(1);
      await page.locator(width < 640 ? '.expanded-editor-collapse' : '.expand-btn').click();
      await input.fill('');
      await settleLayout(page);
      const empty = await metrics(page);
      expect(empty.inputHeight).toBe(resting.inputHeight);
      expect(empty.bottom).toBeLessThan(1);
      expect(empty.following).toBe(true);
    });
  }, 30_000);
});
