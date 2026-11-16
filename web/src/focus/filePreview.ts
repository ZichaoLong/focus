/** On-demand, bounded file reads. See the single-file download/preview contract. */
import { ref, shallowRef } from 'vue';
import type { FileDownloadApi } from './fileDownload';
import { fileDownloadErrorKey } from './fileDownload';
import type { FocusFileInfo } from './types';
import { inspectPreviewImage } from './filePreviewImage';
import { inspectPreviewSvg } from './filePreviewSvg';
import { parsePreviewTable } from './filePreviewTable';
import { parsePreviewJson, type PreviewJsonNode } from './filePreviewJson';
import { CODE_PREVIEW_CHARS, MERMAID_PREVIEW_BYTES, filePreviewLanguage, previewCodeFence } from './filePreviewCode';

export const TEXT_PREVIEW_BYTES = 1024 * 1024;
export const MARKDOWN_RENDER_BYTES = 128 * 1024;
export const IMAGE_PREVIEW_BYTES = 16 * 1024 * 1024;
export const HTML_PREVIEW_BYTES = 8 * 1024 * 1024;
export const PDF_PREVIEW_BYTES = 32 * 1024 * 1024;
export type FilePreviewKind = 'text' | 'markdown' | 'image' | 'html' | 'svg' | 'table' | 'json' | 'code' | 'mermaid' | 'pdf';
export interface FilePreviewContent {
  kind: FilePreviewKind;
  text: string;
  url: string;
  width: number;
  height: number;
  renderMarkdown: boolean;
  renderedText?: string;
  language?: string;
  table?: string[][];
  json?: PreviewJsonNode;
  bytes?: Uint8Array<ArrayBuffer>;
  renderError?: string;
}

const TEXT_EXTENSIONS = new Set(('txt text log json jsonl ndjson csv tsv yaml yml toml ini cfg conf config '
  + 'xml html htm svg css scss less js mjs cjs jsx ts tsx vue svelte py pyi ipynb sh bash zsh fish '
  + 'c h cc cpp hpp cs go rs java kt swift rb php pl r sql tex bib rst diff patch env properties '
  + 'gitignore gitattributes editorconfig lock').split(' '));
const TEXT_NAMES = new Set(['dockerfile', 'makefile', 'license', 'readme', 'justfile', 'procfile']);

export function filePreviewKind(name: string): FilePreviewKind | null {
  const lower = name.toLowerCase();
  const extension = lower.split('.').at(-1) ?? '';
  if (['md', 'markdown', 'mdown'].includes(extension)) return 'markdown';
  if (['html', 'htm'].includes(extension)) return 'html';
  if (extension === 'pdf') return 'pdf';
  if (extension === 'svg') return 'svg';
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'ico', 'avif'].includes(extension)) return 'image';
  if (['csv', 'tsv'].includes(extension)) return 'table';
  if (['json', 'jsonl', 'ndjson', 'ipynb'].includes(extension)) return 'json';
  if (['mmd', 'mermaid'].includes(extension)) return 'mermaid';
  if (filePreviewLanguage(name)) return 'code';
  if (TEXT_EXTENSIONS.has(extension) || TEXT_NAMES.has(lower)) return 'text';
  return null;
}

export function filePreviewLimit(kind: FilePreviewKind): number {
  return kind === 'image' ? IMAGE_PREVIEW_BYTES : kind === 'html' ? HTML_PREVIEW_BYTES
    : kind === 'pdf' ? PDF_PREVIEW_BYTES : TEXT_PREVIEW_BYTES;
}

function prepareTextPreview(kind: FilePreviewKind, bytes: Uint8Array<ArrayBuffer>, name: string): FilePreviewContent {
  const text = decodeText(bytes);
  const content: FilePreviewContent = { kind, text, url: '', width: 0, height: 0,
    renderMarkdown: kind === 'markdown' && bytes.byteLength <= MARKDOWN_RENDER_BYTES };
  try {
    if (kind === 'svg') {
      Object.assign(content, inspectPreviewSvg(text));
      // Original bytes retain a possible XML encoding declaration. SVG image
      // mode cannot run scripts or embed external resources in the parent DOM.
      content.url = URL.createObjectURL(new Blob([bytes], { type: 'image/svg+xml' }));
    } else if (kind === 'table') content.table = parsePreviewTable(text, /\.tsv$/i.test(name) ? '\t' : ',');
    else if (kind === 'json') content.json = parsePreviewJson(text, /\.(jsonl|ndjson)$/i.test(name));
    else if (kind === 'code' || kind === 'mermaid') {
      if (kind === 'code' ? text.length >= CODE_PREVIEW_CHARS : bytes.byteLength > MERMAID_PREVIEW_BYTES) {
        throw new Error('focus.filePreviewRichLarge');
      }
      if (kind === 'code') content.language = filePreviewLanguage(name);
      else content.renderedText = previewCodeFence(text, 'mermaid');
    }
  } catch (error) {
    // Rich-view failure must not discard the complete, already decoded source.
    content.renderError = error instanceof Error && error.message.startsWith('focus.filePreview')
      ? error.message : 'focus.filePreviewFailed';
  }
  return content;
}

function decodeText(bytes: Uint8Array): string {
  const encoding = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le'
    : bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : 'utf-8';
  let text: string;
  try { text = new TextDecoder(encoding, { fatal: true }).decode(bytes); }
  catch { throw new Error('focus.filePreviewEncoding'); }
  // Reject mislabeled binaries instead of showing replacement characters.
  if (/[\x00-\x08\x0e-\x1f]/.test(text)) throw new Error('focus.filePreviewEncoding');
  return text;
}

async function readPreviewBytes(response: Response, limit: number, signal: AbortSignal,
  progress: (size: number) => void): Promise<Uint8Array> {
  if (!response.body) throw new Error('focus.filePreviewFailed');
  const reader = response.body.getReader();
  const cancel = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancel, { once: true });
  try {
    signal.throwIfAborted();
    if (Number(response.headers.get('Content-Length')) > limit) throw new Error('focus.filePreviewTooLarge');
    let size = 0;
    const chunks: Uint8Array[] = [];
    for (;;) {
      const { done, value } = await reader.read();
      signal.throwIfAborted();
      if (done) break;
      size += value.byteLength;
      if (size > limit) throw new Error('focus.filePreviewTooLarge');
      chunks.push(value);
      progress(size);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return bytes;
  } finally {
    signal.removeEventListener('abort', cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function createFilePreview(api: Pick<FileDownloadApi, 'fileContent'>) {
  const opened = ref(false);
  const file = shallowRef<FocusFileInfo | null>(null);
  const line = ref<number | undefined>();
  const anchor = ref<string | undefined>();
  const loading = ref(false);
  const received = ref(0);
  const errorKey = ref('');
  const content = shallowRef<FilePreviewContent | null>(null);
  let operation: AbortController | null = null;

  function release(): void {
    operation?.abort();
    operation = null;
    if (content.value?.url) URL.revokeObjectURL(content.value.url);
    content.value = null;
  }

  function close(): void {
    release();
    opened.value = false;
    file.value = null;
    line.value = undefined;
    anchor.value = undefined;
    loading.value = false;
    received.value = 0;
    errorKey.value = '';
  }

  async function refresh(): Promise<void> {
    const target = file.value;
    if (!target) return;
    release();
    const controller = new AbortController();
    operation = controller;
    loading.value = true;
    errorKey.value = '';
    received.value = 0;
    try {
      const kind = filePreviewKind(target.name);
      if (!kind) throw new Error('focus.filePreviewUnsupported');
      // The metadata is only a hint. The response and stream enforce the limit
      // again, including files that grew since the dialog was opened.
      const bytes = await readPreviewBytes(await api.fileContent(target.path, controller.signal),
        filePreviewLimit(kind), controller.signal, size => { received.value = size; });
      controller.signal.throwIfAborted();
      if (kind === 'image') {
        const { width, height, mime } = inspectPreviewImage(bytes);
        content.value = { kind, text: '', url: URL.createObjectURL(new Blob([bytes as Uint8Array<ArrayBuffer>], { type: mime })),
          width, height, renderMarkdown: false };
      } else {
        content.value = kind === 'pdf'
          ? { kind, text: '', url: '', width: 0, height: 0, renderMarkdown: false, bytes: bytes as Uint8Array<ArrayBuffer> }
          : prepareTextPreview(kind, bytes as Uint8Array<ArrayBuffer>, target.name);
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        const key = error instanceof Error && error.message.startsWith('focus.filePreview')
          ? error.message : fileDownloadErrorKey(error);
        errorKey.value = key === 'focus.fileDownloadFailed' ? 'focus.filePreviewFailed' : key;
      }
    } finally {
      if (!controller.signal.aborted) loading.value = false;
    }
  }

  async function open(target: FocusFileInfo, targetLine?: number, targetAnchor?: string): Promise<void> {
    close();
    opened.value = true;
    file.value = target;
    line.value = targetLine;
    anchor.value = targetAnchor;
    const kind = filePreviewKind(target.name);
    if (!kind) { errorKey.value = 'focus.filePreviewUnsupported'; return; }
    if (target.size > filePreviewLimit(kind)) { errorKey.value = 'focus.filePreviewTooLarge'; return; }
    await refresh();
  }

  return { opened, file, line, anchor, loading, received, errorKey, content, open, close, refresh };
}

export type FilePreviewState = ReturnType<typeof createFilePreview>;
