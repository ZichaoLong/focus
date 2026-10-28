/** Match rendered Markdown headings without loading a second Markdown parser. */
export function findPreviewHeading(root: HTMLElement, anchor: string): HTMLElement | undefined {
  const used = new Map<string, number>();
  for (const heading of root.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')) {
    const base = (heading.textContent ?? '').trim().toLowerCase()
      .replace(/[^\p{L}\p{N}\p{M}\s_-]/gu, '').replace(/\s/g, '-');
    const count = used.get(base) ?? 0;
    used.set(base, count + 1);
    const slug = count ? `${base}-${count}` : base;
    if (heading.id === anchor || slug === anchor.toLowerCase()) return heading;
  }
  return undefined;
}
