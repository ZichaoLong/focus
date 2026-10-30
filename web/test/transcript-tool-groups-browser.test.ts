import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { chromium, type Browser, type Page } from '@playwright/test';
import { createServer, type ViteDevServer } from 'vite';

type FixtureKind = 'working' | 'replied' | 'large' | 'split' | 'paged';

declare global {
  interface Window {
    toolGroupFixture: {
      reset(kind: FixtureKind): Promise<void>;
      placeholders(kind: 'text' | 'thinking', text: string): Promise<void>;
      streamPlaceholder(kind: 'text' | 'thinking', delta: string): Promise<void>;
      reasoning(text: string): Promise<void>;
      evictFirstPage(): Promise<void>;
      navigateAway(): Promise<void>;
      revisitTool(): Promise<void>;
      reply(paragraphs?: number): Promise<void>;
      prepend(): Promise<void>;
      evictOlder(): Promise<void>;
      readonly details: string[];
      readonly protectedRow: string | null;
    };
  }
}

let server: ViteDevServer;
let browser: Browser;
let url: string;
beforeAll(async () => {
  server = await createServer({ logLevel: 'error',
    optimizeDeps: { noDiscovery: true, include: ['vue', 'vue-i18n'] },
    server: { host: '127.0.0.1', port: 0 },
  });
  await server.listen();
  const address = server.httpServer!.address();
  if (!address || typeof address === 'string') throw new Error('Expected a local browser-test server');
  url = `http://127.0.0.1:${address.port}/test/fixtures/tool-groups.html`;
  browser = await chromium.launch({ headless: true,
    ...(process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE ? { executablePath: process.env.FOCUS_TEST_CHROMIUM_EXECUTABLE } : {}),
  });
}, 60_000);
afterAll(async () => { await browser?.close(); await server?.close(); });

async function fixture(kind: FixtureKind, run: (page: Page) => Promise<void>) {
  const page = await browser.newPage({ viewport: { width: 1000, height: 600 } });
  page.setDefaultTimeout(10_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(url);
    await page.waitForFunction(() => Boolean(window.toolGroupFixture));
    await page.evaluate(value => window.toolGroupFixture.reset(value), kind);
    await page.locator('.tool-group-head').waitFor({ state: 'attached' });
    await run(page);
    expect(errors).toEqual([]);
  } finally { await page.close(); }
}
async function browseTop(page: Page) {
  await page.locator('.panes').hover();
  await page.mouse.wheel(0, -10_000);
  await page.waitForFunction(() => document.querySelector('.panes')!.scrollTop < 1);
}
const row = (id: string) => `.transcript-row[data-turn-id="turn:item:${id}:0"]`;
const tool = (id: string) => `[data-scroll-anchor-id="${id}"]`;
const head = (id: string) => `.transcript-tool-group[data-turn-id="turn:item:${id}:0"] .tool-group-head`;

async function browseTo(page: Page, selector: string) {
  await page.locator('.panes').hover();
  const delta = await page.locator(selector).evaluate(element =>
    element.getBoundingClientRect().top - document.querySelector('.panes')!.getBoundingClientRect().top - 4);
  await page.mouse.wheel(0, delta);
  await page.waitForFunction(selector => Math.abs(document.querySelector(selector)!.getBoundingClientRect().top
    - document.querySelector('.panes')!.getBoundingClientRect().top - 4) < 1, selector);
}

describe('tool groups in the real conversation scroll owner', () => {
  it.each([1000, 390].flatMap(width => (['text', 'thinking'] as const).flatMap(kind =>
    ['', '\n\n'].map(text => ({ width, kind, text })),
  )))('keeps blank $kind rows out of layout at width $width (text=$text)', async ({ width, kind, text }) => {
    await fixture('working', async page => {
      await page.setViewportSize({ width, height: 600 });
      await page.locator(tool('c')).waitFor();
      const gap = async (before: string, after: string) => page.evaluate(({ before, after }) =>
        document.querySelector(after)!.getBoundingClientRect().top
        - document.querySelector(before)!.getBoundingClientRect().bottom, { before, after });
      const originalGap = await gap(row('b'), row('c'));
      await page.evaluate(({ kind, text }) => window.toolGroupFixture.placeholders(kind, text), { kind, text });
      expect(await page.locator('.transcript-row').count()).toBe(6);
      expect(await gap(row('b'), row('c'))).toBeCloseTo(originalGap, 1);
      const emptyHeights = () => page.locator('.transcript-row[data-turn-id*="empty-"]').evaluateAll(elements =>
        elements.map(element => element.getBoundingClientRect().height));
      expect(await emptyHeights()).toEqual([0, 0, 0, 0]);

      await page.evaluate(() => window.toolGroupFixture.reply(80));
      await page.waitForFunction(() => !document.querySelector('[data-scroll-anchor-id]'));
      await page.locator(`${row('reply')} .msg`).waitFor();
      expect(await gap('.transcript-tool-group', row('reply'))).toBeCloseTo(originalGap, 1);
      expect(await emptyHeights()).toEqual([0, 0, 0, 0]);
      await browseTop(page);
      await page.locator(head('b')).click();
      await page.locator(tool('c')).waitFor();
      expect(await gap(row('b'), row('c'))).toBeCloseTo(originalGap, 1);

      await page.locator('.panes').hover();
      await page.mouse.wheel(0, 100_000);
      await page.locator(tool('c')).waitFor({ state: 'detached' });
      expect(await emptyHeights()).toEqual([0, 0, 0, 0]);
      await browseTop(page);
      await page.locator(tool('c')).waitFor();
      expect(await gap(row('b'), row('c'))).toBeCloseTo(originalGap, 1);
      await page.evaluate(() => window.toolGroupFixture.prepend());
      await page.locator(tool('c')).waitFor();
      expect(await gap(row('b'), row('c'))).toBeCloseTo(originalGap, 1);
      expect(await emptyHeights()).toEqual([0, 0, 0, 0]);
    });
  }, 30_000);

  it.each(['text', 'thinking'] as const)('reveals streamed %s in the same placeholder and hides it when cleared', async kind => {
    await fixture('working', async page => {
      await page.evaluate(kind => window.toolGroupFixture.placeholders(kind, '\n\n'), kind);
      const placeholder = await page.locator(row('empty-0')).elementHandle();
      expect(await placeholder!.evaluate(element => element.getBoundingClientRect().height)).toBe(0);
      await page.evaluate(kind => window.toolGroupFixture.streamPlaceholder(kind, 'New visible content.'), kind);
      await page.locator(row('empty-0')).getByText('New visible content.', { exact: false }).waitFor();
      expect(await placeholder!.evaluate(element => element.isConnected && element.getBoundingClientRect().height > 0)).toBe(true);
      expect(await page.locator(row('empty-0')).count()).toBe(1);

      await page.evaluate(kind => window.toolGroupFixture.placeholders(kind, ''), kind);
      expect(await placeholder!.evaluate(element => element.isConnected && element.getBoundingClientRect().height === 0)).toBe(true);
      expect(await page.locator('.tool-group-head').count()).toBe(1);
      await page.evaluate(kind => window.toolGroupFixture.streamPlaceholder(kind, 'Visible again.'), kind);
      await page.locator(row('empty-0')).getByText('Visible again.', { exact: false }).waitFor();
      expect(await placeholder!.evaluate(element => element.isConnected && element.getBoundingClientRect().height > 0)).toBe(true);
    });
  }, 30_000);

  it.each([false, true])('preserves controls and the latest choice through singleton splits and merges (open=%s)', async open => {
    await fixture('split', async page => {
      await browseTop(page);
      await page.waitForFunction(() => document.querySelector('.transcript-row[data-turn-id="turn:item:older:0"]')!.getBoundingClientRect().height > 600);
      await page.locator(head('b')).click();
      await browseTo(page, head('b'));
      await page.waitForFunction(() => window.toolGroupFixture.protectedRow === 'turn:item:b:0');
      const before = (await page.locator(head('b')).boundingBox())!.y;
      await page.evaluate(() => window.toolGroupFixture.reasoning('Checking the next tool.'));
      expect(await page.locator('.tool-group-head').count()).toBe(2);
      for (const id of ['b', 'c']) expect(await page.locator(head(id)).getAttribute('aria-expanded')).toBe('false');
      expect(await page.locator('[data-scroll-anchor-id]').count()).toBe(0);
      await page.waitForFunction(before => Math.abs(document.querySelector('.tool-group-head')!.getBoundingClientRect().y - before) < 1, before);

      await page.locator(head('b')).click();
      await page.locator(tool('b')).waitFor();
      expect(await page.locator(tool('c')).count()).toBe(0);
      if (!open) {
        await page.locator(head('c')).click();
        await page.locator(head('c')).click();
      }
      await page.evaluate(() => window.toolGroupFixture.reasoning(''));
      expect(await page.locator('.tool-group-head').count()).toBe(1);
      expect(await page.locator(head('b')).getAttribute('aria-expanded')).toBe(String(open));
      await page.evaluate(() => window.toolGroupFixture.reasoning('Checking again.'));
      for (const id of ['b', 'c']) expect(await page.locator(head(id)).getAttribute('aria-expanded')).toBe(String(open));
      if (!open) await page.locator(head('c')).click();
      await page.locator(tool('c')).getByRole('button').last().click();
      expect(await page.evaluate(() => window.toolGroupFixture.details)).toEqual(['c']);
    });
  }, 30_000);

  it('retains a collapsed singleton after page eviction and clears its choice after leaving the window', async () => {
    await fixture('paged', async page => {
      await page.locator(head('b')).click();
      await browseTo(page, row('tail'));
      await page.waitForFunction(() => window.toolGroupFixture.protectedRow === 'turn:item:tail:0');
      const before = (await page.locator(row('tail')).boundingBox())!.y;
      await page.evaluate(() => window.toolGroupFixture.evictFirstPage());
      expect(await page.locator(row('b')).count()).toBe(0);
      expect(await page.locator(head('c')).getAttribute('aria-expanded')).toBe('false');
      expect(await page.locator(tool('c')).count()).toBe(0);
      await page.waitForFunction(before => Math.abs(document.querySelector('.transcript-row[data-turn-id="turn:item:tail:0"]')!.getBoundingClientRect().y - before) < 1, before);
      await page.locator(head('c')).click();
      await page.locator(tool('c')).waitFor();
      await page.locator(head('c')).click();
      await page.evaluate(() => window.toolGroupFixture.navigateAway());
      await page.evaluate(() => window.toolGroupFixture.revisitTool());
      expect(await page.locator('.tool-group-head').count()).toBe(0);
      await page.locator(tool('c')).waitFor();
    });
  }, 30_000);

  it.each(['focus', 'selection'])('preserves %s when a group splits into untouched singletons and later seals', async kind => {
    await fixture('working', async page => {
      await page.locator(tool('b')).waitFor();
      if (kind === 'focus') await page.locator(tool('b')).getByRole('button').last().focus();
      else await page.locator(tool('b')).evaluate(element => {
        const range = document.createRange(); range.selectNodeContents(element);
        const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
      });
      await page.evaluate(() => window.toolGroupFixture.reasoning('Checking the next tool.'));
      expect(await page.locator('.tool-group-head').count()).toBe(0);
      await page.evaluate(() => window.toolGroupFixture.reply());
      expect(await page.locator(head('b')).getAttribute('aria-expanded')).toBe('true');
      expect(await page.locator(head('c')).getAttribute('aria-expanded')).toBe('false');
      if (kind === 'focus') expect(await page.locator(tool('b')).evaluate(el => el.contains(document.activeElement))).toBe(true);
      else expect(await page.evaluate(() => document.getSelection()?.toString())).toContain('echo b');
    });
  }, 30_000);

  it('folds after a reply, unmounts content, and preserves the exact detail target', async () => {
    await fixture('working', async page => {
      expect(await page.locator('.tool-group-head').getAttribute('aria-expanded')).toBe('true');
      await page.evaluate(() => window.toolGroupFixture.reply());
      await page.waitForFunction(() => !document.querySelector('[data-scroll-anchor-id]'));
      expect(await page.locator('.tool-group-head').getAttribute('aria-expanded')).toBe('false');
      await browseTop(page);
      await page.locator('.tool-group-head').click();
      await page.locator(tool('c')).getByRole('button').last().click();
      expect(await page.evaluate(() => window.toolGroupFixture.details)).toEqual(['c']);
    });
  }, 30_000);

  it.each([false, true])('preserves reading position and expansion when an older page joins (open=%s)', async open => {
    await fixture('replied', async page => {
      await browseTop(page);
      if (open) await page.locator('.tool-group-head').click();
      await page.locator('.panes').hover();
      const scrollTop = open ? 90 : 4;
      await page.mouse.wheel(0, scrollTop);
      await page.waitForFunction(top => Math.abs(document.querySelector('.panes')!.scrollTop - top) < 1, scrollTop);
      const selector = open ? row('b') : '.tool-group-head';
      await page.waitForFunction(() => window.toolGroupFixture.protectedRow !== null);
      const before = (await page.locator(selector).boundingBox())!.y;
      await page.evaluate(() => window.toolGroupFixture.prepend());
      await page.waitForFunction(() => document.querySelector('[data-turn-id="turn:item:a:0"]'));
      await page.waitForFunction(({ selector, before }) => {
        const element = document.querySelector(selector);
        return element && Math.abs(element.getBoundingClientRect().y - before) < 1;
      }, { selector, before });
      expect(await page.locator('.tool-group-head').getAttribute('aria-expanded')).toBe(String(open));
      expect(await page.locator(row('b')).count()).toBe(1);
    });
  }, 30_000);

  it('keeps hundreds of expanded tools virtual and survives source-page eviction', async () => {
    await fixture('large', async page => {
      await browseTop(page);
      expect(await page.locator('[data-scroll-anchor-id]').count()).toBe(0);
      await page.locator('.tool-group-head').click();
      await page.locator(tool('cmd-0')).waitFor();
      expect(await page.locator('[data-scroll-anchor-id]').count()).toBeLessThan(70);
      await page.locator('.tool-group-head').click();
      await page.waitForFunction(() => !document.querySelector('[data-scroll-anchor-id]'));
      // Let visibility observers see the folded layout before reopening it.
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      await page.locator('.tool-group-head').click();
      await page.locator(tool('cmd-0')).waitFor();
      expect(await page.locator('[data-scroll-anchor-id]').count()).toBeLessThan(70);
      await page.locator('.panes').hover();
      const targetTop = (await page.locator(row('cmd-120')).boundingBox())!.y;
      await page.mouse.wheel(0, targetTop + 8);
      await page.locator(tool('cmd-120')).waitFor();
      await page.waitForFunction(() => window.toolGroupFixture.protectedRow === 'turn:item:cmd-120:0');
      const before = (await page.locator(row('cmd-120')).boundingBox())!.y;
      await page.evaluate(() => window.toolGroupFixture.evictOlder());
      await page.waitForFunction(() => !document.querySelector('.transcript-row[data-turn-id="turn:item:cmd-0:0"]'));
      await page.waitForFunction(before => Math.abs(document.querySelector('.transcript-row[data-turn-id="turn:item:cmd-120:0"]')!.getBoundingClientRect().y - before) < 1, before);
      expect(await page.locator('.tool-group-head').getAttribute('aria-expanded')).toBe('true');
      expect(await page.locator('[data-scroll-anchor-id]').count()).toBeLessThan(100);
    });
  }, 30_000);

  it('transfers a freshly clicked header pin when a page replaces the group leader', async () => {
    await fixture('replied', async page => {
      await browseTop(page);
      await page.locator('.tool-group-head').click();
      const before = (await page.locator('.tool-group-head').boundingBox())!.y;
      await page.evaluate(() => window.toolGroupFixture.prepend());
      await page.waitForFunction(() => document.querySelector('.transcript-row[data-turn-id="turn:item:older:0"]')!.getBoundingClientRect().height > 600);
      await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      expect((await page.locator('.tool-group-head').boundingBox())!.y).toBeCloseTo(before, 0);
      expect(await page.locator('.tool-group-head').getAttribute('aria-expanded')).toBe('true');
    });
  }, 30_000);

  it.each(['focus', 'selection'])('does not auto-fold away the reader’s %s', async kind => {
    await fixture('working', async page => {
      await page.locator(tool('b')).waitFor();
      if (kind === 'focus') await page.locator(tool('b')).getByRole('button').last().focus();
      else await page.locator(tool('b')).evaluate(element => {
        const range = document.createRange(); range.selectNodeContents(element);
        const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
      });
      await page.evaluate(() => window.toolGroupFixture.reply());
      expect(await page.locator('.tool-group-head').getAttribute('aria-expanded')).toBe('true');
      if (kind === 'focus') expect(await page.locator(tool('b')).evaluate(el => el.contains(document.activeElement))).toBe(true);
      else expect(await page.evaluate(() => document.getSelection()?.toString())).toContain('echo b');
    });
  }, 30_000);
});
