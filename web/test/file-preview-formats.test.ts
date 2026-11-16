import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { parsePreviewTable, TABLE_PREVIEW_CELLS, TABLE_PREVIEW_COLUMNS } from '../src/focus/filePreviewTable';
import { parsePreviewJson, JSON_PREVIEW_DEPTH, JSON_PREVIEW_NODES } from '../src/focus/filePreviewJson';
import { filePreviewLanguage, previewCodeFence, CODE_PREVIEW_CHARS, MERMAID_PREVIEW_BYTES } from '../src/focus/filePreviewCode';
import { inspectPreviewImage } from '../src/focus/filePreviewImage';
import { createFilePreview, filePreviewKind, filePreviewLimit, PDF_PREVIEW_BYTES } from '../src/focus/filePreview';

const bytes = (name: string) => new Uint8Array(readFileSync(new URL(`./fixtures/file-preview-data/${name}`, import.meta.url)));
const textFile = { path: '/work/test', name: 'test.json', size: 1 };

describe('structured file previews', () => {
  it('preserves CSV cells, multiline quotes, empty cells, leading zeros and spreadsheet formulas literally', () => {
    expect(parsePreviewTable('id,value,note\r\n001,"a,b","line 1\r\nline ""2"""\r\n02,=1+1,\r\n', ','))
      .toEqual([['id', 'value', 'note'], ['001', 'a,b', 'line 1\r\nline "2"'], ['02', '=1+1', '']]);
    expect(parsePreviewTable('a\t"b\tc"\n\t', '\t')).toEqual([['a', 'b\tc'], ['', '']]);
    expect(parsePreviewTable('', ',')).toEqual([]);
    expect(parsePreviewTable('\n\n', ',')).toEqual([[''], ['']]);
  });
  it.each(['"unclosed', 'un"quoted', '"closed" trailing'])('rejects malformed CSV without a partial table: %s', source => {
    expect(() => parsePreviewTable(source, ',')).toThrow('focus.filePreviewTableInvalid');
  });
  it('bounds table shape before rendering, even for mostly empty input', () => {
    expect(() => parsePreviewTable(','.repeat(TABLE_PREVIEW_COLUMNS), ',')).toThrow('focus.filePreviewStructuredLarge');
    expect(() => parsePreviewTable('\n'.repeat(TABLE_PREVIEW_CELLS + 1), ',')).toThrow('focus.filePreviewStructuredLarge');
  });
  it('keeps JSON number spelling, duplicate keys, object order and escaped strings', () => {
    const root = parsePreviewJson('{"n":9007199254740993,"n":1e300,"s":"a\\nb","__proto__":true,"a":[null,-0,1.00]}');
    expect(root.children?.map(n => [n.label, n.value])).toEqual([
      ['"n"', '9007199254740993'], ['"n"', '1e300'], ['"s"', '"a\\nb"'], ['"__proto__"', 'true'], ['"a"', '[]'],
    ]);
    expect(root.children?.at(-1)?.children?.map(n => n.value)).toEqual(['null', '-0', '1.00']);
  });
  it.each(['', '01', '[1,]', '{"a":1,}', '"bad\nstring"', 'true false', 'NaN', '{"a":undefined}'])('rejects invalid JSON: %s', source => {
    expect(() => parsePreviewJson(source)).toThrow('focus.filePreviewJsonInvalid');
  });
  it('bounds tree depth and node count; JSONL validates records separately and retains line labels', () => {
    expect(() => parsePreviewJson('['.repeat(JSON_PREVIEW_DEPTH + 1) + '0' + ']'.repeat(JSON_PREVIEW_DEPTH + 1)))
      .toThrow('focus.filePreviewStructuredLarge');
    expect(() => parsePreviewJson('[' + Array(JSON_PREVIEW_NODES).fill('0').join(',') + ']')).toThrow('focus.filePreviewStructuredLarge');
    const root = parsePreviewJson('{"a":1}\n\n[2,3]\n', true);
    expect(root.children?.map(n => n.label)).toEqual(['1', '3']);
    expect(root.children?.map(n => n.id)).toEqual([1, 3]);
    expect(() => parsePreviewJson('{\n"a":1}', true)).toThrow('focus.filePreviewJsonInvalid');
  });
});

describe('format admission and readable fallbacks', () => {
  it.each([
    ['picture.SVG', 'svg'], ['picture.GIF', 'image'], ['picture.bmp', 'image'], ['picture.ico', 'image'], ['picture.avif', 'image'],
    ['data.csv', 'table'], ['data.tsv', 'table'], ['data.json', 'json'], ['data.ndjson', 'json'],
    ['graph.mmd', 'mermaid'], ['graph.mermaid', 'mermaid'], ['main.py', 'code'], ['Dockerfile', 'code'], ['report.PDF', 'pdf'],
  ])('admits %s as %s', (name, kind) => { expect(filePreviewKind(name)).toBe(kind); });
  it('never turns an embedded closing fence into Markdown or inherits language names from Object.prototype', () => {
    expect(filePreviewLanguage('constructor')).toBeUndefined();
    expect(filePreviewLanguage('main.__proto__')).toBeUndefined();
    expect(previewCodeFence('```\n<img src="/api/private">\n````', 'html'))
      .toBe('`````html\n```\n<img src="/api/private">\n````\n`````');
  });
  it.each([
    ['test.json', '{invalid', 'focus.filePreviewJsonInvalid'],
    ['test.csv', '"invalid', 'focus.filePreviewTableInvalid'],
    ['test.ts', 'x'.repeat(CODE_PREVIEW_CHARS), 'focus.filePreviewRichLarge'],
    ['test.mmd', 'x'.repeat(MERMAID_PREVIEW_BYTES + 1), 'focus.filePreviewRichLarge'],
  ])('keeps the exact source on rich-view failure for %s', async (name, source, renderError) => {
    const api = { fileContent: vi.fn(async () => new Response(source)) };
    const preview = createFilePreview(api);
    await preview.open({ ...textFile, name });
    expect(preview.content.value).toMatchObject({ text: source, renderError });
    expect(preview.errorKey.value).toBe('');
    expect(api.fileContent).toHaveBeenCalledOnce();
    preview.close();
  });
  it('bounds PDF reads and releases the owned bytes without creating an iframe URL', async () => {
    const data = bytes('sample.pdf');
    const api = { fileContent: vi.fn(async () => new Response(data)) };
    const preview = createFilePreview(api);
    expect(filePreviewLimit('pdf')).toBe(PDF_PREVIEW_BYTES);
    await preview.open({ ...textFile, name: 'report.pdf', size: PDF_PREVIEW_BYTES + 1 });
    expect(api.fileContent).not.toHaveBeenCalled();
    await preview.open({ ...textFile, name: 'report.pdf' });
    expect(preview.content.value).toMatchObject({ kind: 'pdf', bytes: data, url: '' });
    preview.close();
    expect(preview.content.value).toBeNull();
  });
});

describe('additional raster header bounds', () => {
  it.each(['gif', 'bmp', 'ico', 'avif'])('inspects real %s files before browser decoding', extension => {
    expect(inspectPreviewImage(bytes(`sample.${extension}`))).toMatchObject({ width: 16, height: 16 });
  });
  it('checks actual ICO payload dimensions rather than trusting its tiny directory entry', () => {
    const ico = bytes('sample.ico');
    ico[6] = 1;
    expect(() => inspectPreviewImage(ico)).toThrow('focus.filePreviewImageInvalid');
  });
  it('accepts top-down BMP and rejects an oversized bitmap', () => {
    const bmp = bytes('sample.bmp'), view = new DataView(bmp.buffer);
    view.setInt32(22, -16, true);
    expect(inspectPreviewImage(bmp)).toMatchObject({ width: 16, height: 16 });
    view.setInt32(18, 40_000, true);
    expect(() => inspectPreviewImage(bmp)).toThrow('focus.filePreviewImageTooLarge');
  });
  it('rejects oversized AVIF properties, invalid box lengths and animated-sequence brands', () => {
    const avif = bytes('sample.avif');
    const property = Buffer.from(avif).indexOf('ispe');
    expect(property).toBeGreaterThan(0);
    new DataView(avif.buffer).setUint32(property + 8, 40_000);
    expect(() => inspectPreviewImage(avif)).toThrow('focus.filePreviewImageTooLarge');
    const broken = bytes('sample.avif'); new DataView(broken.buffer).setUint32(0, 4);
    expect(() => inspectPreviewImage(broken)).toThrow('focus.filePreviewImageInvalid');
    const sequence = bytes('sample.avif'); sequence.set(new TextEncoder().encode('avis'), 8);
    expect(() => inspectPreviewImage(sequence)).toThrow('focus.filePreviewImageInvalid');
  });
  it('bounds both GIF frame count and cumulative frame canvases', () => {
    function gif(width: number, height: number, frames: number): Uint8Array {
      const frame = [0x2c,0,0,0,0,1,0,1,0,0,2,2,0x44,1,0];
      const data = new Uint8Array(13 + frame.length * frames + 1);
      data.set(new TextEncoder().encode('GIF89a')); new DataView(data.buffer).setUint16(6, width, true);
      new DataView(data.buffer).setUint16(8, height, true);
      for (let i = 0; i < frames; i++) data.set(frame, 13 + i * frame.length);
      data[data.length - 1] = 0x3b; return data;
    }
    expect(inspectPreviewImage(gif(1, 1, 1000))).toMatchObject({ width: 1, height: 1 });
    expect(() => inspectPreviewImage(gif(1, 1, 1001))).toThrow('focus.filePreviewImageTooLarge');
    expect(() => inspectPreviewImage(gif(1000, 1000, 97))).toThrow('focus.filePreviewImageTooLarge');
    expect(() => inspectPreviewImage(bytes('sample.gif').slice(0, -1))).toThrow('focus.filePreviewImageInvalid');
  });
});
