import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick, ref } from 'vue';
import { createFocusViewport } from '../src/focus/focusViewport';

function fixture() {
  const layoutReads = vi.fn();
  const properties = new Map<string, string>();
  const style = {
    getPropertyValue: (key: string) => properties.get(key) ?? '',
    setProperty: vi.fn((key: string, value: string) => { properties.set(key, value); }),
    removeProperty: (key: string) => properties.delete(key),
  };
  function box(tagName = 'DIV', y = 0, height = 844) {
    const element = {
      tagName,
      scrollTop: 0, scrollLeft: 0, scrollHeight: 844, clientHeight: 844,
      getBoundingClientRect: () => { layoutReads(); return { x: 0, y, width: 390, height }; },
      contains: (target: unknown): boolean => target === element,
      closest: (): object | null => null,
    };
    return element;
  }
  const root = box();
  const rootStyle = { opacity: '1' };
  const visual = Object.assign(new EventTarget(), {
    width: 390, height: 700, offsetTop: 20, offsetLeft: 0, scale: 1,
  });
  const frames = new Map<number, FrameRequestCallback>();
  let frameId = 0;
  const view = Object.assign(new EventTarget(), {
    innerWidth: 390, innerHeight: 844, devicePixelRatio: 3,
    visualViewport: visual as typeof visual | undefined,
    screen: { orientation: { type: 'portrait-primary' } },
    navigator: { userAgent: 'Fixture browser' },
    requestAnimationFrame: (callback: FrameRequestCallback) => {
      frames.set(++frameId, callback);
      return frameId;
    },
    cancelAnimationFrame: (id: number) => { frames.delete(id); },
    setTimeout: (callback: () => void, ms: number) => setTimeout(callback, ms),
    clearTimeout: (id: ReturnType<typeof setTimeout>) => clearTimeout(id),
    getComputedStyle: vi.fn((element: unknown) => ({
      display: 'flex', visibility: 'visible', opacity: element === root ? rootStyle.opacity : '1',
      overflow: 'hidden', position: 'relative', zIndex: 'auto', transform: 'none', contentVisibility: 'visible',
    })),
  });
  const controls = box('DIV', 0, 50);
  const transcript = Object.assign(box('DIV', 50, 794), {
    scrollTop: 1200, scrollHeight: 4000, textContent: 'PRIVATE CONVERSATION',
  });
  const doc = Object.assign(new EventTarget(), {
    defaultView: view, documentElement: { ...box(), style }, visibilityState: 'visible',
    body: box('BODY'), getElementById: (id: string) => id === 'app' ? root : null,
    elementFromPoint: vi.fn((_x: number, y: number) => y < 50 ? controls : transcript),
    activeElement: { tagName: 'TEXTAREA', value: 'PRIVATE DRAFT' },
    location: { href: 'https://secret.test/?token=PRIVATE_TOKEN' },
  });
  const shell = {
    ...box(), ownerDocument: doc,
    contains: (target: unknown) => target === controls || target === transcript,
    querySelector: (selector: string) => selector === '.panes.chat-scroll' ? transcript
      : selector === '.reading-mode-controls' ? controls : box(),
  };
  const reading = ref(false);
  const owner = createFocusViewport(shell as unknown as HTMLElement, reading);
  const flushFrame = () => {
    const pending = [...frames.values()];
    frames.clear();
    pending.forEach((callback) => callback(0));
  };
  return {
    owner, reading, view, visual, doc, shell, transcript, controls, rootStyle, style, frames, flushFrame, layoutReads,
    report: () => JSON.parse(owner.diagnostics.report.value),
    async switchMode() {
      reading.value = !reading.value;
      await nextTick();
      await nextTick();
    },
  };
}

describe('Focus fixed viewport reconciliation', () => {
  const disposers: Array<() => void> = [];
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    disposers.splice(0).forEach((dispose) => dispose());
    vi.useRealTimers();
  });
  function setup() {
    const target = fixture();
    disposers.push(target.owner.dispose);
    return target;
  }

  it('reconciles each repeated mode transition without waiting for a resize event', async () => {
    const f = setup();
    f.owner.diagnostics.start();
    expect(f.style.getPropertyValue('--app-height')).toBe('700px');
    expect(f.style.getPropertyValue('--app-top')).toBe('20px');
    for (const height of [740, 610, 790]) {
      f.visual.height = height;
      await f.switchMode();
      expect(f.style.getPropertyValue('--app-height')).toBe(`${height}px`);
      f.visual.height += 1;
      f.flushFrame();
      expect(f.style.getPropertyValue('--app-height')).toBe(`${height + 1}px`);
      f.visual.height += 1;
      await vi.advanceTimersByTimeAsync(250);
      expect(f.style.getPropertyValue('--app-height')).toBe(`${height + 2}px`);
    }
    const report = f.report();
    expect(report.transitions.map((item: { to: boolean }) => item.to)).toEqual([true, false, true]);
    expect(report.transitions[0].samples[0].applied.height).toBe('700px');
    expect(report.transitions[2].samples.map((sample: { phase: string }) => sample.phase))
      .toEqual(['before', 'after-dom', 'after-frame', 'settled']);
    expect(f.frames.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
    expect(f.transcript.scrollTop).toBe(1200);
    expect(f.doc.activeElement.value).toBe('PRIVATE DRAFT');
  });

  it('rejects invalid viewport sizes and preserves the last usable size', async () => {
    const f = setup();
    for (const invalid of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
      f.visual.height = invalid;
      f.visual.offsetTop = invalid;
      await f.switchMode();
      expect(f.style.getPropertyValue('--app-height')).toBe('844px');
      expect(f.style.getPropertyValue('--app-top')).toBe('0px');
    }
    f.view.innerHeight = 0;
    f.doc.documentElement.clientHeight = 600;
    await f.switchMode();
    expect(f.style.getPropertyValue('--app-height')).toBe('600px');
    f.doc.documentElement.clientHeight = 0;
    await f.switchMode();
    expect(f.style.getPropertyValue('--app-height')).toBe('600px');
    f.view.visualViewport = undefined;
    f.view.innerHeight = 900;
    await f.switchMode();
    expect(f.style.getPropertyValue('--app-height')).toBe('900px');
  });

  it('keeps transition evidence through rotation and bounds viewport activity separately', async () => {
    const f = setup();
    f.owner.diagnostics.start();
    for (let i = 0; i < 10; i += 1) {
      await f.switchMode();
      f.flushFrame();
      await vi.advanceTimersByTimeAsync(250);
    }
    const transitions = f.report().transitions;
    for (let i = 0; i < 20; i += 1) {
      f.view.innerWidth = i % 2 ? 390 : 844;
      f.visual.height = i % 2 ? 700 : 390;
      f.view.dispatchEvent(new Event('resize'));
      f.visual.dispatchEvent(new Event('resize'));
      f.visual.dispatchEvent(new Event('scroll'));
      expect(f.frames.size).toBe(1);
      f.flushFrame();
    }
    expect(f.report().transitions).toEqual(transitions);
    expect(transitions).toHaveLength(6);
    expect(f.report().viewportChanges).toHaveLength(6);
    expect(f.owner.diagnostics.report.value).not.toMatch(/PRIVATE|secret\.test|token=/u);
    expect(f.report().userAgent).toBe('Fixture browser');
    const changes = f.report().viewportChanges;
    f.view.dispatchEvent(new Event('resize'));
    f.flushFrame();
    expect(f.report().viewportChanges).toEqual(changes);
  });

  it('distinguishes ancestor visibility and a dialog covering otherwise valid layout boxes', async () => {
    const f = setup();
    f.owner.diagnostics.start();
    const initial = f.report().initial;
    expect(f.report().schema).toBe('focus-viewport-v2');
    expect(initial.boxes.root.opacity).toBe('1');
    expect(initial.hitTests.controls.insideExpected).toBe(true);
    expect(initial.hitTests.transcript.insideExpected).toBe(true);

    f.rootStyle.opacity = '0';
    f.doc.elementFromPoint.mockReturnValue({
      ...f.controls, tagName: 'DIALOG', closest: () => ({}),
    });
    await f.switchMode();
    const sample = f.report().transitions[0].samples.at(-1);
    expect(sample.boxes.root.opacity).toBe('0');
    expect(sample.boxes.controls.opacity).toBe('1');
    expect(sample.boxes.transcript.height).toBeGreaterThan(0);
    expect(sample.hitTests.controls).toMatchObject({
      tag: 'DIALOG', insideExpected: false, insideShell: false, inDialog: true,
    });
    expect(sample.hitTests.transcript.insideExpected).toBe(false);
    expect(f.owner.diagnostics.report.value).not.toMatch(/PRIVATE|secret\.test|token=/u);
  });

  it('defaults to no diagnostic measurements while viewport reconciliation remains active', async () => {
    const f = setup();
    expect(f.owner.diagnostics.enabled.value).toBe(false);
    expect(f.owner.diagnostics.report.value).toBe('');
    for (const height of [740, 610, 790]) {
      f.visual.height = height;
      await f.switchMode();
      f.flushFrame();
      await vi.advanceTimersByTimeAsync(250);
      expect(f.style.getPropertyValue('--app-height')).toBe(`${height}px`);
    }
    f.visual.height = 720;
    f.view.dispatchEvent(new Event('resize'));
    f.flushFrame();
    expect(f.style.getPropertyValue('--app-height')).toBe('720px');
    expect(f.layoutReads).not.toHaveBeenCalled();
    expect(f.view.getComputedStyle).not.toHaveBeenCalled();
    expect(f.doc.elementFromPoint).not.toHaveBeenCalled();
    expect(f.owner.diagnostics.report.value).toBe('');
  });

  it('stops pending sampling, retains the report, and restarts with fresh document-local evidence', async () => {
    const f = setup();
    f.owner.diagnostics.start();
    expect(f.report().initial.phase).toBe('recording-start');
    await f.switchMode();
    f.owner.diagnostics.stop();
    const stoppedReport = f.owner.diagnostics.report.value;
    f.layoutReads.mockClear();
    f.view.getComputedStyle.mockClear();
    f.doc.elementFromPoint.mockClear();
    f.visual.height = 750;
    f.flushFrame();
    await vi.advanceTimersByTimeAsync(250);
    f.view.dispatchEvent(new Event('resize'));
    f.flushFrame();
    await f.switchMode();
    expect(f.style.getPropertyValue('--app-height')).toBe('750px');
    expect(f.owner.diagnostics.report.value).toBe(stoppedReport);
    expect(f.layoutReads).not.toHaveBeenCalled();
    expect(f.view.getComputedStyle).not.toHaveBeenCalled();
    expect(f.doc.elementFromPoint).not.toHaveBeenCalled();

    f.owner.diagnostics.start();
    expect(f.owner.diagnostics.enabled.value).toBe(true);
    expect(f.report().initial.reading).toBe(false);
    expect(f.report().transitions).toEqual([]);
    expect(f.report().viewportChanges).toEqual([]);
    f.layoutReads.mockClear();
    f.flushFrame();
    await vi.advanceTimersByTimeAsync(250);
    expect(f.layoutReads).not.toHaveBeenCalled();
    expect(f.report().transitions).toEqual([]);
    await f.switchMode();
    expect(f.report().transitions).toHaveLength(1);
    expect(setup().owner.diagnostics.enabled.value).toBe(false);
  });

  it('cancels superseded checks and cleans up pending ticks, timers and listeners', async () => {
    const f = setup();
    f.owner.diagnostics.start();
    await f.switchMode();
    f.flushFrame();
    expect(vi.getTimerCount()).toBe(1);
    await f.switchMode();
    expect(vi.getTimerCount()).toBe(0);
    f.flushFrame();
    await vi.advanceTimersByTimeAsync(250);
    expect(f.report().transitions[0].samples.at(-1).phase).toBe('after-frame');
    expect(f.report().transitions[1].samples.at(-1).phase).toBe('settled');

    f.reading.value = true;
    await nextTick();
    f.view.dispatchEvent(new Event('resize'));
    f.owner.dispose();
    await nextTick();
    f.flushFrame();
    await vi.runAllTimersAsync();
    expect(f.frames.size).toBe(0);
    expect(f.style.getPropertyValue('--app-height')).toBe('');
    f.view.dispatchEvent(new Event('resize'));
    f.view.dispatchEvent(new Event('pageshow'));
    f.visual.dispatchEvent(new Event('scroll'));
    f.doc.dispatchEvent(new Event('visibilitychange'));
    f.reading.value = false;
    await nextTick();
    expect(f.frames.size).toBe(0);
    expect(f.style.getPropertyValue('--app-height')).toBe('');
  });

  it('resynchronizes after a restored or visible document', () => {
    const f = setup();
    f.visual.height = 650;
    f.view.dispatchEvent(new Event('pageshow'));
    f.flushFrame();
    expect(f.style.getPropertyValue('--app-height')).toBe('650px');
    f.doc.visibilityState = 'hidden';
    f.doc.dispatchEvent(new Event('visibilitychange'));
    expect(f.frames.size).toBe(0);
    f.doc.visibilityState = 'visible';
    f.visual.height = 730;
    f.doc.dispatchEvent(new Event('visibilitychange'));
    f.flushFrame();
    expect(f.style.getPropertyValue('--app-height')).toBe('730px');
  });
});
