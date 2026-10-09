import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFilePreview, filePreviewKind, IMAGE_PREVIEW_BYTES, MARKDOWN_RENDER_BYTES, TEXT_PREVIEW_BYTES } from '../src/focus/filePreview';
import { inspectPreviewImage, IMAGE_PREVIEW_PIXELS } from '../src/focus/filePreviewImage';
import { FocusApiError } from '../src/focus/types';

afterEach(() => vi.restoreAllMocks());
const file = { path: '/work/report.md', name: 'report.md', size: 20 };
function setup() {
  const api = { fileContent: vi.fn(async (_path: string, _signal: AbortSignal) => new Response('# First\n完整正文')) };
  return { api, preview: createFilePreview(api) };
}
function png(width = 800, height = 600): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(24);
  bytes.set([137, 80, 78, 71, 13, 10, 26, 10], 0);
  bytes.set([73, 72, 68, 82], 12);
  new DataView(bytes.buffer).setUint32(16, width);
  new DataView(bytes.buffer).setUint32(20, height);
  return bytes;
}

describe('on-demand file preview', () => {
  it('reads only on explicit open and refresh, keeping the complete text and clicked target', async () => {
    const { api, preview } = setup();
    expect(api.fileContent).not.toHaveBeenCalled();
    await preview.open(file, 2);
    expect(preview.line.value).toBe(2);
    expect(api.fileContent.mock.calls[0]?.[0]).toBe('/work/report.md');
    expect(preview.content.value).toMatchObject({ kind: 'markdown', text: '# First\n完整正文', renderMarkdown: true });
    api.fileContent.mockResolvedValueOnce(new Response('# Updated'));
    expect(preview.content.value?.text).toBe('# First\n完整正文');
    await preview.refresh();
    expect(preview.content.value?.text).toBe('# Updated');
    preview.close();
    expect(preview.content.value).toBeNull();
    expect(preview.file.value).toBeNull();
    expect(preview.opened.value).toBe(false);
  });

  it.each(['a.pdf', 'a.docx', 'a.mp4', 'a.zip'])('does not read unsupported %s', async name => {
    const { api, preview } = setup();
    await preview.open({ ...file, name });
    expect(api.fileContent).not.toHaveBeenCalled();
    expect(preview.errorKey.value).toBe('focus.filePreviewUnsupported');
  });

  it.each(['README', '.gitignore', 'data.jsonl', 'file.py', 'index.html', 'diagram.svg'])('treats %s as source text', name => {
    expect(filePreviewKind(name)).toBe('text');
  });

  it('declines a known oversized file before fetching any content', async () => {
    const { api, preview } = setup();
    await preview.open({ ...file, size: TEXT_PREVIEW_BYTES + 1 });
    expect(api.fileContent).not.toHaveBeenCalled();
    expect(preview.errorKey.value).toBe('focus.filePreviewTooLarge');
  });

  it('cancels on oversized response headers if the file grew after metadata was read', async () => {
    const { api, preview } = setup();
    const cancel = vi.fn();
    api.fileContent.mockResolvedValueOnce(new Response(new ReadableStream({ cancel }), {
      headers: { 'Content-Length': String(TEXT_PREVIEW_BYTES + 1) },
    }));
    await preview.open(file);
    expect(cancel).toHaveBeenCalledOnce();
    expect(preview.content.value).toBeNull();
    expect(preview.errorKey.value).toBe('focus.filePreviewTooLarge');
  });

  it('bounds the actual stream even without a truthful content-length and never shows partial text', async () => {
    const { api, preview } = setup();
    const cancel = vi.fn();
    api.fileContent.mockResolvedValueOnce(new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('first bytes'));
        controller.enqueue(new Uint8Array(TEXT_PREVIEW_BYTES));
      }, cancel,
    }), { headers: { 'Content-Length': '2' } }));
    await preview.open(file);
    expect(preview.content.value).toBeNull();
    expect(preview.errorKey.value).toBe('focus.filePreviewTooLarge');
    expect(cancel).toHaveBeenCalledOnce();
  });

  it('shows complete source for large Markdown and accepts exactly the text limit', async () => {
    const { api, preview } = setup();
    const text = 'x'.repeat(TEXT_PREVIEW_BYTES);
    expect(text.length).toBeGreaterThan(MARKDOWN_RENDER_BYTES);
    api.fileContent.mockResolvedValueOnce(new Response(text));
    await preview.open({ ...file, size: text.length });
    expect(preview.content.value?.text).toBe(text);
    expect(preview.content.value?.renderMarkdown).toBe(false);
  });

  it('cancels a pending stream immediately on close', async () => {
    const { api, preview } = setup();
    const cancel = vi.fn();
    api.fileContent.mockResolvedValueOnce(new Response(new ReadableStream({
      start(controller) { controller.enqueue(new TextEncoder().encode('partial')); }, cancel,
    })));
    const reading = preview.open(file);
    await vi.waitFor(() => expect(preview.received.value).toBe(7));
    preview.close();
    await reading;
    expect(api.fileContent.mock.calls[0]?.[1].aborted).toBe(true);
    expect(cancel).toHaveBeenCalledOnce();
    expect(preview.content.value).toBeNull();
    expect(preview.errorKey.value).toBe('');
  });

  it('discards a late response after another preview was opened', async () => {
    const { api, preview } = setup();
    let finish!: (response: Response) => void;
    api.fileContent.mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const old = preview.open(file);
    await preview.open({ ...file, path: '/new.md' });
    const cancel = vi.fn();
    finish(new Response(new ReadableStream({ cancel })));
    await old;
    expect(cancel).toHaveBeenCalledOnce();
    expect(preview.file.value?.path).toBe('/new.md');
    expect(preview.content.value?.text).toBe('# First\n完整正文');
  });

  it.each([new Uint8Array([255]), new Uint8Array([104, 0, 105])])('rejects invalid encoding or binary text without silent replacements', async bytes => {
    const { api, preview } = setup();
    api.fileContent.mockResolvedValueOnce(new Response(bytes));
    await preview.open(file);
    expect(preview.errorKey.value).toBe('focus.filePreviewEncoding');
    expect(preview.content.value).toBeNull();
  });

  it('reads UTF-16 with a BOM and permits empty text files', async () => {
    const { api, preview } = setup();
    api.fileContent.mockResolvedValueOnce(new Response(new Uint8Array([255, 254, 0x2d, 0x4e])));
    await preview.open(file);
    expect(preview.content.value?.text).toBe('中');
    api.fileContent.mockResolvedValueOnce(new Response(''));
    await preview.refresh();
    expect(preview.content.value?.text).toBe('');
  });

  it('reports current file errors on refresh instead of retaining a misleading old preview', async () => {
    const { api, preview } = setup();
    await preview.open(file);
    api.fileContent.mockRejectedValueOnce(new FocusApiError('missing', { code: 'file_not_found', status: 404 }));
    await preview.refresh();
    expect(preview.content.value).toBeNull();
    expect(preview.errorKey.value).toBe('focus.fileNotFound');
  });

  it('releases object URLs on refresh and close, with no persistent image cache', async () => {
    const { api, preview } = setup();
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValueOnce('blob:first').mockReturnValueOnce('blob:second');
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    api.fileContent.mockImplementation(async () => new Response(png()));
    await preview.open({ ...file, name: 'photo.png', size: 24 });
    expect(preview.content.value).toMatchObject({ kind: 'image', url: 'blob:first', width: 800, height: 600 });
    expect(create.mock.calls[0]?.[0].type).toBe('image/png');
    await preview.refresh();
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:first');
    preview.close();
    expect(revoke.mock.calls).toEqual([['blob:first'], ['blob:second']]);
  });

  it('rejects very large compressed images before passing any URL to the browser decoder', async () => {
    const { api, preview } = setup();
    const create = vi.spyOn(URL, 'createObjectURL');
    api.fileContent.mockResolvedValueOnce(new Response(png(10000, 10000)));
    await preview.open({ ...file, name: 'photo.png', size: 24 });
    expect(preview.errorKey.value).toBe('focus.filePreviewImageTooLarge');
    expect(create).not.toHaveBeenCalled();
    await preview.open({ ...file, name: 'photo.png', size: IMAGE_PREVIEW_BYTES + 1 });
    expect(preview.errorKey.value).toBe('focus.filePreviewTooLarge');
    expect(api.fileContent).toHaveBeenCalledTimes(1);
  });
});

describe('raster header inspection', () => {
  it('accepts ordinary PNGs and rejects invalid, zero or excessive dimensions', () => {
    expect(inspectPreviewImage(png())).toEqual({ width: 800, height: 600, mime: 'image/png' });
    expect(() => inspectPreviewImage(png(0, 1))).toThrow('focus.filePreviewImageInvalid');
    expect(() => inspectPreviewImage(png(IMAGE_PREVIEW_PIXELS, 2))).toThrow('focus.filePreviewImageTooLarge');
    expect(() => inspectPreviewImage(new TextEncoder().encode('<svg/>'))).toThrow('focus.filePreviewImageInvalid');
  });
  it('skips JPEG metadata and reads a progressive SOF without decoding pixels', () => {
    const bytes = new Uint8Array([255,216,255,224,0,4,1,2,255,194,0,8,8,2,88,3,32,0]);
    expect(inspectPreviewImage(bytes)).toEqual({ width: 800, height: 600, mime: 'image/jpeg' });
    expect(() => inspectPreviewImage(bytes.slice(0, 15))).toThrow('focus.filePreviewImageInvalid');
  });
  it('reads WebP extended, lossy and lossless dimensions', () => {
    const bytes = new Uint8Array(30);
    bytes.set(new TextEncoder().encode('RIFF'), 0);
    bytes.set(new TextEncoder().encode('WEBPVP8X'), 8);
    bytes.set([0x1f,3,0,0x57,2,0], 24);
    expect(inspectPreviewImage(bytes)).toMatchObject({ width: 800, height: 600, mime: 'image/webp' });
    bytes.set(new TextEncoder().encode('VP8 '), 12);
    bytes.set([0x9d,1,0x2a,0x20,3,0x58,2], 23);
    expect(inspectPreviewImage(bytes)).toMatchObject({ width: 800, height: 600 });
    bytes.set(new TextEncoder().encode('VP8L'), 12);
    bytes[20] = 0x2f;
    new DataView(bytes.buffer).setUint32(21, 799 | (599 << 14), true);
    expect(inspectPreviewImage(bytes.subarray(0,25))).toMatchObject({ width: 800, height: 600 });
  });
});
