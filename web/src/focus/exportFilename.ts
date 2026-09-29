/** Portable browser download names; never changes the exported content. */
export type ExportFormat = 'markdown' | 'jsonl' | 'print';

const EXTENSIONS = { markdown: '.md', jsonl: '.jsonl', print: '.pdf' } as const;
const FALLBACKS = { markdown: 'codex-conversation-summary', jsonl: 'codex-thread-data', print: 'codex-conversation-summary' } as const;
const MAX_FILENAME_BYTES = 200;

export function normalizeExportFilename(value: string, format: ExportFormat): string {
  const extension = EXTENSIONS[format];
  let stem = value.normalize('NFC')
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, '-')
    .trim().replace(/[. ]+$/g, '');
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
