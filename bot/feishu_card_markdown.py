from __future__ import annotations

import re

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]+)\)")


def contains_unsupported_embedded_image_markdown(text: str) -> bool:
    return bool(_MARKDOWN_IMAGE_RE.search(str(text or "")))


def sanitize_runtime_markdown_for_feishu_card(text: str) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""

    def _replace(match: re.Match[str]) -> str:
        alt_text = str(match.group(1) or "").strip() or "图片"
        target = str(match.group(2) or "").strip()
        if not target:
            return f"【图片】{alt_text}"
        return f"【图片】{alt_text}\n路径：`{target}`"

    return _MARKDOWN_IMAGE_RE.sub(_replace, normalized)
