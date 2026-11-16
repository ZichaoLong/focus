export const TABLE_PREVIEW_CELLS = 100_000;
export const TABLE_PREVIEW_COLUMNS = 200;

/** RFC 4180 quoting, also used with a tab delimiter; values remain exact strings. */
export function parsePreviewTable(text: string, delimiter: ',' | '\t'): string[][] {
  if (!text) return [];
  const rows: string[][] = [];
  let row: string[] = [], field = '', quoted = false, closed = false, cells = 0;
  const invalid = () => { throw new Error('focus.filePreviewTableInvalid'); };
  const pushField = () => {
    if (++cells > TABLE_PREVIEW_CELLS || row.length >= TABLE_PREVIEW_COLUMNS) {
      throw new Error('focus.filePreviewStructuredLarge');
    }
    row.push(field); field = ''; closed = false;
  };
  for (let i = 0; i < text.length; i++) {
    const char = text[i]!;
    if (quoted) {
      if (char === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else { quoted = false; closed = true; }
      } else field += char;
    } else if (char === delimiter) pushField();
    else if (char === '\r' || char === '\n') {
      pushField(); rows.push(row); row = [];
      if (char === '\r' && text[i + 1] === '\n') i++;
    } else if (closed) return invalid();
    else if (char === '"') {
      if (field) return invalid();
      quoted = true;
    } else field += char;
  }
  if (quoted) return invalid();
  if (row.length || field || closed || !/[\r\n]$/.test(text)) { pushField(); rows.push(row); }
  return rows;
}
