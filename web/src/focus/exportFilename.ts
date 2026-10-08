/** Portable browser download names; never changes the exported content. */
export type ExportFormat = 'markdown' | 'jsonl' | 'print';

const EXTENSIONS = { markdown: '.md', jsonl: '.jsonl', print: '.pdf' } as const;
const FALLBACKS = { markdown: 'codex-conversation-summary', jsonl: 'codex-thread-data', print: 'codex-conversation-summary' } as const;
const MAX_FILENAME_BYTES = 200;

function cleanFilename(value: string): string {
  return value.normalize('NFC')
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, '-')
    .trim().replace(/[. ]+$/g, '');
}

/** A single server file keeps its format; no export extension is imposed. */
export function normalizeDownloadFilename(value: string): string {
  let name = cleanFilename(value).replace(/^[. ]+/, '');
  if (/^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)/i.test(name)) name = `_${name}`;
  const extension = name.match(/\.[a-z0-9]{1,16}$/i)?.[0] ?? '';
  const stem = extension ? name.slice(0, -extension.length) : name;
  const encoder = new TextEncoder();
  let bytes = extension.length;
  let bounded = '';
  for (const character of stem) {
    bytes += encoder.encode(character).length;
    if (bytes > MAX_FILENAME_BYTES) break;
    bounded += character;
  }
  return bounded ? `${bounded.replace(/[. ]+$/g, '')}${extension}` : '';
}

export function normalizeExportFilename(value: string, format: ExportFormat): string {
  const extension = EXTENSIONS[format];
  let stem = cleanFilename(value);
  while (stem.toLowerCase().endsWith(extension)) {
    stem = stem.slice(0, -extension.length).trim().replace(/[. ]+$/g, '');
  }
  stem = stem.replace(/^[. ]+/, '');
  if (!stem) return '';
  // Windows reserves device names even when followed by an extension.
  if (/^(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])(?:\.|$)/i.test(stem)) stem = `_${stem}`;
  const encoder = new TextEncoder();
  let bounded = '';
  let bytes = extension.length;
  for (const character of stem) {
    bytes += encoder.encode(character).length;
    if (bytes > MAX_FILENAME_BYTES) break;
    bounded += character;
  }
  bounded = bounded.replace(/[. ]+$/g, '');
  while (bounded.toLowerCase().endsWith(extension)) {
    bounded = bounded.slice(0, -extension.length).trim().replace(/[. ]+$/g, '');
  }
  return `${bounded}${extension}`;
}

export function suggestExportFilename(title: string, format: ExportFormat): string {
  return normalizeExportFilename(title, format) || `${FALLBACKS[format]}${EXTENSIONS[format]}`;
}
