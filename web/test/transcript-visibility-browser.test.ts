import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

type Target = 'row' | 'chunk';
type Observed = { observer: IntersectionObserver; callback: IntersectionObserverCallback;
  target: Element; queued: IntersectionObserverEntry[]; latest?: IntersectionObserverEntry };
declare global {
  interface Window {
    transcriptVisibilityFixture: {
      hold: boolean;
      observed: Observed[];
    };
  }
}

let server: ViteDevServer, browser: Browser, url: string;
const cacheDir = mkdtempSync(join(tmpdir(), 'focus-transcript-visibility-'));
beforeAll(async () => {
  server = await createServer({ cacheDir, logLevel: 'error',
    optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Missing browser-test address');
  url = `http://127.0.0.1:${address.port}/test/fixtures/composer-scroll.html`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}),
  });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); rmSync(cacheDir, { recursive: true, force: true }); });

async function fixture(target: Target, run: (page: Page, selector: string) => Promise<void>) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  page.setDefaultTimeout(15_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    const fixture = window.transcriptVisibilityFixture = { hold: false, observed: [] as Observed[] };
    const NativeObserver = window.IntersectionObserver;
    window.IntersectionObserver = class extends NativeObserver {
      constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
        super((entries, observer) => {
          const record = fixture.observed.find(record => record.observer === observer);
          if (record) {
            record.latest = entries.at(-1);
            if (fixture.hold) { record.queued.push(...entries); return; }
          }
          callback(entries, observer);
        }, options);
        this.callback = callback;
      }
      private callback: IntersectionObserverCallback;
      override observe(element: Element) {
        if (element.matches('.transcript-row,.markdown-chunk')
          && !fixture.observed.some(record => record.observer === this)) {
          fixture.observed.push({ observer: this, callback: this.callback, target: element, queued: [] });
        }
        super.observe(element);
      }
    };
  });
  try {
    await page.goto(`${url}?history${target === 'chunk' ? '&long' : ''}`);
    await page.locator('textarea.ph').waitFor();
    await page.locator('.md p').filter({ hasText: `History paragraph ${target === 'chunk' ? 200 : 48}.` }).waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.locator('textarea.ph').fill('Preserve this unsent draft');
    await page.locator('.panes').hover();
    await page.mouse.wheel(0, -300);
    await page.waitForFunction(() => !document.querySelector('.panes')!.classList.contains('is-following'));
    await page.evaluate(() => new Promise<void>(resolve => {
      let frames = 4;
      const tick = () => { if (--frames) requestAnimationFrame(tick); else resolve(); };
      requestAnimationFrame(tick);
    }));
    const selector = target === 'chunk' ? '.markdown-chunk' : '.transcript-row';
    await expect.poll(async () => (await state(page, selector)).mounted).toBeGreaterThan(0);
    await run(page, selector);
    expect(await page.locator('textarea.ph').inputValue()).toBe('Preserve this unsent draft');
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}

async function state(page: Page, selector: string) {
  return page.evaluate(selector => {
    const pane = document.querySelector('.panes')!, box = pane.getBoundingClientRect();
    const visible = [...pane.querySelectorAll<HTMLElement>(selector)].filter(element => {
      const rect = element.getBoundingClientRect();
      return rect.height > 0 && rect.bottom > box.top && rect.top < box.bottom;
    });
    return { top: pane.scrollTop, height: pane.scrollHeight, visible: visible.length,
      mounted: visible.filter(element => element.childElementCount > 0).length,
      following: pane.classList.contains('is-following') };
  }, selector);
}

it.each(['row', 'chunk'] as const)('keeps visible %s content after batched leave/enter notifications', async target => {
  await fixture(target, async (page, selector) => {
    const top = await page.evaluate(() => {
      window.transcriptVisibilityFixture.hold = true;
      const pane = document.querySelector('.panes')!;
      const top = pane.scrollTop;
      pane.querySelector<HTMLElement>('.content-wrap')!.style.display = 'none';
      return top;
    });
    await page.waitForFunction(selector => window.transcriptVisibilityFixture.observed.some(record =>
      record.target.matches(selector) && record.queued.some(entry => !entry.isIntersecting)), selector);
    await page.evaluate(top => {
      const pane = document.querySelector('.panes')!;
      pane.querySelector<HTMLElement>('.content-wrap')!.style.removeProperty('display');
      pane.scrollTop = top;
    }, top);
    await page.waitForFunction(selector => window.transcriptVisibilityFixture.observed.some(record =>
      record.target.matches(selector) && record.queued.some(entry => !entry.isIntersecting)
      && record.queued.at(-1)?.isIntersecting), selector);
    const before = await state(page, selector);
    expect(before.mounted).toBeGreaterThan(0);
    const retained = await page.locator(`${selector} > *`).first().elementHandle();
    // Use native entries, delaying their delivery to exercise the valid batch
    // contract. This is a scheduling regression, not a real background freeze.
    await page.evaluate(selector => {
      const fixture = window.transcriptVisibilityFixture;
      fixture.hold = false;
      for (const record of [...fixture.observed]) {
        if (!record.target.isConnected || !record.queued.length) continue;
        const entries = record.queued.splice(0);
        record.callback(record.target.matches(selector) ? entries : entries.slice(-1), record.observer);
      }
    }, selector);
    await expect.poll(async () => {
      const result = await state(page, selector);
      return result.visible > 0 && result.mounted === result.visible;
    }, { timeout: 3000 }).toBe(true);
    const after = await state(page, selector);
    expect(after.top).toBeCloseTo(before.top, 0);
    expect(after.height).toBeCloseTo(before.height, 0);
    expect(after.following).toBe(false);
    expect(await retained!.evaluate(element => element.isConnected)).toBe(true);
  });
}, 30_000);

it.each((['row', 'chunk'] as const).flatMap(target => ['visibilitychange', 'pageshow'].map(event => ({ target, event }))))(
  'restores missing $target content on $event without moving the reader', async ({ target, event }) => {
    await fixture(target, async (page, selector) => {
      const before = await state(page, selector);
      const pane = await page.locator('.panes').elementHandle();
      // Model a missed enter notification: the observer's native state is in
      // view while the component retained a leave notification.
      await page.evaluate(selector => {
        for (const record of [...window.transcriptVisibilityFixture.observed]) {
          if (!record.target.isConnected || !record.target.matches(selector) || !record.latest?.isIntersecting) continue;
          record.callback([{ target: record.target, time: performance.now(), isIntersecting: false } as IntersectionObserverEntry], record.observer);
        }
      }, selector);
      await expect.poll(async () => (await state(page, selector)).mounted).toBe(0);
      await page.evaluate(event => {
        if (event === 'pageshow') window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
        else document.dispatchEvent(new Event('visibilitychange'));
      }, event);
      await expect.poll(async () => {
        const result = await state(page, selector);
        return result.visible > 0 && result.mounted === result.visible;
      }, { timeout: 3000 }).toBe(true);
      const after = await state(page, selector);
      expect(after.top).toBeCloseTo(before.top, 0);
      expect(after.height).toBeCloseTo(before.height, 0);
      expect(after.following).toBe(false);
      expect(await pane!.evaluate(element => element.isConnected)).toBe(true);
    });
  }, 30_000,
);
