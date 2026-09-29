/** The export title is plain text, independent of the download filename. */
export const DEFAULT_SUMMARY_TITLE = 'Codex conversation summary';

export function normalizeSummaryTitle(title: string): string {
  return title.replace(/[\s\u0000-\u001f\u007f-\u009f]+/gu, ' ').trim() || DEFAULT_SUMMARY_TITLE;
}

export function summaryDocumentBody(markdown: string): string {
  // Only the exporter's own leading heading is replaceable. Never remove a
  // heading from a question/answer, including one with the same text.
  const heading = `# ${DEFAULT_SUMMARY_TITLE}`;
  if (markdown === heading) return '';
  if (markdown.startsWith(`${heading}\r\n`)) return markdown.slice(heading.length + 2);
  if (markdown.startsWith(`${heading}\n`)) return markdown.slice(heading.length + 1);
  return markdown;
}

export function titleSummaryMarkdown(markdown: string, title: string): string {
  const escaped = normalizeSummaryTitle(title).replace(/[\\`*_{}\[\]()#+\-.!|<>~&]/g, '\\$&');
  const body = summaryDocumentBody(markdown);
  return `# ${escaped}\n${body.startsWith('\n') || body.startsWith('\r\n') ? '' : '\n'}${body}`;
}
