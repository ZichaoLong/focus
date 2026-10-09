/** Read raster dimensions before browser decoding; no thumbnail/transcoding dependency. */
export const IMAGE_PREVIEW_PIXELS = 24_000_000;

export function inspectPreviewImage(bytes: Uint8Array): { width: number; height: number; mime: string } {
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const signature = (offset: number, text: string) => [...text].every((c, i) => bytes[offset + i] === c.charCodeAt(0));
  const u24 = (offset: number) => data.getUint8(offset) + data.getUint8(offset + 1) * 256 + data.getUint8(offset + 2) * 65536;
  let width = 0;
  let height = 0;
  let mime = '';
  if (bytes.length >= 24 && signature(0, '\x89PNG\r\n\x1a\n') && signature(12, 'IHDR')) {
    width = data.getUint32(16); height = data.getUint32(20); mime = 'image/png';
  } else if (bytes.length >= 4 && bytes[0] === 0xff && bytes[1] === 0xd8) {
    // JPEG SOF markers contain dimensions; scan length-delimited metadata only.
    let offset = 2;
    while (offset + 4 <= bytes.length) {
      if (bytes[offset++] !== 0xff) break;
      while (bytes[offset] === 0xff) offset++;
      const marker = bytes[offset++]!;
      if (marker === 0xda || marker === 0xd9) break;
      if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
      if (offset + 2 > bytes.length) break;
      const length = data.getUint16(offset);
      if (length < 2 || offset + length > bytes.length) break;
      if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker) && length >= 8) {
        height = data.getUint16(offset + 3); width = data.getUint16(offset + 5); mime = 'image/jpeg'; break;
      }
      offset += length;
    }
  } else if (bytes.length >= 25 && signature(0, 'RIFF') && signature(8, 'WEBP')) {
    mime = 'image/webp';
    if (bytes.length >= 30 && signature(12, 'VP8X')) {
      width = 1 + u24(24); height = 1 + u24(27);
    } else if (signature(12, 'VP8L') && bytes[20] === 0x2f) {
      const bits = data.getUint32(21, true);
      width = (bits & 0x3fff) + 1; height = ((bits >>> 14) & 0x3fff) + 1;
    } else if (bytes.length >= 30 && signature(12, 'VP8 ') && signature(23, '\x9d\x01\x2a')) {
      width = data.getUint16(26, true) & 0x3fff; height = data.getUint16(28, true) & 0x3fff;
    }
  }
  if (!width || !height || !mime) throw new Error('focus.filePreviewImageInvalid');
  if (width * height > IMAGE_PREVIEW_PIXELS || width > 32768 || height > 32768) {
    throw new Error('focus.filePreviewImageTooLarge');
  }
  return { width, height, mime };
}
