export interface TranscriptScrollAnchor { id: string; chunk?: string; group?: boolean; offset: number; scrollTop: number }

export function isTranscriptRowPinned(element: HTMLElement): boolean {
  const document = element.ownerDocument;
  const selection = document.getSelection();
  return element.contains(document.activeElement)
    || !!(selection && !selection.isCollapsed
      && (element.contains(selection.anchorNode) || element.contains(selection.focusNode)));
}

function toolGroupFor(pane: HTMLElement, member: string): HTMLElement | undefined {
  return [...pane.querySelectorAll<HTMLElement>('[data-transcript-tool-group]')].find(group => {
    try {
      const members: unknown = JSON.parse(group.dataset.transcriptToolGroup ?? 'null');
      return Array.isArray(members) && members.includes(member);
    } catch { return false; }
  });
}

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
  for (const row of pane.querySelectorAll<HTMLElement>('.transcript-row[data-turn-id], [data-transcript-tool-group]')) {
    const box = row.getBoundingClientRect();
    if (box.bottom <= box.top) continue;
    if (box.bottom > viewport.top && box.top < viewport.bottom) {
      if (row.dataset.transcriptToolGroup) {
        return { id: row.dataset.turnId!, group: true, offset: box.top - viewport.top, scrollTop: pane.scrollTop };
      }
      for (const chunk of row.querySelectorAll<HTMLElement>('[data-transcript-chunk]')) {
        const chunkBox = chunk.getBoundingClientRect();
        if (chunkBox.bottom > viewport.top && chunkBox.top < viewport.bottom) {
          return { id: row.dataset.turnId!, chunk: chunk.dataset.transcriptChunk!,
            offset: chunkBox.top - viewport.top, scrollTop: pane.scrollTop };
        }
      }
      return { id: row.dataset.turnId!, offset: box.top - viewport.top, scrollTop: pane.scrollTop };
    }
  }
  return null;
}

export function restoreTranscriptScrollAnchor(pane: HTMLElement, anchor: TranscriptScrollAnchor,
  options: { preserveScrollMotion?: boolean } = {}): boolean {
  let row = [...pane.querySelectorAll<HTMLElement>('.transcript-row[data-turn-id]')]
    .find(element => element.dataset.turnId === anchor.id);
  const box = row?.getBoundingClientRect();
  // Group headers may move when a previous page joins the run. Resolve by a
  // surviving source member, never by the group's current first row.
  if (anchor.group || !box || box.bottom <= box.top) {
    const group = toolGroupFor(pane, anchor.id);
    if (group) { row = group; anchor.group = true; delete anchor.chunk; }
    else if (box && box.bottom > box.top) delete anchor.group;
    else return false;
  }
  if (!row) return false;
  const target = anchor.chunk === undefined ? row : [...row.querySelectorAll<HTMLElement>('[data-transcript-chunk]')]
    .find(element => element.dataset.transcriptChunk === anchor.chunk);
  if (!target) return false;
  const top = pane.scrollTop;
  const offset = target.getBoundingClientRect().top - pane.getBoundingClientRect().top;
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
