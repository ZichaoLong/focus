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

Table splitting must protect complete, same-line `\(...\)` formulas: their
internal pipes must not separate columns or discard following cells. This
applies to headers, body rows, nested tables and closed streaming content in
both chat and print. Recognition follows the existing math syntax owner; code,
escaped delimiters, unclosed content and unsupported math forms do not become
formulas. Preserve the original pipes, backslashes and whitespace for source
fallback and formula copy; do not repair tables by replacing LaTeX commands or
rewriting stored content.

Chat Markdown and print prose allow browser weight synthesis when a real bold
font face is unavailable, keeping CJK emphasis visible. Do not enable synthetic
italics or change font policy elsewhere in the application. Font appearance
need not be pixel-identical across devices. These presentation rules do not
modify stored messages, copied source or exported Markdown.

Whole prose loading and long-reply display follow the [bounded transcript contract](focus-web-transcript-window.md#reply-times-and-long-replies).
`markdownChunks` parses the complete document with shared configuration before grouping,
preserving document-wide references and whole tables, lists, formulas and code blocks.
Long-reply diff fences retain every original addition/deletion for scrolling, without
ordinary diff preview head/tail omissions. Full copy uses the complete source string.

## Mermaid diagram viewing

Chat Mermaid retains the lazy strict renderer, source fallback, source copy and SVG export.
`MarkdownMermaid.vue` owns the presentation adapter: inline previews contain the whole diagram
within a viewport-bounded height. They do not capture dragging, wheel or touch gestures;
these continue browsing the conversation.

The existing expand action opens `MermaidViewer.vue` in a full-size dialog, using an isolated
image snapshot of sanitized SVG without running Mermaid again. Subsequent streaming content
does not replace that snapshot during interaction; reopening captures the current diagram.
`Markdown.vue` owns the viewer lifetime, outside chunk recycling and regrouping when streaming ends.
`ImageViewport.vue` owns the shared image canvas and gestures, also used by
[on-demand file previews](focus-web-file-download.md#on-demand-previews).
Opening fits the complete diagram. Controls offer fit, original size, zoom in and zoom out.
The minimum scale depends on diagram and viewport dimensions and can fall below 50%; the
maximum is four times the original size. Pan bounds keep the diagram reachable.
Mouse dragging, wheel/trackpad zoom, single-finger pan and two-finger pinch act only inside
the viewer. Pointer capture, cancellation, blur and viewport changes end or rebase gestures
so releasing cannot leave a stale drag. Arrow keys pan, plus/minus zoom, 0 fits, and Escape
or close exits, restoring the opener focus and reading position. The shared Dialog owns
focus trapping and Escape priority. Print diagrams remain static and exported source is unchanged.

## Verification boundary

Regression coverage includes CJK punctuation beside CJK text, Latin letters and
numbers, nested inline syntax, lists and tables, code and escapes, math,
streaming/final transitions, line breaks and
print. Browser checks use the actual Markdown component at wide and narrow
viewports to verify emphasis, font fallback, paragraphs and code lines, plus
mixed inline table content and horizontal scrolling with long-reply rendering
optimizations active.
Also check complete cells around pipe-containing formulas, copied source,
streaming closure and print fallback.
A narrow viewport does not establish compatibility with every device's fonts.

Mermaid checks include whole previews and fitting for very wide/tall diagrams, zoom anchors,
pan bounds, multi-touch and cancellation, rotation, conversation scroll restoration, source
fallback, copying and SVG export.
