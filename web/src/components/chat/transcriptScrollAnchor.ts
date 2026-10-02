export interface TranscriptScrollAnchor { id: string; offset: number; scrollTop: number }

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
      return { id: row.dataset.turnId!, offset: box.top - viewport.top, scrollTop: pane.scrollTop };
    }
  }
  return null;
}

export function restoreTranscriptScrollAnchor(pane: HTMLElement, anchor: TranscriptScrollAnchor,
  options: { preserveScrollMotion?: boolean } = {}): boolean {
  const row = [...pane.querySelectorAll<HTMLElement>('.transcript-row[data-turn-id]')]
    .find(element => element.dataset.turnId === anchor.id);
  if (!row) return false;
  const top = pane.scrollTop;
  const offset = row.getBoundingClientRect().top - pane.getBoundingClientRect().top;
  // Compare content coordinates: viewport movement from touch/inertia is not
  // layout movement and must never be pulled back to an old screen offset.
  // The owning pane disables native anchoring while using this correction.
  const motion = options.preserveScrollMotion === false ? 0 : top - anchor.scrollTop;
  const delta = offset - anchor.offset + motion;
  if (Math.abs(delta) > 0.5) pane.scrollTop += delta;
  anchor.offset = offset - (pane.scrollTop - top);
  anchor.scrollTop = pane.scrollTop;
  return true;
}
