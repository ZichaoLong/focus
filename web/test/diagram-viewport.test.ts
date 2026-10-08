import { describe, expect, it } from 'vitest';
import { centerDiagram, constrainDiagram, diagramFitScale, moveDiagram } from '../src/lib/diagramViewport';

describe('Mermaid viewing geometry', () => {
  const phone = { width: 320, height: 420 };
  it.each([{ width: 200, height: 20_000 }, { width: 30_000, height: 200 }])(
    'fits the complete $width × $height diagram, including scales below 50%', (image) => {
      const view = centerDiagram(image, phone);
      expect(view.scale).toBeLessThan(0.5);
      expect(view.x).toBeGreaterThanOrEqual(16);
      expect(view.y).toBeGreaterThanOrEqual(16);
      expect(view.x + image.width * view.scale).toBeLessThanOrEqual(phone.width - 16);
      expect(view.y + image.height * view.scale).toBeLessThanOrEqual(phone.height - 16);
    },
  );
  it('keeps small diagrams at their original size and centered', () => {
    expect(centerDiagram({ width: 100, height: 80 }, phone)).toEqual({ scale: 1, x: 110, y: 170 });
  });
  it('preserves the image point under the moving pinch midpoint', () => {
    const image = { width: 1000, height: 1200 };
    const before = { scale: 1, x: -300, y: -400 };
    const from = { x: 160, y: 210 };
    const to = { x: 180, y: 230 };
    const after = moveDiagram(before, image, phone, from, to, 1.5);
    expect(after.scale).toBe(1.5);
    expect((to.x - after.x) / after.scale).toBe((from.x - before.x) / before.scale);
    expect((to.y - after.y) / after.scale).toBe((from.y - before.y) / before.scale);
  });
  it('allows reaching both far edges without losing the diagram offscreen', () => {
    const image = { width: 3000, height: 2000 };
    const first = constrainDiagram({ scale: 1, x: 100_000, y: 100_000 }, image, phone);
    expect(first).toEqual({ scale: 1, x: 16, y: 16 });
    const last = constrainDiagram({ scale: 1, x: -100_000, y: -100_000 }, image, phone);
    expect(last.x + image.width).toBe(phone.width - 16);
    expect(last.y + image.height).toBe(phone.height - 16);
  });
  it('bounds extreme zoom input and refits after portrait/landscape changes', () => {
    const image = { width: 3000, height: 2000 };
    const initial = centerDiagram(image, phone);
    const anchor = { x: 160, y: 210 };
    expect(moveDiagram(initial, image, phone, anchor, anchor, 1e20).scale).toBe(4);
    expect(moveDiagram(initial, image, phone, anchor, anchor, 1e-20).scale).toBe(diagramFitScale(image, phone) / 2);
    const landscape = { width: 700, height: 260 };
    const fitted = centerDiagram(image, landscape);
    expect(fitted.x + image.width * fitted.scale).toBeLessThanOrEqual(landscape.width - 16);
    expect(fitted.y + image.height * fitted.scale).toBeLessThanOrEqual(landscape.height - 16);
  });
});
