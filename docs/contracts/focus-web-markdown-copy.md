# Focus Web Markdown copy contract

Document role: synchronized English peer. Canonical Chinese: `docs/contracts/focus-web-markdown-copy.zh-CN.md`.

## Scope and payload

Browser Markdown provides individual copy buttons for code fences, plain-text
fences, diff fences, and recognized inline and display formulas. Ordinary prose
and inline code continue to use text selection or whole-reply copying.

- Code and text fences copy their complete contents with whitespace preserved,
  excluding Markdown fences. The simplified pre renderer for heavy messages
  and highlighter fallbacks retain a copy button.
- Diff fences copy the complete source, including signs and omitted display rows.
- Formula buttons say “Copy LaTeX” and copy the original formula body, preserving
  whitespace and backslashes but excluding math delimiters. Neither rendered
  KaTeX DOM nor normalized rendering text may supply the clipboard payload.

## Formula recognition and failure behavior

`web/src/lib/markdownMath.ts` owns recognition. Copy controls consume its parsed
nodes without adding formula heuristics. Inline math uses same-line closed
`\(...\)`; display math uses block-position `\[...\]` or `$$...$$`. Code,
escaped content, single-dollar syntax, prose-position block delimiters, and
unclosed content remain text.

Recognized formulas remain copyable while loading or when rendering fails and
shows source. Unclosed streaming formulas receive a button only once closed and
parsed. Formula-like ordinary text does not receive an automatic formula button.

## Presentation and clipboard

The Markdown presentation layer owns formula and code copy controls.
Formula buttons support keyboard and touch input; horizontal display-math
scrolling must not conceal them. Clipboard writes reuse the browser API and
plain-HTTP fallback in `web/src/lib/clipboard.ts`. New controls report “Copied”
only after successful writes and suggest selecting text when copying fails.
Copying does not change source messages, math grammar, threads, or server state.
