# Focus Web Markdown prose rendering contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-markdown-rendering.zh-CN.md`.

## Emphasis and line breaks

`configureFocusMarkdown` in `web/src/lib/markdownParser.ts` owns the shared chat
and Q&A print parser configuration. `markdownMath.ts` still owns math syntax;
copy behavior follows the [Markdown copy contract](focus-web-markdown-copy.md).

Double-asterisk strong emphasis adjacent to Chinese, Japanese or Korean text
accepts punctuation inside its boundaries, including `**结论。**后续` and
`这里**“重点”**继续`. Markdown still pairs delimiters; do not repair presentation
by rewriting the whole source, inserting spaces or adding line breaks. Other
emphasis syntax retains its existing rules. Asterisks inside code, escapes,
link destinations and recognized formulas must not become prose emphasis.
The rule applies to streaming and historical replies and is shared by print.

Chat prose preserves ordinary newlines, explicit hard breaks and blank-line
paragraphs. Code retains its lines and indentation. A bold sentence without a
following source newline does not become a standalone heading or paragraph.

Chat Markdown and print prose allow browser weight synthesis when a real bold
font face is unavailable, keeping CJK emphasis visible. Do not enable synthetic
italics or change font policy elsewhere in the application. Font appearance
need not be pixel-identical across devices. These presentation rules do not
modify stored messages, copied source or exported Markdown.

## Verification boundary

Regression coverage includes CJK punctuation, nested inline syntax, lists and
tables, code and escapes, math, streaming/final transitions, line breaks and
print. Browser checks use the actual Markdown component at wide and narrow
viewports to verify emphasis, font fallback, paragraphs and code lines.
A narrow viewport does not establish compatibility with every device's fonts.
