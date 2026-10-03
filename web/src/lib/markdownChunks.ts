import { getMarkdown, parseMarkdownToStructure, type BaseNode } from 'markstream-vue';
import { configureFocusMarkdown } from './markdownParser';

export interface MarkdownChunk { nodes: BaseNode[]; characters: number; lines: number }

/** Parse once with document-wide references, then group whole top-level nodes. */
export function markdownChunks(source: string): MarkdownChunk[] {
  const md = configureFocusMarkdown(getMarkdown('focus-progressive-reply'));
  const nodes = parseMarkdownToStructure(source, md, { final: true, streamParse: false });
  // The upstream diff parser applies patches. Read the complete original fence
  // instead, including deletions, also when nested inside a list or quotation.
  function preserveDiff(value: unknown): void {
    if (!value || typeof value !== 'object') return;
    const node = value as Record<string, unknown>;
    if (node.type === 'code_block' && node.diff && typeof node.raw === 'string') {
      node.code = node.raw; node.language = 'diff'; node.diff = false;
      delete node.originalCode; delete node.updatedCode;
    }
    for (const child of Object.values(node)) {
      if (Array.isArray(child)) child.forEach(preserveDiff);
      else if (child && typeof child === 'object') preserveDiff(child);
    }
  }
  const chunks: MarkdownChunk[] = [];
  let chunk: MarkdownChunk = { nodes: [], characters: 0, lines: 0 };
  for (const node of nodes) {
    if (chunk.nodes.length && (chunk.characters + node.raw.length > 12_000 || chunk.nodes.length >= 24)) {
      chunks.push(chunk); chunk = { nodes: [], characters: 0, lines: 0 };
    }
    preserveDiff(node);
    chunk.nodes.push(node);
    chunk.characters += node.raw.length;
    chunk.lines += node.raw.split('\n').length;
  }
  if (chunk.nodes.length) chunks.push(chunk);
  return chunks;
}
