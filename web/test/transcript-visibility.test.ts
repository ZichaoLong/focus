import { afterEach, describe, expect, it, vi } from 'vitest';
import { observeTranscriptVisibility } from '../src/components/chat/transcriptVisibility';

function fixture(supported = true) {
  let now = 10, frameId = 0;
  const frames = new Map<number, FrameRequestCallback>();
  const observers: Observer[] = [];
  class Observer {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
    takeRecords = vi.fn(() => []);
    constructor(readonly callback: IntersectionObserverCallback) { observers.push(this); }
    emit(target: object, ...states: Array<[number, boolean]>) {
      this.callback(states.map(([time, isIntersecting]) => ({ target, time, isIntersecting })) as IntersectionObserverEntry[],
        this as unknown as IntersectionObserver);
    }
  }
  const view = Object.assign(new EventTarget(), {
    IntersectionObserver: supported ? Observer : undefined,
    performance: { now: () => now },
    requestAnimationFrame: (callback: FrameRequestCallback) => { frames.set(++frameId, callback); return frameId; },
    cancelAnimationFrame: (id: number) => { frames.delete(id); },
  });
  const document = Object.assign(new EventTarget(), { defaultView: view, visibilityState: 'visible' });
  const add = vi.spyOn(document, 'addEventListener'), remove = vi.spyOn(document, 'removeEventListener');
  const cleanups: Array<() => void> = [];
  function observe() {
    const update = vi.fn();
    const element = { ownerDocument: document, closest: () => null } as unknown as HTMLElement;
    const stop = observeTranscriptVisibility(element, update);
    cleanups.push(stop);
    return { element, update, stop, observer: observers.at(-1)! };
  }
  return { observe, document, view, observers, frames, add, remove,
    now(value: number) { now = value; },
    visible(value: boolean) { document.visibilityState = value ? 'visible' : 'hidden'; document.dispatchEvent(new Event('visibilitychange')); },
    pageshow(persisted: boolean) { view.dispatchEvent(Object.assign(new Event('pageshow'), { persisted })); },
    flush() { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback(now)); },
    dispose() { cleanups.forEach(stop => stop()); },
  };
}

describe('transcript visibility delivery and recovery', () => {
  const fixtures: ReturnType<typeof fixture>[] = [];
  function setup(supported = true) { const value = fixture(supported); fixtures.push(value); return value; }
  afterEach(() => fixtures.splice(0).forEach(value => value.dispose()));

  it('applies the newest state in a batch in either direction', () => {
    const f = setup(), row = f.observe();
    row.observer.emit(row.element, [1, false], [2, true]);
    expect(row.update.mock.calls).toEqual([[true]]);
    row.observer.emit(row.element, [3, true], [4, false]);
    expect(row.update.mock.calls).toEqual([[true], [false]]);
    row.observer.emit(row.element, [6, true], [5, false]);
    expect(row.update).toHaveBeenLastCalledWith(true);
    row.observer.emit({}, [7, false]);
    expect(row.update).toHaveBeenCalledTimes(3);
  });

  it('keeps background content and discards old notifications across recovery', () => {
    const f = setup(), row = f.observe();
    row.observer.emit(row.element, [1, true]);
    f.visible(false);
    row.observer.emit(row.element, [2, false]);
    f.visible(true);
    row.observer.emit(row.element, [3, false]);
    expect(row.update.mock.calls).toEqual([[true]]);
    f.flush();
    expect(row.observer.takeRecords).toHaveBeenCalledOnce();
    expect(row.observer.unobserve).toHaveBeenCalledWith(row.element);
    row.observer.emit(row.element, [9, false]);
    expect(row.update).toHaveBeenCalledOnce();
    row.observer.emit(row.element, [10, true]);
    expect(row.update.mock.calls).toEqual([[true], [true]]);
    row.observer.emit(row.element, [11, false]);
    expect(row.update).toHaveBeenLastCalledWith(false);
  });

  it('shares one foreground frame across rows and chunks and still virtualizes offscreen content', () => {
    const f = setup(), row = f.observe(), chunk = f.observe();
    expect(f.add).toHaveBeenCalledTimes(1);
    f.visible(true); f.pageshow(true); f.visible(true);
    expect(f.frames.size).toBe(1);
    f.flush();
    for (const item of [row, chunk]) expect(item.observer.observe).toHaveBeenCalledTimes(2);
    row.observer.emit(row.element, [10, true]);
    chunk.observer.emit(chunk.element, [10, false]);
    expect(row.update).toHaveBeenLastCalledWith(true);
    expect(chunk.update).toHaveBeenLastCalledWith(false);
  });

  it('rechecks BFCache restoration and cancels a pending pass when hidden again', () => {
    const f = setup(), row = f.observe();
    f.pageshow(false);
    expect(f.frames.size).toBe(0);
    f.pageshow(true);
    expect(f.frames.size).toBe(1);
    f.visible(false); f.pageshow(true);
    expect(f.frames.size).toBe(0);
    f.now(20); f.visible(true); f.flush();
    expect(row.observer.observe).toHaveBeenCalledTimes(2);
    row.observer.emit(row.element, [19, false], [20, true]);
    expect(row.update.mock.calls).toEqual([[true]]);
  });

  it('releases listeners and scheduled work when the final target unmounts', () => {
    const f = setup(), row = f.observe(), chunk = f.observe();
    f.visible(true); row.stop(); f.flush();
    expect(row.observer.observe).toHaveBeenCalledTimes(1);
    expect(chunk.observer.observe).toHaveBeenCalledTimes(2);
    expect(f.remove).not.toHaveBeenCalled();
    f.visible(true); chunk.stop();
    expect(f.frames.size).toBe(0);
    expect(f.remove).toHaveBeenCalledOnce();
    row.observer.emit(row.element, [30, true]);
    expect(row.update).not.toHaveBeenCalled();
    f.visible(true); f.pageshow(true);
    expect(f.frames.size).toBe(0);
    const next = f.observe();
    f.visible(true); f.flush();
    expect(next.observer.observe).toHaveBeenCalledTimes(2);
  });

  it('renders content without observers when the browser lacks IntersectionObserver', () => {
    const f = setup(false), row = f.observe();
    expect(row.update.mock.calls).toEqual([[true]]);
    expect(f.add).not.toHaveBeenCalled();
    expect(f.observers).toHaveLength(0);
  });
});
