export interface TranscriptScrollAnchor { id: string; offset: number }

/** Visual overflow (for example a copy button) does not consume a scroll gesture. */
export function canScrollVertically(element: HTMLElement, direction: 'up' | 'down'): boolean {
  return ['auto', 'scroll', 'overlay'].includes(getComputedStyle(element).overflowY)
    && element.scrollHeight > element.clientHeight + 1
    && (direction === 'up' ? element.scrollTop > 1
      : element.scrollTop + element.clientHeight < element.scrollHeight - 1);
}

/** Anchor the first visible source row, including a partially visible tall row. */
export function captureTranscriptScrollAnchor(pane: HTMLElement): TranscriptScrollAnchor | null {
  const viewport = pane.getBoundingClientRect();
  for (const row of pane.querySelectorAll<HTMLElement>('.transcript-row[data-turn-id]')) {
    const box = row.getBoundingClientRect();
    if (box.bottom > viewport.top && box.top < viewport.bottom) {
      return { id: row.dataset.turnId!, offset: box.top - viewport.top };
    }
  }
  return null;
}

export function restoreTranscriptScrollAnchor(pane: HTMLElement, anchor: TranscriptScrollAnchor): boolean {
  const row = [...pane.querySelectorAll<HTMLElement>('.transcript-row[data-turn-id]')]
    .find(element => element.dataset.turnId === anchor.id);
  if (!row) return false;
  const delta = row.getBoundingClientRect().top - pane.getBoundingClientRect().top - anchor.offset;
  if (Math.abs(delta) > 0.5) pane.scrollTop += delta;
  return true;
}
