import { afterEach, describe, expect, it, vi } from 'vitest';
import { canScrollVertically, captureTranscriptScrollAnchor, restoreTranscriptScrollAnchor } from '../src/components/chat/transcriptScrollAnchor';

afterEach(() => vi.unstubAllGlobals());

function viewport() {
  let insertedHeight = 0;
  const pane = { scrollTop: 150, getBoundingClientRect: () => ({ top: 50, bottom: 550 }),
    querySelectorAll: () => rows };
  const rows = Array.from({ length: 5 }, (_, index) => ({ dataset: { turnId: `row-${index}` },
    getBoundingClientRect: () => ({ top: 50 + index * 200 + insertedHeight - pane.scrollTop,
      bottom: 250 + index * 200 + insertedHeight - pane.scrollTop }),
  }));
  return { pane: pane as unknown as HTMLElement, rows, insert: (height: number) => { insertedHeight += height; } };
}

describe('continuous transcript scroll anchors', () => {
  it('lets gestures over overflowing text reach the transcript but respects scrollable code blocks', () => {
    const element = { scrollTop: 0, clientHeight: 255, scrollHeight: 259 } as HTMLElement;
    let overflowY = 'visible';
    vi.stubGlobal('getComputedStyle', () => ({ overflowY }));
    expect(canScrollVertically(element, 'down')).toBe(false);
    overflowY = 'auto';
    expect(canScrollVertically(element, 'down')).toBe(true);
    expect(canScrollVertically(element, 'up')).toBe(false);
    element.scrollTop = 4;
    expect(canScrollVertically(element, 'down')).toBe(false);
    expect(canScrollVertically(element, 'up')).toBe(true);
    overflowY = 'hidden';
    expect(canScrollVertically(element, 'up')).toBe(false);
  });

  it('preserves a partially visible row through prepend and delayed height measurements', () => {
    const { pane, insert } = viewport();
    const anchor = captureTranscriptScrollAnchor(pane)!;
    expect(anchor).toEqual({ id: 'row-0', offset: -150 });
    insert(3000); expect(restoreTranscriptScrollAnchor(pane, anchor)).toBe(true);
    expect(pane.scrollTop).toBe(3150);
    insert(-600); restoreTranscriptScrollAnchor(pane, anchor);
    expect(pane.scrollTop).toBe(2550);
    expect(captureTranscriptScrollAnchor(pane)).toEqual(anchor);
  });

  it('compensates distant eviction and leaves the viewport alone if an anchor disappeared', () => {
    const { pane, insert } = viewport(); pane.scrollTop = 450;
    const anchor = captureTranscriptScrollAnchor(pane)!;
    insert(-200); restoreTranscriptScrollAnchor(pane, anchor);
    expect(pane.scrollTop).toBe(250);
    expect(restoreTranscriptScrollAnchor(pane, { id: 'another-thread', offset: 0 })).toBe(false);
    expect(pane.scrollTop).toBe(250);
  });
});
