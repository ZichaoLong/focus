import { describe, expect, it } from 'vitest';
import { renderSummaryPrintMarkdown as render } from '../src/focus/summaryPrintMarkdown';

describe('complete printable Q&A Markdown', () => {
  it('uses the same CJK emphasis grammar as chat without changing code or paragraph breaks', () => {
    const { html } = render('**结论。**后续\n\n这里**“重点”**继续\n\n`**代码。**后续`');
    expect(html).toContain('<p><strong>结论。</strong>后续</p>');
    expect(html).toContain('<p>这里<strong>“重点”</strong>继续</p>');
    expect(html).toContain('<code>**代码。**后续</code>');
  });

  it('preserves every code/diff line, tables and earlier and final turns', () => {
    const lines = Array.from({ length: 200 }, (_, index) => `+line-${index}`);
    const { html } = render(`# Q&A\n\n## 1. Earliest\n\n### User\n\nQuestion\n\n### Assistant\n\n\`\`\`diff\n${lines.join('\n')}\n\`\`\`\n\n| Column | Value |\n| --- | --- |\n| 中文 | hello |\n\n## 2. Latest\n\nLast reply`);
    for (const line of lines) expect(html).toContain(line);
    expect(html).toContain('<table>');
    expect(html).toContain('中文');
    expect(html).toContain('Last reply');
    expect(html).not.toContain('code-editor');
    expect(html).not.toContain('<button');
  });

  it('uses exact Focus delimiters and preserves unsupported/unclosed math and code', () => {
    const { html, fallback } = render(String.raw`Inline \(x^2\), $cash$ and \(unclosed

\[
\frac{1}{2}
\]

$$ y^2 $$

\[unclosed` + '\n\n`\\(code\\)`');
    expect((html.match(/class="summary-math"/g) ?? [])).toHaveLength(3);
    expect(html).toContain('$cash$');
    expect(html).toContain(String.raw`\(unclosed`);
    expect(html).toContain(String.raw`\[unclosed`);
    expect(html).toContain(String.raw`<code>\(code\)</code>`);
    expect(fallback).toBe(false);
  });

  it('retains the original delimiters when KaTeX rejects a formula', () => {
    const { html, fallback } = render(String.raw`Broken \(\unknowncommand{x}\).`);
    expect(html).toContain(String.raw`\(\unknowncommand{x}\)`);
    expect(fallback).toBe(true);
  });

  it('escapes untrusted HTML and rejects active URLs, including in formulas', () => {
    const { html } = render(String.raw`<script>alert(1)</script>

[click](javascript:alert(1)) ![attack](javascript:alert(1))

\(\href{javascript:alert(1)}{bad}\)` + '\n\n```html\n<img src=x onerror="alert(1)">\n```');
    expect(html).not.toContain('<script');
    expect(html).not.toContain('<img');
    expect(html).not.toContain('href="javascript:');
    expect(html).toContain('&lt;script&gt;');
    expect(html).toContain('&lt;img');
  });

  it('keeps unavailable local images and malformed fenced content visible', () => {
    const { html, fallback } = render('![local](/tmp/chart.png)\n\n```python\nunterminated\n\n### Assistant\nStill here');
    expect(html).toContain('![local](/tmp/chart.png)');
    expect(html).toContain('Still here');
    expect(fallback).toBe(true);
  });
});
