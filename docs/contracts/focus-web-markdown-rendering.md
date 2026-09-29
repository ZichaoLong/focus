# Focus Web Markdown prose rendering contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-markdown-rendering.zh-CN.md`.

## Emphasis and line breaks

`configureFocusMarkdown` in `web/src/lib/markdownParser.ts` owns the shared chat
and Q&A print parser configuration. `markdownMath.ts` still owns math syntax;
copy behavior follows the [Markdown copy contract](focus-web-markdown-copy.md).

Double-asterisk strong emphasis adjacent to Chinese, Japanese or Korean text
accepts punctuation inside its boundaries, including `**结论。**后续` and
`这里**“重点”**继续`. Outside letters or numbers are also accepted when the inside
punctuation is CJK-specific/fullwidth, or its punctuation run directly adjoins
CJK text on the inside: `**结论。**Mamba`, `RoPE**（局部）**2`, and
`2026**“中文”**Next`. Shared quotes and punctuation in purely English text keep
their existing rules. Markdown still pairs delimiters; do not repair presentation
by rewriting the whole source, inserting spaces or adding line breaks. Other
emphasis syntax retains its existing rules. Asterisks inside code, escapes,
link destinations and recognized formulas must not become prose emphasis.
The rule applies to streaming and historical replies and is shared by print.

Chat prose preserves ordinary newlines, explicit hard breaks and blank-line
paragraphs. Code retains its lines and indentation. A bold sentence without a
following source newline does not become a standalone heading or paragraph.

Text, inline math, emphasis, links and inline code inside table cells share one
inline flow. Long-reply rendering optimizations and inline-node boundaries must
not introduce line breaks or paragraph gaps. Paragraph spacing does not apply
to inline cell fragments. Cells may still wrap naturally to their available
width, and wide tables continue to scroll horizontally within their own wrapper.

Chat Markdown and print prose allow browser weight synthesis when a real bold
font face is unavailable, keeping CJK emphasis visible. Do not enable synthetic
italics or change font policy elsewhere in the application. Font appearance
need not be pixel-identical across devices. These presentation rules do not
modify stored messages, copied source or exported Markdown.

## Verification boundary

Regression coverage includes CJK punctuation beside CJK text, Latin letters and
numbers, nested inline syntax, lists and tables, code and escapes, math,
streaming/final transitions, line breaks and
print. Browser checks use the actual Markdown component at wide and narrow
viewports to verify emphasis, font fallback, paragraphs and code lines, plus
mixed inline table content and horizontal scrolling with long-reply rendering
optimizations active.
A narrow viewport does not establish compatibility with every device's fonts.
