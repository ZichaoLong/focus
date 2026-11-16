export interface PreviewJsonNode {
  id: number;
  label: string;
  value: string;
  children?: PreviewJsonNode[];
}
export const JSON_PREVIEW_NODES = 10_000;
export const JSON_PREVIEW_DEPTH = 64;

/** Keep numeric lexemes and duplicate keys: JSON.parse alone would lose both. */
export function parsePreviewJson(text: string, lines = false): PreviewJsonNode {
  let offset = 0, nodes = 0;
  const invalid = () => { throw new Error('focus.filePreviewJsonInvalid'); };
  function space(): void { while (/[\x20\t\r\n]/.test(text[offset] ?? '') && offset < text.length) offset++; }
  function string(): string {
    const start = offset++;
    while (offset < text.length) {
      const char = text[offset++]!;
      if (char === '\\') offset++;
      else if (char === '"') {
        const raw = text.slice(start, offset);
        try { JSON.parse(raw); } catch { return invalid(); }
        return raw;
      }
    }
    return invalid();
  }
  function value(label: string, depth: number): PreviewJsonNode {
    if (++nodes > JSON_PREVIEW_NODES || depth > JSON_PREVIEW_DEPTH) {
      throw new Error('focus.filePreviewStructuredLarge');
    }
    space();
    const node: PreviewJsonNode = { id: nodes, label, value: '' };
    const char = text[offset];
    if (char === '{' || char === '[') {
      offset++;
      node.value = char === '{' ? '{}' : '[]'; node.children = [];
      const end = char === '{' ? '}' : ']';
      space();
      if (text[offset] === end) { offset++; return node; }
      for (;;) {
        space();
        let key = String(node.children.length);
        if (char === '{') {
          if (text[offset] !== '"') return invalid();
          key = string(); space();
          if (text[offset++] !== ':') return invalid();
        }
        node.children.push(value(key, depth + 1)); space();
        if (text[offset] === end) { offset++; return node; }
        if (text[offset++] !== ',') return invalid();
      }
    }
    if (char === '"') node.value = string();
    else {
      const token = /^(?:true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?)/.exec(text.slice(offset));
      if (!token) return invalid();
      node.value = token[0]; offset += token[0].length;
    }
    return node;
  }
  if (lines) {
    const root: PreviewJsonNode = { id: 0, label: '$', value: '[]', children: [] };
    for (const [index, line] of text.split(/\r?\n/).entries()) {
      if (!line.trim()) continue;
      // A record is independently parsed, so unescaped line breaks cannot join records.
      const parsed = parsePreviewJson(line);
      const renumber = (node: PreviewJsonNode): void => {
        if (++nodes > JSON_PREVIEW_NODES) throw new Error('focus.filePreviewStructuredLarge');
        node.id = nodes; node.children?.forEach(renumber);
      };
      renumber(parsed); parsed.label = String(index + 1); root.children!.push(parsed);
    }
    return root;
  }
  const result = value('$', 0); space();
  if (offset !== text.length) return invalid();
  return result;
}
