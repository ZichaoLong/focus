import { toSafeMermaidSvgMarkup } from 'markstream-vue';

function bounded<T>(work: Promise<T>, milliseconds = 10_000): Promise<T | null> {
  return new Promise((resolve) => {
    const timer = window.setTimeout(() => resolve(null), milliseconds);
    work.then((value) => { window.clearTimeout(timer); resolve(value); }, () => {
      window.clearTimeout(timer);
      resolve(null);
    });
  });
}

/** Wait for printable assets; preserve source in place when an asset fails. */
export async function prepareSummaryPrint(root: HTMLElement): Promise<boolean> {
  let fallback = false;
  const diagrams = [...root.querySelectorAll<HTMLElement>('.summary-mermaid')];
  if (diagrams.length) {
    const module = await bounded(import('mermaid'));
    module?.default.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'neutral', suppressErrorRendering: true });
    for (const [index, diagram] of diagrams.entries()) {
      const rendered = module && await bounded(module.default.render(`summary-diagram-${index}`, diagram.textContent ?? ''));
      const safe = rendered && toSafeMermaidSvgMarkup(rendered.svg);
      if (safe) {
        const figure = document.createElement('figure');
        figure.className = 'summary-diagram';
        figure.innerHTML = safe;
        diagram.replaceWith(figure);
      } else fallback = true;
    }
  }
  await Promise.all([...root.querySelectorAll('img')].map(async (image) => {
    let cleanup = () => {};
    if (!image.complete) {
      await bounded(new Promise<void>((resolve) => {
        const done = () => resolve();
        image.addEventListener('load', done, { once: true });
        image.addEventListener('error', done, { once: true });
        cleanup = () => { image.removeEventListener('load', done); image.removeEventListener('error', done); };
      }));
    }
    cleanup();
    if (!image.complete || !image.naturalWidth) {
      const source = document.createElement('span');
      source.className = 'summary-source';
      source.textContent = `![${image.alt}](${image.getAttribute('src') ?? ''})`;
      image.replaceWith(source);
      fallback = true;
    }
  }));
  // Layout starts the font requests, including those used only by KaTeX.
  root.getBoundingClientRect();
  const fontsReady = await bounded(document.fonts.ready);
  const mathFontFailed = [...document.fonts].some((font) => font.family.startsWith('KaTeX') && font.status === 'error');
  if (!fontsReady || mathFontFailed) {
    root.querySelectorAll<HTMLElement>('.summary-math').forEach((math) => {
      math.textContent = math.dataset.source ?? '';
      math.className = 'summary-source';
    });
    fallback = true;
  }
  return fallback;
}
