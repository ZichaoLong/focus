import { afterEach, describe, expect, it, vi } from 'vitest';
import { canScrollVertically, captureTranscriptScrollAnchor, restoreTranscriptScrollAnchor } from '../src/components/chat/transcriptScrollAnchor';

afterEach(() => vi.unstubAllGlobals());

function viewport() {
  let insertedHeight = 0;
  const pane = { scrollTop: 150, getBoundingClientRect: () => ({ top: 50, bottom: 550 }),
    querySelectorAll: () => rows };
  const rows = Array.from({ length: 5 }, (_, index) => ({ dataset: { turnId: `row-${index}` },
    querySelectorAll: () => [],
    getBoundingClientRect: () => ({ top: 50 + index * 200 + insertedHeight - pane.scrollTop,
      bottom: 250 + index * 200 + insertedHeight - pane.scrollTop }),
  }));
  return { pane: pane as unknown as HTMLElement, rows, insert: (height: number) => { insertedHeight += height; } };
}

describe('continuous transcript scroll anchors', () => {
  it('keeps a folded header anchor when an earlier group leader joins', () => {
    let inserted = 0;
    const hiddenRow = { dataset: { turnId: 'b' }, getBoundingClientRect: () => ({ top: 0, bottom: 0 }) };
    const header = { dataset: { turnId: 'b', transcriptToolGroup: JSON.stringify(['b', 'c']) },
      getBoundingClientRect: () => ({ top: 120 + inserted - pane.scrollTop, bottom: 152 + inserted - pane.scrollTop }) };
    const pane = { scrollTop: 100, getBoundingClientRect: () => ({ top: 0, bottom: 500 }),
      querySelectorAll: (selector: string) => selector.includes(',') ? [header, hiddenRow]
        : selector.startsWith('.transcript-row') ? [hiddenRow] : [header] };
    const element = pane as unknown as HTMLElement;
    const anchor = captureTranscriptScrollAnchor(element)!;
    expect(anchor).toEqual({ id: 'b', group: true, offset: 20, scrollTop: 100 });
    header.dataset.turnId = 'a';
    header.dataset.transcriptToolGroup = JSON.stringify(['a', 'b', 'c']);
    inserted = 600;
    expect(restoreTranscriptScrollAnchor(element, anchor)).toBe(true);
    expect(pane.scrollTop).toBe(700);
    pane.scrollTop += 30;
    inserted += 200;
    restoreTranscriptScrollAnchor(element, anchor);
    expect(pane.scrollTop).toBe(930);
    expect(anchor.id).toBe('b');
  });

  it('maps a newly folded source row to its header and back when the header disappears', () => {
    let folded = false;
    let grouped = true;
    const row = { dataset: { turnId: 'b' }, querySelectorAll: () => [],
      getBoundingClientRect: () => folded ? { top: 0, bottom: 0 }
        : { top: 160 - pane.scrollTop, bottom: 224 - pane.scrollTop } };
    const header = { dataset: { turnId: 'a', transcriptToolGroup: JSON.stringify(['a', 'b']) },
      getBoundingClientRect: () => ({ top: 40 - pane.scrollTop, bottom: 72 - pane.scrollTop }) };
    const pane = { scrollTop: 150, getBoundingClientRect: () => ({ top: 0, bottom: 500 }),
      querySelectorAll: (selector: string) => selector.includes(',') ? [header, row]
        : selector.startsWith('.transcript-row') ? [row] : grouped ? [header] : [] };
    const element = pane as unknown as HTMLElement;
    const anchor = captureTranscriptScrollAnchor(element)!;
    expect(anchor.id).toBe('b');
    expect(anchor.group).toBeUndefined();
    folded = true;
    expect(restoreTranscriptScrollAnchor(element, anchor)).toBe(true);
    expect(pane.scrollTop).toBe(30);
    expect(anchor.group).toBe(true);
    folded = false; grouped = false;
    expect(restoreTranscriptScrollAnchor(element, anchor)).toBe(true);
    expect(pane.scrollTop).toBe(150);
    expect(anchor.group).toBeUndefined();
  });

  it('anchors within a long reply when earlier Markdown groups change height', () => {
    let growth = 0;
    const pane = { scrollTop: 700, getBoundingClientRect: () => ({ top: 0, bottom: 500 }), querySelectorAll: () => [row] };
    const chunks = Array.from({ length: 3 }, (_, i) => ({ dataset: { transcriptChunk: String(i) },
      getBoundingClientRect: () => ({ top: i * 600 + (i ? growth : 0) - pane.scrollTop,
        bottom: (i + 1) * 600 + growth - pane.scrollTop }) }));
    const row = { dataset: { turnId: 'long' }, querySelectorAll: () => chunks,
      getBoundingClientRect: () => ({ top: -pane.scrollTop, bottom: 1800 + growth - pane.scrollTop }) };
    const element = pane as unknown as HTMLElement;
    const anchor = captureTranscriptScrollAnchor(element)!;
    expect(anchor.chunk).toBe('1');
    growth = 300; pane.scrollTop += 20;
    restoreTranscriptScrollAnchor(element, anchor); expect(pane.scrollTop).toBe(1020);
    for (let i = 0; i < 5; i += 1) restoreTranscriptScrollAnchor(element, anchor);
    expect(pane.scrollTop).toBe(1020);
  });
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
    expect(anchor).toEqual({ id: 'row-0', offset: -150, scrollTop: 150 });
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
    expect(restoreTranscriptScrollAnchor(pane, { id: 'another-thread', offset: 0, scrollTop: 250 })).toBe(false);
    expect(pane.scrollTop).toBe(250);
  });

  it.each([-80, 80])('preserves ongoing scroll motion (%i px) across late layout changes', (motion) => {
    const { pane, insert } = viewport();
    const anchor = captureTranscriptScrollAnchor(pane)!;
    insert(3000); restoreTranscriptScrollAnchor(pane, anchor);
    pane.scrollTop += motion;
    // An observer notification without layout movement must not undo touch or inertia.
    restoreTranscriptScrollAnchor(pane, anchor);
    expect(pane.scrollTop).toBe(3150 + motion);
    insert(-600); restoreTranscriptScrollAnchor(pane, anchor);
    expect(pane.scrollTop).toBe(2550 + motion);
    pane.scrollTop += motion;
    insert(200); restoreTranscriptScrollAnchor(pane, anchor);
    expect(pane.scrollTop).toBe(2750 + 2 * motion);
    for (let i = 0; i < 5; i++) restoreTranscriptScrollAnchor(pane, anchor);
    expect(pane.scrollTop).toBe(2750 + 2 * motion);
  });

  it('does not preserve a browser clamp inside a synchronous page eviction', () => {
    const { pane, insert } = viewport(); pane.scrollTop = 450;
    const anchor = captureTranscriptScrollAnchor(pane)!;
    insert(-200);
    pane.scrollTop = 100; // The intermediate, shorter DOM clamps the old scroll position.
    restoreTranscriptScrollAnchor(pane, anchor, { preserveScrollMotion: false });
    expect(pane.scrollTop).toBe(250);
    pane.scrollTop -= 40; // Inertia resumes after the DOM transaction.
    restoreTranscriptScrollAnchor(pane, anchor);
    expect(pane.scrollTop).toBe(210);
  });
});
