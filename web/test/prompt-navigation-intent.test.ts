import { describe, expect, it, vi } from 'vitest';
import {
  centeredPromptScrollTop,
  createPromptNavigationIntent,
  type PromptNavigationActivity,
} from '../src/focus/promptNavigationIntent';

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function createScheduler() {
  let nextTimerId = 1;
  let nextFrameId = 1;
  const activeTimers = new Map<number, { callback: () => void; delayMs: number }>();
  const allTimers = new Map<number, { callback: () => void; delayMs: number }>();
  const activeFrames = new Map<number, () => void>();
  const allFrames = new Map<number, () => void>();

  const setTimer = vi.fn((callback: () => void, delayMs: number): unknown => {
    const id = nextTimerId++;
    const scheduled = { callback, delayMs };
    activeTimers.set(id, scheduled);
    allTimers.set(id, scheduled);
    return id;
  });
  const clearTimer = vi.fn((handle: unknown) => {
    activeTimers.delete(handle as number);
  });
  const requestFrame = vi.fn((callback: () => void): number => {
    const id = nextFrameId++;
    activeFrames.set(id, callback);
    allFrames.set(id, callback);
    return id;
  });
  const cancelFrame = vi.fn((id: number) => {
    activeFrames.delete(id);
  });

  return {
    activeTimers,
    activeFrames,
    setTimer,
    clearTimer,
    requestFrame,
    cancelFrame,
    timerId(delayMs: number): number {
      const entry = [...activeTimers].find(([, scheduled]) => scheduled.delayMs === delayMs);
      expect(entry, `active timer with delay ${delayMs}`).toBeDefined();
      return entry![0];
    },
    frameId(): number {
      const entry = activeFrames.keys().next().value as number | undefined;
      expect(entry, 'active animation frame').toBeDefined();
      return entry!;
    },
    fireTimer(id: number, options: { evenIfCancelled?: boolean } = {}): void {
      const scheduled = options.evenIfCancelled ? allTimers.get(id) : activeTimers.get(id);
      expect(scheduled, `timer ${id}`).toBeDefined();
      activeTimers.delete(id);
      scheduled!.callback();
    },
    fireFrame(id: number, options: { evenIfCancelled?: boolean } = {}): void {
      const callback = options.evenIfCancelled ? allFrames.get(id) : activeFrames.get(id);
      expect(callback, `animation frame ${id}`).toBeDefined();
      activeFrames.delete(id);
      callback!();
    },
  };
}

function createHarness(options: {
  resolveTarget?: (target: string) => Promise<boolean>;
  flushRender?: () => Promise<void>;
  locateTarget?: (target: string) => string | null;
  captureRestoreState?: () => string;
  initialDelayMs?: number;
  lifetimeMs?: number;
} = {}) {
  let identity = 'thread-a:reload-1:pane-1';
  let now = 0;
  const scheduler = createScheduler();
  const activity: PromptNavigationActivity[] = [];
  const captureRestoreState = vi.fn(options.captureRestoreState ?? (() => 'following'));
  const restoreAfterFailure = vi.fn((_state: string) => undefined);
  const resolveTarget = vi.fn(options.resolveTarget ?? (async () => true));
  const cancelTargetResolution = vi.fn();
  const flushRender = vi.fn(options.flushRender ?? (async () => undefined));
  const locateTarget = vi.fn(options.locateTarget ?? ((target: string) => `anchor:${target}`));
  const startSmoothScroll = vi.fn((_anchor: string) => undefined);
  const stopScrollWrites = vi.fn();
  const correctAnchor = vi.fn((_target: string, _anchor: string) => true);
  const onActivityChange = vi.fn((next: PromptNavigationActivity) => {
    activity.push(next);
  });

  const owner = createPromptNavigationIntent({
    getIdentity: () => identity,
    sameIdentity: (left, right) => left === right,
    captureRestoreState,
    restoreAfterFailure,
    resolveTarget,
    cancelTargetResolution,
    flushRender,
    locateTarget,
    startSmoothScroll,
    stopScrollWrites,
    correctAnchor,
    onActivityChange,
    initialDelayMs: options.initialDelayMs,
    lifetimeMs: options.lifetimeMs,
    now: () => now,
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
    requestFrame: scheduler.requestFrame,
    cancelFrame: scheduler.cancelFrame,
  });

  return {
    owner,
    scheduler,
    activity,
    captureRestoreState,
    restoreAfterFailure,
    resolveTarget,
    cancelTargetResolution,
    flushRender,
    locateTarget,
    startSmoothScroll,
    stopScrollWrites,
    correctAnchor,
    onActivityChange,
    setIdentity(next: string) {
      identity = next;
    },
    setNow(next: number) {
      now = next;
    },
  };
}

async function letNavigationReachResolver(): Promise<void> {
  await Promise.resolve();
}

async function letNavigationReachPostResolverRenderFence(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe('prompt navigation intent', () => {
  it('keeps B authoritative when B resolves before the superseded A', async () => {
    const a = deferred<boolean>();
    const b = deferred<boolean>();
    const harness = createHarness({
      resolveTarget: (target) => (target === 'A' ? a.promise : b.promise),
    });

    const navigateA = harness.owner.navigate('A');
    await letNavigationReachResolver();
    const navigateB = harness.owner.navigate('B');
    await letNavigationReachResolver();

    expect(harness.cancelTargetResolution).toHaveBeenCalledTimes(1);
    b.resolve(true);
    await expect(navigateB).resolves.toBe(true);
    expect(harness.startSmoothScroll).toHaveBeenCalledOnce();
    expect(harness.startSmoothScroll).toHaveBeenLastCalledWith('anchor:B');

    a.resolve(true);
    await expect(navigateA).resolves.toBe(false);
    expect(harness.locateTarget).toHaveBeenCalledTimes(1);
    expect(harness.owner.ownsScroll()).toBe(true);
  });

  it('keeps B authoritative when the superseded A resolves before B', async () => {
    const a = deferred<boolean>();
    const b = deferred<boolean>();
    const harness = createHarness({
      resolveTarget: (target) => (target === 'A' ? a.promise : b.promise),
    });

    const navigateA = harness.owner.navigate('A');
    await letNavigationReachResolver();
    const navigateB = harness.owner.navigate('B');
    await letNavigationReachResolver();

    a.resolve(true);
    await expect(navigateA).resolves.toBe(false);
    expect(harness.locateTarget).not.toHaveBeenCalled();

    b.resolve(true);
    await expect(navigateB).resolves.toBe(true);
    expect(harness.startSmoothScroll).toHaveBeenCalledExactlyOnceWith('anchor:B');
    expect(harness.owner.ownsScroll()).toBe(true);
  });

  it('does not revive A after B fails', async () => {
    const a = deferred<boolean>();
    const b = deferred<boolean>();
    const restoreStates = ['restore-A', 'restore-B'];
    const harness = createHarness({
      resolveTarget: (target) => (target === 'A' ? a.promise : b.promise),
      captureRestoreState: () => restoreStates.shift()!,
    });

    const navigateA = harness.owner.navigate('A');
    await letNavigationReachResolver();
    const navigateB = harness.owner.navigate('B');
    await letNavigationReachResolver();

    b.resolve(false);
    await expect(navigateB).resolves.toBe(false);
    expect(harness.restoreAfterFailure).toHaveBeenCalledExactlyOnceWith('restore-B');
    expect(harness.owner.ownsScroll()).toBe(false);

    a.resolve(true);
    await expect(navigateA).resolves.toBe(false);
    expect(harness.restoreAfterFailure).toHaveBeenCalledTimes(1);
    expect(harness.locateTarget).not.toHaveBeenCalled();
    expect(harness.startSmoothScroll).not.toHaveBeenCalled();
  });

  it('cancels a pending resolver and ignores its late rejection', async () => {
    const resolution = deferred<boolean>();
    const harness = createHarness({ resolveTarget: () => resolution.promise });

    const navigation = harness.owner.navigate('A');
    await letNavigationReachResolver();
    expect(harness.owner.isResolving()).toBe(true);

    harness.owner.cancel();
    expect(harness.cancelTargetResolution).toHaveBeenCalledOnce();
    expect(harness.owner.ownsScroll()).toBe(false);
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(2);

    resolution.reject(new Error('late resolver failure'));
    await expect(navigation).resolves.toBe(false);
    expect(harness.restoreAfterFailure).not.toHaveBeenCalled();
    expect(harness.locateTarget).not.toHaveBeenCalled();
  });

  it('rejects a resolved target after its pane identity changes', async () => {
    const resolution = deferred<boolean>();
    const harness = createHarness({ resolveTarget: () => resolution.promise });

    const navigation = harness.owner.navigate('A');
    await letNavigationReachResolver();
    harness.setIdentity('thread-b:reload-1:pane-2');
    resolution.resolve(true);

    await expect(navigation).resolves.toBe(false);
    expect(harness.locateTarget).not.toHaveBeenCalled();
    expect(harness.startSmoothScroll).not.toHaveBeenCalled();
    expect(harness.restoreAfterFailure).not.toHaveBeenCalled();
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(2);
    expect(harness.owner.ownsScroll()).toBe(false);
  });

  it('stops an anchored native scroll when the pane identity changes', async () => {
    const harness = createHarness({ initialDelayMs: 0 });
    await expect(harness.owner.navigateRendered('A')).resolves.toBe(true);
    const correctionFrame = harness.scheduler.frameId();

    harness.setIdentity('thread-b:reload-1:pane-2');
    harness.scheduler.fireFrame(correctionFrame);

    expect(harness.correctAnchor).not.toHaveBeenCalled();
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(2);
    expect(harness.owner.ownsScroll()).toBe(false);
  });

  it('takes ownership before waiting for the pre-navigation render fence', async () => {
    const renderFence = deferred<void>();
    const harness = createHarness({ flushRender: () => renderFence.promise });

    const navigation = harness.owner.navigateRendered('A');

    expect(harness.flushRender).toHaveBeenCalledOnce();
    expect(harness.owner.ownsScroll()).toBe(true);
    expect(harness.owner.isResolving()).toBe(true);
    expect(harness.stopScrollWrites).toHaveBeenCalledOnce();
    expect(harness.activity.at(-1)).toEqual({ active: true, resolving: true });
    expect(harness.locateTarget).not.toHaveBeenCalled();
    expect(harness.startSmoothScroll).not.toHaveBeenCalled();
    expect(harness.owner.notifyLayoutChange()).toBe(true);
    expect(harness.scheduler.activeFrames).toHaveLength(0);

    renderFence.resolve();
    await expect(navigation).resolves.toBe(true);
    expect(harness.owner.isResolving()).toBe(false);
    expect(harness.startSmoothScroll).toHaveBeenCalledExactlyOnceWith('anchor:A');
  });

  it('cancels after resolution without letting the pending render continuation scroll', async () => {
    const postResolverRenderFence = deferred<void>();
    let flushCount = 0;
    const harness = createHarness({
      flushRender: () => {
        flushCount += 1;
        return flushCount === 2 ? postResolverRenderFence.promise : Promise.resolve();
      },
    });

    const navigation = harness.owner.navigate('A');
    await letNavigationReachPostResolverRenderFence();
    expect(harness.resolveTarget).toHaveBeenCalledExactlyOnceWith('A');
    expect(harness.flushRender).toHaveBeenCalledTimes(2);

    harness.owner.cancel();
    postResolverRenderFence.resolve();

    await expect(navigation).resolves.toBe(false);
    expect(harness.cancelTargetResolution).not.toHaveBeenCalled();
    expect(harness.locateTarget).not.toHaveBeenCalled();
    expect(harness.startSmoothScroll).not.toHaveBeenCalled();
    expect(harness.restoreAfterFailure).not.toHaveBeenCalled();
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(2);
    expect(harness.owner.ownsScroll()).toBe(false);
  });

  it('lets a new intent supersede a resolved target at its pending render fence', async () => {
    const postResolverRenderFence = deferred<void>();
    let flushCount = 0;
    const harness = createHarness({
      flushRender: () => {
        flushCount += 1;
        return flushCount === 2 ? postResolverRenderFence.promise : Promise.resolve();
      },
    });

    const navigateA = harness.owner.navigate('A');
    await letNavigationReachPostResolverRenderFence();
    expect(harness.resolveTarget).toHaveBeenCalledExactlyOnceWith('A');
    expect(harness.flushRender).toHaveBeenCalledTimes(2);

    await expect(harness.owner.navigateRendered('B')).resolves.toBe(true);
    expect(harness.startSmoothScroll).toHaveBeenCalledExactlyOnceWith('anchor:B');
    postResolverRenderFence.resolve();

    await expect(navigateA).resolves.toBe(false);
    expect(harness.cancelTargetResolution).not.toHaveBeenCalled();
    expect(harness.locateTarget).toHaveBeenCalledExactlyOnceWith('B');
    expect(harness.startSmoothScroll).toHaveBeenCalledTimes(1);
    expect(harness.restoreAfterFailure).not.toHaveBeenCalled();
    expect(harness.owner.ownsScroll()).toBe(true);
  });

  it('does not let an obsolete correction timer affect a newer intent', async () => {
    const harness = createHarness({ initialDelayMs: 20, lifetimeMs: 1_000 });
    await harness.owner.navigateRendered('A');
    const staleTimer = harness.scheduler.timerId(20);

    await harness.owner.navigateRendered('B');
    const currentTimer = harness.scheduler.timerId(20);
    harness.scheduler.fireTimer(staleTimer, { evenIfCancelled: true });

    expect(harness.scheduler.activeTimers.has(currentTimer)).toBe(true);
    expect(harness.scheduler.activeFrames).toHaveLength(0);
    expect(harness.correctAnchor).not.toHaveBeenCalled();

    harness.setNow(20);
    harness.scheduler.fireTimer(currentTimer);
    expect(harness.scheduler.activeFrames).toHaveLength(1);
  });

  it('fences an obsolete frame and stops native scroll when the current target disappears', async () => {
    const harness = createHarness({ initialDelayMs: 0, lifetimeMs: 1_000 });
    await harness.owner.navigateRendered('A');
    const staleFrame = harness.scheduler.frameId();

    await harness.owner.navigateRendered('B');
    const currentFrame = harness.scheduler.frameId();
    harness.correctAnchor.mockReturnValue(false);
    harness.scheduler.fireFrame(staleFrame, { evenIfCancelled: true });

    expect(harness.scheduler.activeFrames.has(currentFrame)).toBe(true);
    expect(harness.correctAnchor).not.toHaveBeenCalled();
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(2);
    expect(harness.owner.ownsScroll()).toBe(true);

    harness.scheduler.fireFrame(currentFrame);
    expect(harness.correctAnchor).toHaveBeenCalledExactlyOnceWith('B', 'anchor:B');
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(3);
    expect(harness.owner.ownsScroll()).toBe(false);
  });

  it('does not let an obsolete expiry retire a newer intent', async () => {
    const harness = createHarness({ initialDelayMs: 1_000, lifetimeMs: 100 });
    await harness.owner.navigateRendered('A');
    const staleExpiry = harness.scheduler.timerId(100);

    await harness.owner.navigateRendered('B');
    const currentExpiry = harness.scheduler.timerId(100);
    harness.scheduler.fireTimer(staleExpiry, { evenIfCancelled: true });

    expect(harness.scheduler.activeTimers.has(currentExpiry)).toBe(true);
    expect(harness.correctAnchor).not.toHaveBeenCalled();
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(2);
    expect(harness.owner.ownsScroll()).toBe(true);

    harness.scheduler.fireTimer(currentExpiry);
    expect(harness.correctAnchor).toHaveBeenCalledExactlyOnceWith('B', 'anchor:B');
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(3);
    expect(harness.owner.ownsScroll()).toBe(false);
  });

  it('coalesces layout changes while retaining bounded anchor ownership', async () => {
    const harness = createHarness({ initialDelayMs: 0 });
    harness.correctAnchor.mockReturnValueOnce(true).mockReturnValueOnce(false);
    await harness.owner.navigateRendered('A');

    expect(harness.scheduler.activeFrames).toHaveLength(1);
    expect(harness.owner.notifyLayoutChange()).toBe(true);
    expect(harness.owner.notifyLayoutChange()).toBe(true);
    expect(harness.owner.notifyLayoutChange()).toBe(true);
    expect(harness.scheduler.activeFrames).toHaveLength(1);

    harness.scheduler.fireFrame(harness.scheduler.frameId());
    expect(harness.correctAnchor).toHaveBeenCalledTimes(1);
    expect(harness.owner.ownsScroll()).toBe(true);

    harness.owner.notifyLayoutChange();
    harness.owner.notifyLayoutChange();
    expect(harness.scheduler.activeFrames).toHaveLength(1);
    harness.scheduler.fireFrame(harness.scheduler.frameId());
    expect(harness.correctAnchor).toHaveBeenCalledTimes(2);
    expect(harness.owner.ownsScroll()).toBe(false);
    expect(harness.owner.notifyLayoutChange()).toBe(false);
  });

  it('restores only the captured state when the rendered target is missing', async () => {
    const harness = createHarness({
      captureRestoreState: () => 'captured-following',
      locateTarget: () => null,
    });

    await expect(harness.owner.navigateRendered('missing')).resolves.toBe(false);

    expect(harness.restoreAfterFailure).toHaveBeenCalledExactlyOnceWith('captured-following');
    expect(harness.startSmoothScroll).not.toHaveBeenCalled();
    expect(harness.stopScrollWrites).toHaveBeenCalledTimes(2);
    expect(harness.owner.ownsScroll()).toBe(false);
    expect(harness.activity.at(-1)).toEqual({ active: false, resolving: false });
  });

  it('restores captured state and propagates the current resolver failure', async () => {
    const failure = new Error('resolver failed');
    const harness = createHarness({
      captureRestoreState: () => 'captured-before-failure',
      resolveTarget: async () => {
        throw failure;
      },
    });

    await expect(harness.owner.navigate('A')).rejects.toBe(failure);
    expect(harness.restoreAfterFailure).toHaveBeenCalledExactlyOnceWith(
      'captured-before-failure',
    );
    expect(harness.locateTarget).not.toHaveBeenCalled();
    expect(harness.owner.ownsScroll()).toBe(false);
  });
});

describe('centered prompt scroll position', () => {
  it('centers a target in pane coordinates and clamps both scroll limits', () => {
    expect(centeredPromptScrollTop({
      scrollTop: 400,
      scrollHeight: 2_000,
      clientHeight: 600,
      paneTop: 100,
      targetTop: 450,
      targetHeight: 100,
    })).toBe(500);
    expect(centeredPromptScrollTop({
      scrollTop: 0,
      scrollHeight: 2_000,
      clientHeight: 600,
      paneTop: 100,
      targetTop: 0,
      targetHeight: 100,
    })).toBe(0);
    expect(centeredPromptScrollTop({
      scrollTop: 1_350,
      scrollHeight: 2_000,
      clientHeight: 600,
      paneTop: 100,
      targetTop: 700,
      targetHeight: 100,
    })).toBe(1_400);
  });
});
