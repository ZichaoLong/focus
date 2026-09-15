/** Keep the toolbar's upward model menu inside its actual visible scrollports. */
export function observeComposerModelMenu(
  toolbar: HTMLElement,
  applyStyle: (style: Record<string, string>) => void,
): () => void {
  const view = toolbar.ownerDocument.defaultView;
  if (!view) return () => {};
  const ancestors: HTMLElement[] = [];
  for (let parent = toolbar.parentElement; parent; parent = parent.parentElement) {
    ancestors.push(parent);
  }
  const viewport = view.visualViewport;
  let frame: number | null = null;
  let disposed = false;
  let previousHeight = -1;
  let previousGap = -1;

  function measure(): void {
    frame = null;
    if (disposed) return;
    let top = viewport?.offsetTop ?? 0;
    let bottom = top + (viewport?.height ?? view!.innerHeight);
    for (const ancestor of ancestors) {
      const style = view!.getComputedStyle(ancestor);
      if (
        /^(auto|scroll|hidden|clip)$/.test(style.overflowY)
        || /\b(paint|strict|content)\b/.test(style.contain)
      ) {
        const rect = ancestor.getBoundingClientRect();
        const innerTop = rect.top + ancestor.clientTop;
        top = Math.max(top, innerTop);
        bottom = Math.min(bottom, innerTop + ancestor.clientHeight);
      }
    }
    const anchorTop = toolbar.getBoundingClientRect().top;
    const menuBottom = Math.min(anchorTop - 4, bottom - 8);
    const height = Math.max(0, Math.floor(Math.min(560, menuBottom - top - 8)));
    const gap = Math.ceil(anchorTop - menuBottom);
    if (height === previousHeight && gap === previousGap) return;
    previousHeight = height;
    previousGap = gap;
    applyStyle({ maxHeight: `${height}px`, bottom: `calc(100% + ${gap}px)` });
  }

  function schedule(): void {
    if (!disposed && frame === null) frame = view!.requestAnimationFrame(measure);
  }

  // Observe the whole ancestor chain: textarea growth moves the toolbar without
  // resizing the toolbar itself, and the empty-state composer lives in a scroller.
  const observer = new ResizeObserver(schedule);
  for (const element of [toolbar, ...ancestors]) observer.observe(element);
  view.addEventListener('resize', schedule);
  view.addEventListener('scroll', schedule, true);
  viewport?.addEventListener('resize', schedule);
  viewport?.addEventListener('scroll', schedule);
  measure();

  return () => {
    disposed = true;
    observer.disconnect();
    if (frame !== null) view.cancelAnimationFrame(frame);
    view.removeEventListener('resize', schedule);
    view.removeEventListener('scroll', schedule, true);
    viewport?.removeEventListener('resize', schedule);
    viewport?.removeEventListener('scroll', schedule);
  };
}
