from __future__ import annotations

import re

_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]+)\)")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\n]+)\)")
_MARKDOWN_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_FENCED_CODE_OPEN_RE = re.compile(r"^([ \t]*)(`{3,}|~{3,})([^\n]*)$")


def contains_unsupported_embedded_image_markdown(text: str) -> bool:
    return bool(_MARKDOWN_IMAGE_RE.search(str(text or "")))


def ends_with_fenced_code_block(text: str) -> bool:
    normalized = str(text or "").rstrip()
    if not normalized:
        return False
    lines = normalized.splitlines()
    if not lines:
        return False
    last = lines[-1].strip()
    if not re.fullmatch(r"(`{3,}|~{3,})", last):
        return False
    fence_char = last[0]
    fence_len = len(last)
    for line in reversed(lines[:-1]):
        stripped = line.strip()
        if re.fullmatch(rf"{re.escape(fence_char)}{{{fence_len},}}.*", stripped):
            return True
    return False


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


def sanitize_terminal_result_markdown_for_feishu_json2(text: str) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""

    def _replace_image(match: re.Match[str]) -> str:
        alt_text = str(match.group(1) or "").strip() or "图片"
        target = str(match.group(2) or "").strip()
        if not target:
            return f"【图片】{alt_text}"
        return f"【图片】{alt_text}\n路径：`{target}`"

    sanitized = _MARKDOWN_IMAGE_RE.sub(_replace_image, normalized)
    return _normalize_fenced_code_blocks_for_feishu(sanitized)


def _normalize_fenced_code_blocks_for_feishu(text: str) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""
    lines = normalized.splitlines(keepends=True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        body = line.rstrip("\r\n")
        newline = line[len(body):]
        match = _FENCED_CODE_OPEN_RE.match(body)
        if match is None:
            output.append(line)
            index += 1
            continue

        indent = match.group(1)
        fence = match.group(2)
        fence_char = fence[0]
        fence_len = len(fence)
        info = str(match.group(3) or "").strip()
        opening_newline = newline or "\n"
        block: list[str] = [f"{fence}{info}{opening_newline}"]
        index += 1

        while index < len(lines):
            inner_line = lines[index]
            inner_body = inner_line.rstrip("\r\n")
            inner_newline = inner_line[len(inner_body):]
            stripped = inner_body.strip()
            if re.fullmatch(rf"{re.escape(fence_char)}{{{fence_len},}}", stripped):
                closing_newline = inner_newline or "\n"
                block.append(f"{stripped}{closing_newline}")
                index += 1
                break
            if indent and inner_body.startswith(indent):
                inner_body = inner_body[len(indent):]
            block.append(f"{inner_body}{inner_newline}")
            index += 1

        _append_blank_line_before_code_block(output)
        output.extend(block)
        _append_blank_line_after_code_block(output, lines, index)
    return "".join(output)


def _append_blank_line_before_code_block(output: list[str]) -> None:
    if not output:
        return
    previous = output[-1]
    if previous.strip():
        if not previous.endswith(("\n", "\r")):
            output[-1] = previous + "\n"
        output.append("\n")


def _append_blank_line_after_code_block(output: list[str], lines: list[str], next_index: int) -> None:
    if next_index >= len(lines):
        return
    if not lines[next_index].strip():
        return
    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] = output[-1] + "\n"
    output.append("\n")
