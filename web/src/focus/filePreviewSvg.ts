import { checkPreviewImageSize } from './filePreviewImageBounds';

/** Inspect in an inert XML document; the viewer only ever embeds SVG as an image. */
export function inspectPreviewSvg(text: string): { width: number; height: number } {
  const invalid = () => { throw new Error('focus.filePreviewImageInvalid'); };
  // Custom entities have no place in a standalone image preview.
  if (/<!ENTITY/i.test(text)) return invalid();
  const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
  const root = doc.documentElement;
  if (doc.querySelector('parsererror') || root.localName !== 'svg'
    || root.namespaceURI !== 'http://www.w3.org/2000/svg') return invalid();
  const box = root.getAttribute('viewBox')?.trim().split(/[\s,]+/).map(Number);
  if (box && (box.length !== 4 || !box.every(Number.isFinite) || !(box[2]! > 0 && box[3]! > 0))) return invalid();
  const length = (name: string): number | undefined => {
    const value = root.getAttribute(name)?.trim();
    if (!value || value.endsWith('%') || value === 'auto') return undefined;
    const match = /^(\d*\.?\d+(?:e[+-]?\d+)?)\s*(px|pt|pc|in|cm|mm|q)?$/i.exec(value);
    if (!match) return invalid();
    const units: Record<string, number> = { px: 1, pt: 96 / 72, pc: 16, in: 96, cm: 96 / 2.54, mm: 96 / 25.4, q: 96 / 101.6 };
    return Number(match[1]) * units[(match[2] ?? 'px').toLowerCase()]!;
  };
  const w = length('width'), h = length('height');
  const ratio = box ? box[2]! / box[3]! : undefined;
  const width = w ?? (h && ratio ? h * ratio : box?.[2] ?? 300);
  const height = h ?? (w && ratio ? w / ratio : box?.[3] ?? 150);
  checkPreviewImageSize(width, height);
  return { width, height };
}
