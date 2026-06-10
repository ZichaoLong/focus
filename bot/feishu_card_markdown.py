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
        block, index = _collect_fence_block(
            lines,
            index,
            indent=indent,
            fence_char=fence_char,
            fence_len=fence_len,
            info=info,
            opening_newline=newline or "\n",
        )
        _append_blank_line_before_code_block(output)
        output.extend(block)
        _append_blank_line_after_code_block(output, lines, index)
    return "".join(output)


def _collect_fence_block(
    lines: list[str],
    opening_index: int,
    *,
    indent: str,
    fence_char: str,
    fence_len: int,
    info: str,
    opening_newline: str,
) -> tuple[list[str], int]:
    closing_index = _find_fence_closing_index(lines, opening_index + 1, fence_char, fence_len)
    opening_fence = fence_char * fence_len
    if closing_index is None:
        return [f"{opening_fence}{info}{opening_newline}"], opening_index + 1
    content = _normalize_fence_content_indent(lines[opening_index + 1:closing_index], indent)
    closing_line = lines[closing_index]
    closing_body = closing_line.rstrip("\r\n")
    closing_newline = closing_line[len(closing_body):] or "\n"
    required_len = max(fence_len, _max_line_start_fence_len(content, fence_char) + 1)
    upgraded_fence = fence_char * required_len
    block = [f"{upgraded_fence}{info}{opening_newline}"]
    block.extend(content)
    block.append(f"{upgraded_fence}{closing_newline}")
    return block, closing_index + 1


def _find_fence_closing_index(
    lines: list[str],
    start_index: int,
    fence_char: str,
    fence_len: int,
) -> int | None:
    nested_closings_to_skip = 0
    last_matching_fence: int | None = None
    index = start_index
    while index < len(lines):
        line = lines[index]
        body = line.rstrip("\r\n")
        stripped = body.strip()
        if _is_same_length_fence_opener(stripped, fence_char, fence_len):
            nested_closings_to_skip += 1
            index += 1
            continue
        if re.fullmatch(rf"{re.escape(fence_char)}{{{fence_len},}}", stripped):
            if (
                not nested_closings_to_skip
                and _bare_fence_opens_nested_block_before_outer_close(
                    lines,
                    index + 1,
                    fence_char,
                    fence_len,
                )
            ):
                nested_closings_to_skip += 1
                index += 1
                continue
            last_matching_fence = index
            if nested_closings_to_skip:
                nested_closings_to_skip -= 1
            else:
                return index
        index += 1
    return last_matching_fence


def _bare_fence_opens_nested_block_before_outer_close(
    lines: list[str],
    start_index: int,
    fence_char: str,
    fence_len: int,
) -> bool:
    inner_closing_index = _next_matching_fence_index(lines, start_index, fence_char, fence_len)
    if inner_closing_index is None:
        return False
    outer_closing_index = _next_nonblank_index(lines, inner_closing_index + 1)
    if outer_closing_index is None:
        return False
    return _is_same_length_bare_fence(lines[outer_closing_index], fence_char, fence_len)


def _next_matching_fence_index(
    lines: list[str],
    start_index: int,
    fence_char: str,
    fence_len: int,
) -> int | None:
    for index in range(start_index, len(lines)):
        if _is_same_length_bare_fence(lines[index], fence_char, fence_len):
            return index
    return None


def _next_nonblank_index(lines: list[str], start_index: int) -> int | None:
    for index in range(start_index, len(lines)):
        if lines[index].strip():
            return index
    return None


def _is_same_length_bare_fence(line: str, fence_char: str, fence_len: int) -> bool:
    body = line.rstrip("\r\n")
    stripped = body.strip()
    return stripped == fence_char * fence_len


def _is_same_length_fence_opener(stripped_line: str, fence_char: str, fence_len: int) -> bool:
    marker = re.escape(fence_char)
    return bool(
        re.fullmatch(rf"{marker}{{{fence_len},}}[^\s`~].*", stripped_line)
        or re.fullmatch(rf"{marker}{{{fence_len},}}[ \t]+[^\s`~].*", stripped_line)
    )


def _normalize_fence_content_indent(lines: list[str], indent: str) -> list[str]:
    if not indent:
        return list(lines)
    normalized: list[str] = []
    for line in lines:
        body = line.rstrip("\r\n")
        newline = line[len(body):]
        if body.startswith(indent):
            body = body[len(indent):]
        normalized.append(f"{body}{newline}")
    return normalized


def _max_line_start_fence_len(lines: list[str], fence_char: str) -> int:
    max_len = 0
    for line in lines:
        body = line.rstrip("\r\n")
        stripped = body.strip()
        match = re.match(rf"{re.escape(fence_char)}{{3,}}", stripped)
        if match:
            max_len = max(max_len, len(match.group(0)))
    return max_len


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
