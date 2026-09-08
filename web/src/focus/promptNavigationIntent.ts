type TimerHandle = unknown;
type RequestFrame = (callback: () => void) => number;
type CancelFrame = (frameId: number) => void;

export type PromptNavigationActivity = {
  active: boolean;
  resolving: boolean;
};

export type PromptNavigationIntentOwner<TTarget> = {
  navigate: (target: TTarget) => Promise<boolean>;
  navigateRendered: (target: TTarget) => Promise<boolean>;
  cancel: () => void;
  notifyLayoutChange: () => boolean;
  ownsScroll: () => boolean;
  isResolving: () => boolean;
};

export function centeredPromptScrollTop(metrics: {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  paneTop: number;
  targetTop: number;
  targetHeight: number;
}): number {
  const desiredTop = metrics.scrollTop
    + metrics.targetTop
    - metrics.paneTop
    - (metrics.clientHeight - metrics.targetHeight) * 0.5;
  const maxTop = Math.max(0, metrics.scrollHeight - metrics.clientHeight);
  return Math.min(maxTop, Math.max(0, desiredTop));
}

function defaultRequestFrame(callback: () => void): number {
  return (typeof requestAnimationFrame === 'function'
    ? requestAnimationFrame(callback)
    : setTimeout(callback, 16)) as unknown as number;
}

function defaultCancelFrame(frameId: number): void {
  if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(frameId);
  else clearTimeout(frameId);
}

type ResolvingIntent<TTarget, TIdentity, TRestoreState> = {
  phase: 'resolving';
  generation: number;
  target: TTarget;
  identity: TIdentity;
  restoreState: TRestoreState;
  resolverStarted: boolean;
};

type AnchoringIntent<TTarget, TAnchor, TIdentity, TRestoreState> = {
  phase: 'anchoring';
  generation: number;
  target: TTarget;
  anchor: TAnchor;
  identity: TIdentity;
  restoreState: TRestoreState;
  correctAfter: number;
};

type ActiveIntent<TTarget, TAnchor, TIdentity, TRestoreState> =
  | ResolvingIntent<TTarget, TIdentity, TRestoreState>
  | AnchoringIntent<TTarget, TAnchor, TIdentity, TRestoreState>;

/**
 * Own one Prompt-navigation transaction from the pre-resolution render fence
 * through bounded late-layout correction. Every await, timer, and animation
 * frame is fenced by both a local generation and the caller's current identity.
 */
export function createPromptNavigationIntent<
  TTarget,
  TAnchor,
  TIdentity,
  TRestoreState,
>(options: {
  getIdentity: () => TIdentity;
  sameIdentity: (left: TIdentity, right: TIdentity) => boolean;
  captureRestoreState: () => TRestoreState;
  restoreAfterFailure: (state: TRestoreState) => void;
  resolveTarget: (target: TTarget) => Promise<boolean>;
  cancelTargetResolution: () => void;
  flushRender: () => Promise<void>;
  locateTarget: (target: TTarget) => TAnchor | null;
  startSmoothScroll: (anchor: TAnchor) => void;
  stopScrollWrites: () => void;
  correctAnchor: (target: TTarget, anchor: TAnchor) => boolean;
  onActivityChange?: (activity: PromptNavigationActivity) => void;
  initialDelayMs?: number;
  lifetimeMs?: number;
  now?: () => number;
  setTimer?: (callback: () => void, delayMs: number) => TimerHandle;
  clearTimer?: (handle: TimerHandle) => void;
  requestFrame?: RequestFrame;
  cancelFrame?: CancelFrame;
}): PromptNavigationIntentOwner<TTarget> {
  const initialDelayMs = Math.max(0, options.initialDelayMs ?? 420);
  const lifetimeMs = Math.max(0, options.lifetimeMs ?? 8_000);
  const now = options.now ?? (() => performance.now());
  const setTimer = options.setTimer ?? (
    (callback: () => void, delayMs: number): TimerHandle => setTimeout(callback, delayMs)
  );
  const clearTimer = options.clearTimer ?? ((handle: TimerHandle) => {
    clearTimeout(handle as ReturnType<typeof setTimeout>);
  });
  const requestFrame = options.requestFrame ?? defaultRequestFrame;
  const cancelFrame = options.cancelFrame ?? defaultCancelFrame;

  let generation = 0;
  let activeIntent: ActiveIntent<TTarget, TAnchor, TIdentity, TRestoreState> | null = null;
  let correctionFrame: number | null = null;
  let correctionTimer: TimerHandle | null = null;
  let expiryTimer: TimerHandle | null = null;
  let publishedActivity = '';

  function ownsGeneration(
    intent: ActiveIntent<TTarget, TAnchor, TIdentity, TRestoreState>,
  ): boolean {
    return activeIntent?.generation === intent.generation
      && generation === intent.generation;
  }

  function identityMatches(
    intent: ActiveIntent<TTarget, TAnchor, TIdentity, TRestoreState>,
  ): boolean {
    return options.sameIdentity(intent.identity, options.getIdentity());
  }

  function publishActivity(): void {
    const activity: PromptNavigationActivity = {
      active: activeIntent !== null,
      resolving: activeIntent?.phase === 'resolving',
    };
    const key = `${activity.active}:${activity.resolving}`;
    if (key === publishedActivity) return;
    publishedActivity = key;
    options.onActivityChange?.(activity);
  }

  function clearScheduled(): void {
    if (correctionFrame !== null) {
      cancelFrame(correctionFrame);
      correctionFrame = null;
    }
    if (correctionTimer !== null) {
      clearTimer(correctionTimer);
      correctionTimer = null;
    }
    if (expiryTimer !== null) {
      clearTimer(expiryTimer);
      expiryTimer = null;
    }
  }

  function retireCurrent(optionsForRetirement: {
    cancelResolution: boolean;
    stopScroll: boolean;
  }): ActiveIntent<TTarget, TAnchor, TIdentity, TRestoreState> | null {
    const retired = activeIntent;
    generation += 1;
    activeIntent = null;
    clearScheduled();
    publishActivity();
    if (retired && optionsForRetirement.stopScroll) options.stopScrollWrites();
    if (
      retired?.phase === 'resolving'
      && retired.resolverStarted
      && optionsForRetirement.cancelResolution
    ) options.cancelTargetResolution();
    return retired;
  }

  function cancel(): void {
    retireCurrent({ cancelResolution: true, stopScroll: true });
  }

  function begin(target: TTarget): ResolvingIntent<TTarget, TIdentity, TRestoreState> {
    const restoreState = options.captureRestoreState();
    const retired = retireCurrent({ cancelResolution: true, stopScroll: true });
    if (!retired) options.stopScrollWrites();
    const intent: ResolvingIntent<TTarget, TIdentity, TRestoreState> = {
      phase: 'resolving',
      generation,
      target,
      identity: options.getIdentity(),
      restoreState,
      resolverStarted: false,
    };
    activeIntent = intent;
    publishActivity();
    return intent;
  }

  function abandonIfStale(
    intent: ActiveIntent<TTarget, TAnchor, TIdentity, TRestoreState>,
  ): boolean {
    if (!ownsGeneration(intent)) return true;
    if (identityMatches(intent)) return false;
    retireCurrent({ cancelResolution: true, stopScroll: true });
    return true;
  }

  function failCurrent(
    intent: ActiveIntent<TTarget, TAnchor, TIdentity, TRestoreState>,
  ): void {
    if (!ownsGeneration(intent)) return;
    const restoreState = intent.restoreState;
    retireCurrent({ cancelResolution: false, stopScroll: true });
    options.restoreAfterFailure(restoreState);
  }

  function deactivateAnchor(
    intent: AnchoringIntent<TTarget, TAnchor, TIdentity, TRestoreState>,
    stopScroll: boolean,
  ): void {
    if (!ownsGeneration(intent)) return;
    retireCurrent({ cancelResolution: false, stopScroll });
  }

  function scheduleCorrection(
    intent: AnchoringIntent<TTarget, TAnchor, TIdentity, TRestoreState>,
  ): void {
    if (
      !ownsGeneration(intent)
      || correctionFrame !== null
      || correctionTimer !== null
    ) return;
    const delay = intent.correctAfter - now();
    if (delay > 0) {
      correctionTimer = setTimer(() => {
        if (!ownsGeneration(intent)) return;
        correctionTimer = null;
        scheduleCorrection(intent);
      }, delay);
      return;
    }

    correctionFrame = requestFrame(() => {
      if (!ownsGeneration(intent)) return;
      correctionFrame = null;
      if (!identityMatches(intent) || !options.correctAnchor(intent.target, intent.anchor)) {
        // A replaced pane/anchor can leave the browser's old native smooth
        // animation alive even though this intent can no longer correct it.
        deactivateAnchor(intent, true);
      }
    });
  }

  function installAnchor(
    intent: ResolvingIntent<TTarget, TIdentity, TRestoreState>,
  ): boolean {
    if (abandonIfStale(intent)) return false;
    const anchor = options.locateTarget(intent.target);
    if (anchor === null) {
      failCurrent(intent);
      return false;
    }
    const anchoringIntent: AnchoringIntent<TTarget, TAnchor, TIdentity, TRestoreState> = {
      phase: 'anchoring',
      generation: intent.generation,
      target: intent.target,
      anchor,
      identity: intent.identity,
      restoreState: intent.restoreState,
      correctAfter: now() + initialDelayMs,
    };
    activeIntent = anchoringIntent;
    publishActivity();
    expiryTimer = setTimer(() => {
      if (!ownsGeneration(anchoringIntent)) return;
      expiryTimer = null;
      // End ownership at a deterministic final anchor and freeze any native
      // smooth animation that outlived the bounded correction window (for
      // example after background-tab throttling).
      try {
        if (identityMatches(anchoringIntent)) {
          options.correctAnchor(anchoringIntent.target, anchoringIntent.anchor);
        }
      } finally {
        deactivateAnchor(anchoringIntent, true);
      }
    }, lifetimeMs);
    scheduleCorrection(anchoringIntent);
    try {
      options.startSmoothScroll(anchor);
    } catch (error) {
      failCurrent(anchoringIntent);
      throw error;
    }
    return true;
  }

  async function runNavigation(target: TTarget, resolve: boolean): Promise<boolean> {
    const intent = begin(target);
    try {
      await options.flushRender();
      if (abandonIfStale(intent)) return false;

      if (resolve) {
        intent.resolverStarted = true;
        const installed = await options.resolveTarget(target);
        if (!ownsGeneration(intent)) return false;
        intent.resolverStarted = false;
        if (abandonIfStale(intent)) return false;
        if (!installed) {
          failCurrent(intent);
          return false;
        }
        await options.flushRender();
        if (abandonIfStale(intent)) return false;
      }

      return installAnchor(intent);
    } catch (error) {
      if (!ownsGeneration(intent)) return false;
      intent.resolverStarted = false;
      if (abandonIfStale(intent)) return false;
      failCurrent(intent);
      throw error;
    }
  }

  function notifyLayoutChange(): boolean {
    const intent = activeIntent;
    if (!intent) return false;
    if (intent.phase === 'anchoring') scheduleCorrection(intent);
    return true;
  }

  return {
    navigate: (target) => runNavigation(target, true),
    navigateRendered: (target) => runNavigation(target, false),
    cancel,
    notifyLayoutChange,
    ownsScroll: () => activeIntent !== null,
    isResolving: () => activeIntent?.phase === 'resolving',
  };
}
