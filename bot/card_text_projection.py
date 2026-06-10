from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from bot.feishu_card_markdown import (
    contains_unsupported_embedded_image_markdown,
    ends_with_fenced_code_block,
    sanitize_terminal_result_markdown_for_feishu_json2,
)


TERMINAL_RESULT_CARD_TITLE = "Codex"
TERMINAL_RESULT_CARD_MARKER = "\u2063\u2060\u2064\u2060\u2063"
TERMINAL_RESULT_ELEMENT_ID_PREFIX = "fc_tr_"
TERMINAL_RESULT_SOURCE_NONE = "none"
TERMINAL_RESULT_SOURCE_STORE = "store"
TERMINAL_RESULT_SOURCE_CARD_LEGACY = "card_legacy"
TERMINAL_RESULT_SOURCE_CARD_DEGRADED = "card_degraded"
EXECUTION_CARD_TITLE_PREFIX = "Codex 执行过程"
_TERMINAL_RESULT_ELEMENT_ID_RE = re.compile(r"^fc_tr_([0-9a-f]{32})_([0-9a-f]{16})$")
_TEXT_NODE_TAGS = {"markdown", "plain_text", "lark_md"}
_IGNORED_TAGS = {
    "action",
    "button",
    "checkbox",
    "date_picker",
    "form",
    "input",
    "overflow",
    "picker_date",
    "picker_datetime",
    "picker_time",
    "select_img",
    "select_person",
    "select_static",
    "text_area",
    "textarea",
}


@dataclass(frozen=True, slots=True)
class CardTextProjection:
    text: str
    visible_text: str
    final_reply_text: str = ""
    terminal_result_id: str = ""
    terminal_result_checksum: str = ""
    final_reply_source: str = TERMINAL_RESULT_SOURCE_NONE

    @property
    def has_authoritative_final_reply(self) -> bool:
        return bool(self.final_reply_text) and self.final_reply_source == TERMINAL_RESULT_SOURCE_STORE


def terminal_result_checksum(final_reply_text: str) -> str:
    normalized = str(final_reply_text or "").strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def terminal_result_element_id(terminal_result_id: str, checksum: str) -> str:
    normalized_id = str(terminal_result_id or "").strip().lower()
    normalized_checksum = str(checksum or "").strip().lower()
    if not normalized_id or not normalized_checksum:
        return ""
    return f"{TERMINAL_RESULT_ELEMENT_ID_PREFIX}{normalized_id}_{normalized_checksum[:16]}"


def render_final_reply_text_block(final_reply_text: str) -> str:
    normalized = str(final_reply_text or "").strip()
    if not normalized:
        return ""
    if ends_with_fenced_code_block(normalized):
        return f"{normalized}\n{TERMINAL_RESULT_CARD_MARKER}"
    return f"{normalized}{TERMINAL_RESULT_CARD_MARKER}"


def render_terminal_result_card_content_for_feishu(final_reply_text: str) -> str:
    normalized = str(final_reply_text or "").strip()
    if not normalized:
        return ""
    projection = sanitize_terminal_result_markdown_for_feishu_json2(normalized)
    return render_final_reply_text_block(projection)


def can_render_terminal_result_card(final_reply_text: str, *, char_limit: int) -> bool:
    normalized = str(final_reply_text or "").strip()
    if not normalized:
        return False
    if TERMINAL_RESULT_CARD_MARKER in normalized:
        return False
    if contains_unsupported_embedded_image_markdown(normalized):
        return False
    budget = max(int(char_limit), 0)
    if budget <= 0:
        return False
    return len(render_terminal_result_card_content_for_feishu(normalized)) <= budget


def _contains_terminal_result_marker(text: str) -> bool:
    return TERMINAL_RESULT_CARD_MARKER in str(text or "")


def _split_terminal_result_payload(text: str) -> tuple[str, str]:
    normalized = str(text or "")
    if TERMINAL_RESULT_CARD_MARKER not in normalized:
        return normalized, ""
    visible, _, payload = normalized.partition(TERMINAL_RESULT_CARD_MARKER)
    return visible, payload


def _strip_terminal_result_marker(text: str) -> str:
    visible, _ = _split_terminal_result_payload(text)
    return visible


def project_interactive_card_text(content_dict: dict[str, Any]) -> CardTextProjection:
    terminal_projection = _project_terminal_result_card_text(content_dict)
    if terminal_projection is not None:
        return terminal_projection
    visible_text = _extract_visible_card_text(content_dict)
    return CardTextProjection(text=visible_text, visible_text=visible_text)


def is_terminal_result_card(content_dict: dict[str, Any]) -> bool:
    return _matches_terminal_result_card_contract(content_dict)


def is_execution_card(content_dict: dict[str, Any]) -> bool:
    header = content_dict.get("header") or {}
    if isinstance(header, dict):
        title = header.get("title") or {}
        if isinstance(title, dict):
            title_content = str(title.get("content", "") or "").strip()
            if title_content.startswith(EXECUTION_CARD_TITLE_PREFIX):
                template = str(header.get("template", "") or "").strip()
                return template in {"turquoise", "grey", "blue"}
    title_content = str(content_dict.get("title", "") or "").strip()
    return title_content.startswith(EXECUTION_CARD_TITLE_PREFIX)


def _project_terminal_result_card_text(
    content_dict: dict[str, Any],
) -> CardTextProjection | None:
    if not _matches_terminal_result_card_contract(content_dict):
        return None
    visible_text = _extract_visible_card_text(content_dict)
    final_reply_text = _extract_terminal_result_card_final_reply_text(content_dict)
    if not final_reply_text:
        return CardTextProjection(text="", visible_text=visible_text)
    terminal_result_id, checksum = _extract_terminal_result_card_id(content_dict)
    source = (
        TERMINAL_RESULT_SOURCE_CARD_DEGRADED
        if terminal_result_id
        else TERMINAL_RESULT_SOURCE_CARD_LEGACY
    )
    return CardTextProjection(
        text=final_reply_text,
        visible_text=visible_text,
        final_reply_text=final_reply_text,
        terminal_result_id=terminal_result_id,
        terminal_result_checksum=checksum,
        final_reply_source=source,
    )


def _matches_terminal_result_card_contract(content_dict: dict[str, Any]) -> bool:
    header = content_dict.get("header") or {}
    if isinstance(header, dict):
        title = header.get("title") or {}
        if isinstance(title, dict):
            if str(title.get("content", "") or "").strip() == TERMINAL_RESULT_CARD_TITLE:
                if str(header.get("template", "") or "").strip() == "green":
                    elements = _collect_root_elements(content_dict)
                    has_final_reply_block = any(
                        isinstance(element, dict)
                        and str(element.get("tag", "") or "").strip() == "markdown"
                        and _contains_terminal_result_marker(str(element.get("content", "") or ""))
                        for element in elements
                    )
                    if has_final_reply_block:
                        return True
    return _matches_history_rendered_terminal_result_contract(content_dict)


def _extract_terminal_result_card_final_reply_text(content_dict: dict[str, Any]) -> str:
    elements = _collect_root_elements(content_dict)
    for element in elements:
        if not isinstance(element, dict):
            continue
        if str(element.get("tag", "") or "").strip() != "markdown":
            continue
        content = str(element.get("content", "") or "")
        if _contains_terminal_result_marker(content):
            return _strip_terminal_result_marker(content).strip()
    history_rendered = _extract_history_rendered_terminal_result_text(content_dict)
    if history_rendered:
        return history_rendered
    return ""


def _extract_terminal_result_card_id(content_dict: dict[str, Any]) -> tuple[str, str]:
    for element in _collect_root_elements(content_dict):
        if not isinstance(element, dict):
            continue
        element_id = str(element.get("element_id", "") or "").strip()
        match = _TERMINAL_RESULT_ELEMENT_ID_RE.match(element_id)
        if match:
            return match.group(1), match.group(2)
    return "", ""


def _matches_history_rendered_terminal_result_contract(content_dict: dict[str, Any]) -> bool:
    title = str(content_dict.get("title", "") or "").strip()
    if title != TERMINAL_RESULT_CARD_TITLE:
        return False
    rendered_text = _history_rendered_card_text(content_dict)
    return _contains_terminal_result_marker(rendered_text)


def _extract_history_rendered_terminal_result_text(content_dict: dict[str, Any]) -> str:
    if not _matches_history_rendered_terminal_result_contract(content_dict):
        return ""
    rendered_text = _history_rendered_card_text(content_dict)
    return _strip_terminal_result_marker(rendered_text).strip()


def _history_rendered_text_nodes(content_dict: dict[str, Any]) -> list[str]:
    nodes: list[str] = []
    _collect_history_rendered_text_nodes(content_dict.get("elements"), nodes)
    return nodes


def _history_rendered_card_text(content_dict: dict[str, Any]) -> str:
    return _join_history_rendered_raw_text_nodes(_history_rendered_raw_text_nodes(content_dict))


def _history_rendered_raw_text_nodes(content_dict: dict[str, Any]) -> list[str]:
    nodes: list[str] = []
    _collect_history_rendered_raw_text_nodes(content_dict.get("elements"), nodes)
    return nodes


def _collect_history_rendered_text_nodes(node: Any, texts: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_history_rendered_text_nodes(item, texts)
        return
    if not isinstance(node, dict):
        return
    tag = str(node.get("tag", "") or "").strip()
    if tag == "text":
        normalized = _strip_terminal_result_marker(str(node.get("text", "") or node.get("content", "") or "")).strip()
        if normalized:
            texts.append(normalized)
        return
    for key in ("elements", "fields", "columns"):
        value = node.get(key)
        if isinstance(value, list):
            _collect_history_rendered_text_nodes(value, texts)
    for key in ("text", "title", "header", "body", "alt"):
        value = node.get(key)
        if isinstance(value, (dict, list)):
            _collect_history_rendered_text_nodes(value, texts)


def _collect_history_rendered_raw_text_nodes(node: Any, texts: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_history_rendered_raw_text_nodes(item, texts)
        return
    if not isinstance(node, dict):
        return
    tag = str(node.get("tag", "") or "").strip()
    if tag == "text":
        raw = str(node.get("text", "") or node.get("content", "") or "")
        if raw:
            texts.append(raw)
        return
    for key in ("elements", "fields", "columns"):
        value = node.get(key)
        if isinstance(value, list):
            _collect_history_rendered_raw_text_nodes(value, texts)
    for key in ("text", "title", "header", "body", "alt"):
        value = node.get(key)
        if isinstance(value, (dict, list)):
            _collect_history_rendered_raw_text_nodes(value, texts)


def _join_history_rendered_raw_text_nodes(nodes: list[str]) -> str:
    parts: list[str] = []
    previous = ""
    for raw in nodes:
        text = str(raw or "")
        if not text:
            continue
        if parts:
            if not previous.endswith(("\n", "\r")) and not text.startswith(("\n", "\r")):
                parts.append("\n")
        parts.append(text)
        previous = text
    return "".join(parts)


def _collect_root_elements(content_dict: dict[str, Any]) -> list[Any]:
    elements = content_dict.get("elements")
    if isinstance(elements, list):
        return elements
    body = content_dict.get("body")
    if isinstance(body, dict):
        body_elements = body.get("elements")
        if isinstance(body_elements, list):
            return body_elements
    return []


def _extract_visible_card_text(content_dict: dict[str, Any]) -> str:
    blocks: list[str] = []
    _append_block(blocks, content_dict.get("title", ""))
    _collect_visible_blocks(content_dict, blocks)
    return "\n\n".join(blocks).strip()


def _append_block(blocks: list[str], text: Any) -> None:
    normalized = _strip_terminal_result_marker(str(text or "")).strip()
    if not normalized:
        return
    if blocks and blocks[-1] == normalized:
        return
    blocks.append(normalized)


def _collect_visible_blocks(node: Any, blocks: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_visible_blocks(item, blocks)
        return
    if not isinstance(node, dict):
        return

    tag = str(node.get("tag", "") or "").strip()
    if tag in _IGNORED_TAGS:
        return
    if tag == "text":
        _append_block(blocks, node.get("text") or node.get("content"))
        return
    if tag in _TEXT_NODE_TAGS:
        _append_block(blocks, node.get("content", ""))
        return
    if tag == "img":
        alt = node.get("alt")
        if isinstance(alt, dict):
            _collect_visible_blocks(alt, blocks)
        else:
            _append_block(blocks, alt)
        return
    if tag == "div":
        _collect_visible_blocks(node.get("text"), blocks)
        _collect_visible_blocks(node.get("fields"), blocks)
        return
    if tag == "note":
        _collect_visible_blocks(node.get("elements"), blocks)
        return
    if tag == "column_set":
        _collect_visible_blocks(node.get("columns"), blocks)
        return
    if tag == "column":
        _collect_visible_blocks(node.get("elements"), blocks)
        return
    if tag == "collapsible_panel":
        header = node.get("header") or {}
        if isinstance(header, dict):
            _collect_visible_blocks(header.get("title"), blocks)
        _collect_visible_blocks(node.get("elements"), blocks)
        return
    if tag == "header":
        _collect_visible_blocks(node.get("title"), blocks)
        return
    if tag == "body":
        _collect_visible_blocks(node.get("elements"), blocks)
        return
    if tag == "hr":
        return

    header = node.get("header")
    if isinstance(header, dict):
        _collect_visible_blocks(header, blocks)
    body = node.get("body")
    if isinstance(body, dict):
        _collect_visible_blocks(body, blocks)
    elif isinstance(body, list):
        _collect_visible_blocks(body, blocks)
    title = node.get("title")
    if isinstance(title, dict):
        _collect_visible_blocks(title, blocks)
    text = node.get("text")
    if isinstance(text, dict):
        _collect_visible_blocks(text, blocks)
    fields = node.get("fields")
    if isinstance(fields, list):
        _collect_visible_blocks(fields, blocks)
    elements = node.get("elements")
    if isinstance(elements, list):
        _collect_visible_blocks(elements, blocks)
