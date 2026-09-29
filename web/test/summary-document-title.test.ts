import { describe, expect, it } from 'vitest';
import { normalizeSummaryTitle, summaryDocumentBody, titleSummaryMarkdown } from '../src/focus/summaryDocumentTitle';
import { renderSummaryPrintMarkdown } from '../src/focus/summaryPrintMarkdown';

describe('independent document titles', () => {
  it('replaces only the generated heading and preserves all question/answer bytes', () => {
    const body = '\n范围说明\n\n## Question\n原样：**粗体**\n\n# Codex conversation summary\n```ts\nconst a = 1\n```\n';
    const source = `# Codex conversation summary\n${body}`;
    expect(titleSummaryMarkdown(source, '我的文档')).toBe(`# 我的文档\n${body}`);
    expect(summaryDocumentBody(source)).toBe(body);
  });

  it('treats user titles as literal text, including Markdown, HTML and entity syntax', () => {
    const title = '**加粗** [link](https://example.com) <script> &copy; `code` $1';
    const rendered = renderSummaryPrintMarkdown(titleSummaryMarkdown('# Codex conversation summary\n\n正文', title));
    expect(rendered.html).not.toContain('<strong>');
    expect(rendered.html).not.toContain('<a ');
    expect(rendered.html).not.toContain('<script>');
    expect(rendered.html).toContain('&lt;script&gt;');
    expect(rendered.html).toContain('&amp;copy;');
    expect(rendered.html).toContain('<p>正文</p>');
  });

  it('normalizes multiline and blank titles and never discards an unfamiliar leading heading', () => {
    expect(normalizeSummaryTitle('  一\n二\t三\u0000 ')).toBe('一 二 三');
    expect(normalizeSummaryTitle(' \r\n ')).toBe('Codex conversation summary');
    expect(summaryDocumentBody('# Other heading\n\nbody')).toBe('# Other heading\n\nbody');
    expect(summaryDocumentBody('# Codex conversation summary\r\n\r\nbody')).toBe('\r\nbody');
  });
});
