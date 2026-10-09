/** Shared image/Mermaid viewing geometry. Coordinates are CSS canvas pixels. */
export interface DiagramSize { width: number; height: number }
export interface MermaidDiagram extends DiagramSize { svg: string }
export interface DiagramPoint { x: number; y: number }
export interface DiagramTransform extends DiagramPoint { scale: number }

const INSET = 16;
export const MAX_DIAGRAM_SCALE = 4;

export function diagramFitScale(image: DiagramSize, canvas: DiagramSize): number {
  return Math.min(1, Math.max(1, canvas.width - INSET * 2) / image.width,
    Math.max(1, canvas.height - INSET * 2) / image.height);
}

export function constrainDiagram(
  view: DiagramTransform, image: DiagramSize, canvas: DiagramSize,
): DiagramTransform {
  const scale = Math.max(diagramFitScale(image, canvas) / 2, Math.min(MAX_DIAGRAM_SCALE, view.scale));
  const bound = (position: number, content: number, available: number) => content <= available - INSET * 2
    ? (available - content) / 2
    : Math.min(INSET, Math.max(available - content - INSET, position));
  return { scale, x: bound(view.x, image.width * scale, canvas.width),
    y: bound(view.y, image.height * scale, canvas.height) };
}

export function centerDiagram(image: DiagramSize, canvas: DiagramSize, scale = diagramFitScale(image, canvas)): DiagramTransform {
  return constrainDiagram({ scale, x: (canvas.width - image.width * scale) / 2,
    y: (canvas.height - image.height * scale) / 2 }, image, canvas);
}

/** Keep the image point under the gesture anchor, including a moving pinch midpoint. */
export function moveDiagram(
  view: DiagramTransform, image: DiagramSize, canvas: DiagramSize,
  from: DiagramPoint, to: DiagramPoint, factor: number,
): DiagramTransform {
  const scale = Math.max(diagramFitScale(image, canvas) / 2, Math.min(MAX_DIAGRAM_SCALE, view.scale * factor));
  return constrainDiagram({ scale, x: to.x - (from.x - view.x) * scale / view.scale,
    y: to.y - (from.y - view.y) * scale / view.scale }, image, canvas);
}
