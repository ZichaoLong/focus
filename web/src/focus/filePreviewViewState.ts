/** Transient reading position for file-preview navigation; never retains DOM or content. */
export interface FilePreviewViewState {
  sourceMode: boolean;
  wrapped: boolean;
  scrollTop: number;
  scrollLeft: number;
}

/** Follow lazy Markdown/font layout until the reader interacts, then relinquish scrolling. */
export function restoreFilePreviewScroll(root: HTMLElement, view: FilePreviewViewState, restored: () => void): () => void {
  let announced = false;
  let child: Element | null = null;
  const announce = () => { if (!announced) { announced = true; restored(); } };
  const resize = new ResizeObserver(apply);
  const mutations = new MutationObserver(apply);
  const gestures = ['wheel', 'touchstart', 'pointerdown', 'keydown'];
  function apply(): void {
    if (child !== root.firstElementChild) {
      resize.disconnect();
      child = root.firstElementChild;
      resize.observe(child ?? root);
    }
    // A lazy source placeholder has different geometry from the rendered document.
    if (root.querySelector('.markdown-source-fallback[aria-busy="true"]')) return;
    root.scrollTop = view.scrollTop;
    root.scrollLeft = view.scrollLeft;
    announce();
  }
  function stop(): void {
    clearTimeout(timeout);
    resize.disconnect(); mutations.disconnect();
    for (const event of gestures) root.removeEventListener(event, stop, true);
    announce();
  }
  const timeout = setTimeout(stop, 5000);
  for (const event of gestures) root.addEventListener(event, stop, { capture: true, passive: true });
  mutations.observe(root, { childList: true, subtree: true, characterData: true });
  resize.observe(root);
  apply();
  return stop;
}
