from __future__ import annotations

import re

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]+)\)")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\n]+)\)")
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)


def contains_unsupported_embedded_image_markdown(text: str) -> bool:
    return bool(_MARKDOWN_IMAGE_RE.search(str(text or "")))


def sanitize_runtime_markdown_for_feishu_card(text: str) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""

    def _replace_image(match: re.Match[str]) -> str:
        alt_text = str(match.group(1) or "").strip() or "图片"
        target = str(match.group(2) or "").strip()
        if not target:
            return f"【图片】{alt_text}"
        return f"【图片】{alt_text}\n路径：`{target}`"

    def _replace_link(match: re.Match[str]) -> str:
        label = str(match.group(1) or "").strip()
        target = str(match.group(2) or "").strip()
        if not target:
            return label
        if not label or label == target or target in label:
            return label or target
        if label.endswith(("：", ":")):
            return f"{label}{target}"
        return f"{label} ({target})"

    def _replace_heading(match: re.Match[str]) -> str:
        level = len(str(match.group(1) or ""))
        title = str(match.group(2) or "").strip()
        if not title:
            return ""
        marker = {
            1: "【标题】",
            2: "【小节】",
            3: "【三级标题】",
            4: "【四级标题】",
            5: "【五级标题】",
            6: "【六级标题】",
        }.get(level, "【标题】")
        return f"{marker} {title}"

    sanitized = _MARKDOWN_HEADING_RE.sub(_replace_heading, normalized)
    sanitized = _MARKDOWN_IMAGE_RE.sub(_replace_image, sanitized)
    return _MARKDOWN_LINK_RE.sub(_replace_link, sanitized)
