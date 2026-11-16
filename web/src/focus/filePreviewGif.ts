/** Bound both the logical canvas and the number of animated GIF frames before decoding. */
import { checkPreviewImageSize } from './filePreviewImageBounds';

export const GIF_PREVIEW_FRAME_PIXELS = 96_000_000;
export const GIF_PREVIEW_FRAMES = 1000;

export function inspectGif(bytes: Uint8Array): { width: number; height: number } {
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const invalid = () => { throw new Error('focus.filePreviewImageInvalid'); };
  if (bytes.length < 13) return invalid();
  const width = data.getUint16(6, true), height = data.getUint16(8, true);
  checkPreviewImageSize(width, height);
  const colorBytes = (flags: number) => flags & 0x80 ? 3 * (1 << ((flags & 7) + 1)) : 0;
  let offset = 13 + colorBytes(bytes[10]!), frames = 0;
  function skipBlocks(): void {
    for (;;) {
      if (offset >= bytes.length) return invalid();
      const size = bytes[offset++]!;
      if (size === 0) return;
      offset += size;
      if (offset > bytes.length) return invalid();
    }
  }
  while (offset < bytes.length) {
    const marker = bytes[offset++]!;
    if (marker === 0x3b) return frames ? { width, height } : invalid();
    if (marker === 0x21) { offset++; skipBlocks(); continue; }
    if (marker !== 0x2c || offset + 9 > bytes.length) return invalid();
    const left = data.getUint16(offset, true), top = data.getUint16(offset + 2, true);
    const w = data.getUint16(offset + 4, true), h = data.getUint16(offset + 6, true);
    if (!w || !h || left + w > width || top + h > height) return invalid();
    if (++frames > GIF_PREVIEW_FRAMES || width * height * frames > GIF_PREVIEW_FRAME_PIXELS) {
      throw new Error('focus.filePreviewImageTooLarge');
    }
    offset += 9 + colorBytes(bytes[offset + 8]!) + 1; // local color table, then LZW code size
    skipBlocks();
  }
  return invalid();
}
