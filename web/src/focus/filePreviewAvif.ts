/** Inspect AVIF item properties without decoding pixels. Animated sequences are not admitted. */
import { checkPreviewImageSize } from './filePreviewImageBounds';

export function inspectAvif(bytes: Uint8Array): { width: number; height: number } | null {
  const data = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const invalid = () => { throw new Error('focus.filePreviewImageInvalid'); };
  const label = (offset: number) => String.fromCharCode(...bytes.subarray(offset, offset + 4));
  type Box = { type: string; start: number; end: number };
  function boxes(start: number, end: number): Box[] {
    const result: Box[] = [];
    while (start < end) {
      if (start + 8 > end) return invalid();
      let size = data.getUint32(start), header = 8;
      if (size === 1) {
        if (start + 16 > end) return invalid();
        const large = data.getBigUint64(start + 8);
        if (large > BigInt(bytes.length)) return invalid();
        size = Number(large); header = 16;
      } else if (size === 0) size = end - start;
      if (size < header || start + size > end) return invalid();
      result.push({ type: label(start + 4), start: start + header, end: start + size });
      start += size;
    }
    return result;
  }
  if (bytes.length < 16 || label(4) !== 'ftyp') return null;
  const top = boxes(0, bytes.length);
  const ftyp = top[0]!;
  if (ftyp.end - ftyp.start < 8 || (ftyp.end - ftyp.start) % 4) return invalid();
  const brands = [label(ftyp.start)];
  for (let p = ftyp.start + 8; p < ftyp.end; p += 4) brands.push(label(p));
  if (!brands.includes('avif') || brands.includes('avis')) return invalid();
  const meta = top.find(box => box.type === 'meta');
  if (!meta || meta.start + 4 > meta.end) return invalid();
  const items = boxes(meta.start + 4, meta.end);
  const primary = items.find(box => box.type === 'pitm');
  const properties = items.find(box => box.type === 'iprp');
  if (!primary || !properties || primary.start + 6 > primary.end) return invalid();
  const version = bytes[primary.start];
  if (version !== 0 && version !== 1) return invalid();
  if (version === 1 && primary.start + 8 > primary.end) return invalid();
  const id = version === 0 ? data.getUint16(primary.start + 4) : data.getUint32(primary.start + 4);
  const containers = boxes(properties.start, properties.end);
  const ipco = containers.find(box => box.type === 'ipco');
  if (!ipco) return invalid();
  const dimensions = new Map<number, { width: number; height: number }>();
  boxes(ipco.start, ipco.end).forEach((box, index) => {
    if (box.type !== 'ispe') return;
    if (box.start + 12 !== box.end || data.getUint32(box.start) !== 0) return invalid();
    const width = data.getUint32(box.start + 4), height = data.getUint32(box.start + 8);
    // Check every coded item's dimensions, including tiles and thumbnails.
    checkPreviewImageSize(width, height);
    dimensions.set(index + 1, { width, height });
  });
  let selected: { width: number; height: number } | undefined;
  for (const box of containers.filter(box => box.type === 'ipma')) {
    let p = box.start;
    if (p + 8 > box.end || bytes[p]! > 1) return invalid();
    const longId = bytes[p] === 1, longIndex = (data.getUint32(p) & 1) !== 0;
    const count = data.getUint32(p + 4); p += 8;
    for (let i = 0; i < count; i++) {
      const size = longId ? 4 : 2;
      if (p + size + 1 > box.end) return invalid();
      const itemId = longId ? data.getUint32(p) : data.getUint16(p); p += size;
      const associations = bytes[p++]!;
      for (let j = 0; j < associations; j++) {
        if (p + (longIndex ? 2 : 1) > box.end) return invalid();
        const index = longIndex ? data.getUint16(p) & 0x7fff : bytes[p]! & 0x7f;
        p += longIndex ? 2 : 1;
        if (itemId === id && dimensions.has(index)) selected = dimensions.get(index);
      }
    }
    if (p !== box.end) return invalid();
  }
  return selected ?? invalid();
}
