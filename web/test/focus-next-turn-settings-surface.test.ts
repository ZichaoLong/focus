import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { observeComposerModelMenu } from '../src/components/chat/composerModelMenu';

function source(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

describe('Focus Web next-turn settings surface', () => {
  it('labels active-turn quick and full model controls as next-turn settings', () => {
    const app = source('../src/focus/FocusApp.vue');
    const pane = source('../src/components/chat/ConversationPane.vue');
    const dock = source('../src/components/chat/ChatDock.vue');
    const composer = source('../src/components/chat/Composer.vue');
    const picker = source('../src/components/settings/ModelPicker.vue');
    const settingsDialog = source('../src/focus/FocusSettingsDialog.vue');
    const en = source('../src/i18n/locales/en/focus.ts');
    const zh = source('../src/i18n/locales/zh/focus.ts');

    expect(app).toContain("client.running.value ? t('focus.nextTurnSettings') : ''");
    expect(app).toContain(':composer-model-settings-hint="activeNextTurnSettingsHint"');
    expect(app).toContain(':settings-hint="activeNextTurnSettingsHint"');
    expect(pane).toContain(':model-settings-hint="composerModelSettingsHint"');
    expect(pane).toContain(':composer-model-settings-hint="composerModelSettingsHint"');
    expect(dock).toContain(':model-settings-hint="composerModelSettingsHint"');
    expect(composer).toContain('v-if="modelSettingsHint"');
    expect(picker).toContain('v-if="settingsHint"');
    expect(settingsDialog).toContain("t('focus.nextTurnSettings')");
    expect(settingsDialog).not.toContain('running: boolean;');
    expect(en).toContain('nextTurnSettings:');
    expect(zh).toContain('nextTurnSettings:');
  });

  it('keeps the provider heading outside the touch-scrollable model list', () => {
    const composer = source('../src/components/chat/Composer.vue');
    const scrollRule = composer.match(/\.md-scroll \{([\s\S]*?)\n\}/u)?.[1] ?? '';

    expect(composer).toMatch(/class="md-section md-header">\{\{ currentProvider \}\}<\/div>\s*<div class="md-scroll">/u);
    expect(scrollRule).toContain('min-height: 0;');
    expect(scrollRule).toContain('overflow-y: auto;');
    expect(scrollRule).toContain('overscroll-behavior-y: contain;');
    expect(scrollRule).toContain('-webkit-overflow-scrolling: touch;');
  });
});

// Layout inputs are mutable so a resize/scroll can move the anchor without
// resizing the toolbar itself, as happens in the centred empty conversation.
function menuFixture() {
  function element(top: number, height: number, overflowY = 'visible', contain = 'none') {
    return {
      top,
      clientHeight: height,
      clientTop: 0,
      parentElement: null as ReturnType<typeof element> | null,
      style: { overflowY, contain },
      getBoundingClientRect() { return { top: this.top }; },
    };
  }
  const viewport = Object.assign(new EventTarget(), { offsetTop: 0, height: 500 });
  const frames = new Map<number, FrameRequestCallback>();
  let frameId = 0;
  const view = Object.assign(new EventTarget(), {
    innerHeight: 500,
    visualViewport: viewport as typeof viewport | undefined,
    getComputedStyle: (node: ReturnType<typeof element>) => node.style,
    requestAnimationFrame: vi.fn((callback: FrameRequestCallback) => {
      frames.set(++frameId, callback);
      return frameId;
    }),
    cancelAnimationFrame: vi.fn((id: number) => { frames.delete(id); }),
  });
  const pane = element(50, 450, 'hidden');
  const scroller = element(94, 330, 'auto');
  scroller.clientTop = 1;
  scroller.parentElement = pane;
  const composer = element(160, 160);
  composer.parentElement = scroller;
  const toolbar = Object.assign(element(282, 30), { ownerDocument: { defaultView: view } });
  toolbar.parentElement = composer;
  let notifyResize = () => {};
  const observe = vi.fn();
  const disconnect = vi.fn();
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { notifyResize = callback; }
    observe = observe;
    disconnect = disconnect;
  });
  const applyStyle = vi.fn<(style: Record<string, string>) => void>();
  return {
    toolbar, composer, scroller, pane, viewport, view, frames, observe, disconnect, applyStyle,
    resize: () => notifyResize(),
    start: () => observeComposerModelMenu(toolbar as unknown as HTMLElement, applyStyle),
    flush: () => {
      const pending = [...frames.values()];
      frames.clear();
      for (const callback of pending) callback(0);
    },
    bounds: () => {
      const style = applyStyle.mock.lastCall![0];
      const gap = Number(style.bottom.match(/\+ (\d+)px/u)![1]);
      const height = Number.parseFloat(style.maxHeight);
      const bottom = toolbar.top - gap;
      return { top: bottom - height, bottom, height };
    },
  };
}

describe('quick model menu visible bounds', () => {
  let stop: (() => void) | undefined;
  afterEach(() => {
    stop?.();
    stop = undefined;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('fits above a centred composer inside the bordered chat scrollport', () => {
    const fixture = menuFixture();
    stop = fixture.start();

    expect(fixture.bounds()).toEqual({ top: 103, bottom: 278, height: 175 });
    expect(fixture.observe.mock.calls.map(([node]) => node)).toEqual([
      fixture.toolbar, fixture.composer, fixture.scroller, fixture.pane,
    ]);
  });

  it.each(['auto', 'scroll', 'hidden', 'clip'])('respects an ancestor with overflow-y: %s', (overflow) => {
    const fixture = menuFixture();
    fixture.scroller.style.overflowY = overflow;
    stop = fixture.start();

    expect(fixture.bounds().top).toBeGreaterThan(fixture.scroller.top + fixture.scroller.clientTop);
    expect(fixture.bounds().height).toBeGreaterThan(0);
  });

  it.each(['paint', 'strict', 'content', 'layout paint'])('respects %s paint containment', (contain) => {
    const fixture = menuFixture();
    fixture.scroller.style = { overflowY: 'visible', contain };
    stop = fixture.start();

    expect(fixture.bounds().top).toBe(103);
  });

  it('does not treat non-clipping layout containers as scrollports', () => {
    const fixture = menuFixture();
    fixture.scroller.style = { overflowY: 'visible', contain: 'inline-size' };
    stop = fixture.start();

    expect(fixture.bounds().top).toBe(58);
  });

  it('follows a panned keyboard viewport and lifts an anchor below its visible bottom', () => {
    const fixture = menuFixture();
    fixture.scroller.style.overflowY = 'visible';
    stop = fixture.start();
    fixture.viewport.offsetTop = 90;
    fixture.viewport.height = 220;
    fixture.toolbar.top = 440;
    fixture.viewport.dispatchEvent(new Event('resize'));
    fixture.viewport.dispatchEvent(new Event('scroll'));
    expect(fixture.frames.size).toBe(1);
    fixture.flush();

    expect(fixture.bounds()).toEqual({ top: 98, bottom: 302, height: 204 });
  });

  it('remeasures after ancestor growth and coalesces layout notifications', () => {
    const fixture = menuFixture();
    stop = fixture.start();
    fixture.toolbar.top = 360;
    fixture.resize();
    fixture.view.dispatchEvent(new Event('resize'));
    fixture.view.dispatchEvent(new Event('scroll'));
    expect(fixture.applyStyle).toHaveBeenCalledTimes(1);
    expect(fixture.frames.size).toBe(1);
    fixture.flush();
    expect(fixture.bounds()).toEqual({ top: 103, bottom: 356, height: 253 });

    fixture.resize();
    fixture.flush();
    expect(fixture.applyStyle).toHaveBeenCalledTimes(2);
  });

  it('falls back to window height and caps tall desktop menus', () => {
    const fixture = menuFixture();
    fixture.view.visualViewport = undefined;
    fixture.view.innerHeight = 1000;
    fixture.pane.clientHeight = 950;
    fixture.scroller.style.overflowY = 'visible';
    fixture.toolbar.top = 920;
    stop = fixture.start();

    expect(fixture.bounds()).toEqual({ top: 356, bottom: 916, height: 560 });
    fixture.view.innerHeight = 300;
    fixture.view.dispatchEvent(new Event('resize'));
    fixture.flush();
    expect(fixture.bounds()).toEqual({ top: 58, bottom: 292, height: 234 });
  });

  it('never emits a negative height when no space remains above the toolbar', () => {
    const fixture = menuFixture();
    fixture.toolbar.top = 98;
    stop = fixture.start();
    expect(fixture.bounds().height).toBe(0);
  });

  it('disconnects listeners and discards queued or late measurements on close', () => {
    const fixture = menuFixture();
    const removeWindowListener = vi.spyOn(fixture.view, 'removeEventListener');
    const removeViewportListener = vi.spyOn(fixture.viewport, 'removeEventListener');
    stop = fixture.start();
    fixture.resize();
    const lateFrame = [...fixture.frames.values()][0]!;
    stop();
    stop = undefined;
    fixture.toolbar.top = 360;
    lateFrame(0);
    fixture.resize();
    fixture.view.dispatchEvent(new Event('resize'));
    fixture.view.dispatchEvent(new Event('scroll'));
    fixture.viewport.dispatchEvent(new Event('resize'));
    fixture.viewport.dispatchEvent(new Event('scroll'));
    fixture.flush();

    expect(fixture.disconnect).toHaveBeenCalledOnce();
    expect(fixture.view.cancelAnimationFrame).toHaveBeenCalledOnce();
    expect(fixture.frames.size).toBe(0);
    expect(fixture.applyStyle).toHaveBeenCalledTimes(1);
    expect(removeWindowListener).toHaveBeenCalledWith('resize', expect.any(Function));
    expect(removeWindowListener).toHaveBeenCalledWith('scroll', expect.any(Function), true);
    expect(removeViewportListener).toHaveBeenCalledWith('resize', expect.any(Function));
    expect(removeViewportListener).toHaveBeenCalledWith('scroll', expect.any(Function));
  });
});
